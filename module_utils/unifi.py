"""Small client for the UniFi controller API used by local Ansible modules."""

import json
import time
from http.client import HTTPException
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit

from ansible.module_utils.urls import Request


class UnifiError(Exception):
    """An API error safe to display without including credentials or responses."""


class UnifiNotFound(UnifiError):
    pass


class UnifiUncertain(UnifiError):
    """A request may have reached the controller; do not blindly retry writes."""


class UnifiClient:
    def __init__(self, params):
        base = urlsplit(params["api_url"])
        if (
            base.scheme not in ("http", "https")
            or not base.hostname
            or base.username is not None
            or base.password is not None
            or base.path not in ("", "/")
            or base.query
            or base.fragment
        ):
            raise UnifiError(
                "api_url must be a controller origin, e.g. https://192.0.2.1, without a path or credentials"
            )
        self.base = params["api_url"].rstrip("/")
        self.site = quote(params["site"], safe="")
        self.kind = params["controller_type"]
        self.prefix = "/proxy/network" if self.kind == "unifi_os" else ""
        self.path = self.prefix + "/api/s/" + self.site + "/rest/portforward"
        self.api_key = params.get("api_key")
        if self.api_key and self.kind != "unifi_os":
            raise UnifiError("API-key authentication requires controller_type=unifi_os")
        self.username = params.get("username")
        self.password = params.get("password")
        if not self.api_key and not (self.username and self.password):
            raise UnifiError(
                "Supply a non-empty API key or local username and password"
            )
        self.request_timeout = params["request_timeout"]
        self.timeouts = params["timeouts"]
        self.csrf = None
        self.session = Request(
            validate_certs=params["validate_certs"],
            timeout=self.request_timeout,
            cookies=CookieJar(),
            follow_redirects="none",
            use_proxy=False,
            use_netrc=False,
        )
        self.start_operation("read")

    def start_operation(self, operation):
        self.deadline = time.monotonic() + self.timeouts[operation]

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise UnifiUncertain(
                "UniFi operation deadline exceeded; read current state before retrying"
            )
        return min(self.request_timeout, remaining)

    def _pause(self, attempt, headers=None):
        delay = 0.5 * 2**attempt
        if headers:
            try:
                delay = min(30, max(delay, float(headers.get("Retry-After", 0))))
            except (TypeError, ValueError):
                pass
        remaining = self.deadline - time.monotonic()
        if delay >= remaining:
            raise UnifiUncertain("UniFi operation deadline exceeded during retry")
        time.sleep(delay)

    def request(self, method, path, payload=None):
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        data = json.dumps(payload).encode() if payload is not None else None
        # Only reads are retried. A lost POST response must not create duplicates.
        for attempt in range(3):
            try:
                response = self.session.open(
                    method,
                    self.base + path,
                    data=data,
                    headers=headers,
                    timeout=self._remaining(),
                )
                try:
                    self.csrf = (
                        response.headers.get("X-Updated-CSRF-Token")
                        or response.headers.get("X-CSRF-Token")
                        or self.csrf
                    )
                    raw = response.read()
                finally:
                    response.close()
            except HTTPError as error:
                status = error.code
                retry_headers = error.headers
                error.close()
                if method == "GET" and status in (429, 502, 503, 504) and attempt < 2:
                    self._pause(attempt, retry_headers)
                    continue
                if status == 404:
                    raise UnifiNotFound(
                        "UniFi endpoint or rule not found (HTTP 404)"
                    ) from None
                if status in (401, 403):
                    raise UnifiError(
                        f"UniFi authentication or permission denied (HTTP {status})"
                    ) from None
                if status >= 500:
                    raise UnifiUncertain(
                        f"UniFi returned HTTP {status}; the write outcome may be unknown"
                    ) from None
                raise UnifiError(
                    f"UniFi request failed (HTTP {status}); check controller type and rule parameters"
                ) from None
            except (URLError, OSError, HTTPException) as error:
                if method == "GET" and attempt < 2:
                    self._pause(attempt)
                    continue
                # Exception text can contain an origin, headers, or credentials.
                raise UnifiUncertain(
                    f"UniFi connection failed ({type(error).__name__}); check reachability, TLS, and timeout"
                ) from None
            try:
                body = json.loads(raw) if raw else {}
            except (ValueError, UnicodeError):
                raise UnifiUncertain(
                    "UniFi returned an invalid JSON response"
                ) from None
            if not isinstance(body, dict):
                raise UnifiUncertain("UniFi returned an unexpected response shape")
            meta = body.get("meta", {})
            if not isinstance(meta, dict) or meta.get("rc", "ok") != "ok":
                raise UnifiError(
                    "UniFi reported an API error; check rule parameters and permissions"
                )
            return body
        raise UnifiError("UniFi read retries exhausted")

    def login(self):
        if not self.api_key:
            path = "/api/auth/login" if self.kind == "unifi_os" else "/api/login"
            self.request(
                "POST", path, {"username": self.username, "password": self.password}
            )

    @staticmethod
    def _rows(body):
        rows = body.get("data")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise UnifiUncertain("UniFi response is missing a valid data array")
        return rows

    def list_rules(self):
        # A missing collection endpoint must not be treated as an empty site.
        rows = self._rows(self.request("GET", self.path))
        ids = [row.get("_id") for row in rows]
        if any(not isinstance(key, str) or not key for key in ids) or len(
            set(ids)
        ) != len(ids):
            raise UnifiError("UniFi returned rules with missing or duplicate IDs")
        return rows

    def get_rule(self, rule_id):
        try:
            rows = self._rows(
                self.request("GET", self.path + "/" + quote(rule_id, safe=""))
            )
        except UnifiNotFound:
            return None
        if not rows:
            return None
        if len(rows) != 1 or rows[0].get("_id") != rule_id:
            raise UnifiError("UniFi returned an unexpected rule ID")
        return rows[0]

    def create_rule(self, payload):
        rows = self._rows(self.request("POST", self.path, payload))
        if len(rows) != 1 or not rows[0].get("_id"):
            raise UnifiUncertain("UniFi did not return the created rule ID")
        return rows[0]

    def update_rule(self, rule_id, payload):
        self.request("PUT", self.path + "/" + quote(rule_id, safe=""), payload)

    def delete_rule(self, rule_id):
        try:
            self.request("DELETE", self.path + "/" + quote(rule_id, safe=""), {})
        except UnifiNotFound:
            pass
