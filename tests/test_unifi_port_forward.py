"""Offline regression tests; never contact a real UniFi controller."""

import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


api = load("ansible.module_utils.unifi", ROOT / "module_utils/unifi.py")
rule = load("unifi_port_forward", ROOT / "library/unifi_port_forward.py")


def params(**updates):
    result = {
        "api_url": "https://192.0.2.1",
        "api_key": "secret-test-key",
        "controller_type": "unifi_os",
        "validate_certs": True,
        "request_timeout": 30,
        "timeouts": dict.fromkeys(("create", "read", "update", "delete"), 1200),
        "site": "default",
        "name": "Test forward",
        "state": "present",
    }
    result.update(updates)
    return result


def creation(**updates):
    result = params(wan={"port": "443"}, forward={"ip": "192.0.2.10"})
    result.update(updates)
    return result


def existing(**updates):
    result = rule.desired_rule(creation(), None)
    result.update({"_id": "rule-1", "site_id": "site-1"})
    result.update(updates)
    return result


class FakeClient:
    def __init__(self, rows=()):
        self.rows = copy.deepcopy(list(rows))
        self.writes = []
        self.uncertain_create = False

    def login(self):
        pass

    def start_operation(self, operation):
        pass

    def list_rules(self):
        return copy.deepcopy(self.rows)

    def get_rule(self, rule_id):
        return copy.deepcopy(
            next((row for row in self.rows if row["_id"] == rule_id), None)
        )

    def create_rule(self, payload):
        row = dict(copy.deepcopy(payload), _id="created-1")
        self.rows.append(row)
        self.writes.append(("POST", payload))
        if self.uncertain_create:
            raise api.UnifiUncertain("lost response")
        return copy.deepcopy(row)

    def update_rule(self, rule_id, payload):
        self.rows = [
            dict(copy.deepcopy(payload), _id=rule_id) if row["_id"] == rule_id else row
            for row in self.rows
        ]
        self.writes.append(("PUT", payload))

    def delete_rule(self, rule_id):
        self.rows = [row for row in self.rows if row["_id"] != rule_id]
        self.writes.append(("DELETE", rule_id))


class RuleTests(unittest.TestCase):
    def test_lifecycle_and_repeated_runs(self):
        client = FakeClient()
        result = rule.reconcile(creation(), client)
        self.assertTrue(result["changed"])
        self.assertEqual(result["rule"]["forward"]["port"], "443")
        self.assertFalse(rule.reconcile(creation(), client)["changed"])
        self.assertTrue(rule.reconcile(params(logging=True), client)["changed"])
        self.assertFalse(rule.reconcile(params(logging=True), client)["changed"])
        self.assertTrue(rule.reconcile(params(state="absent"), client)["changed"])
        self.assertFalse(rule.reconcile(params(state="absent"), client)["changed"])
        self.assertEqual(
            [method for method, _ in client.writes], ["POST", "PUT", "DELETE"]
        )

    def test_check_mode_predicts_create_update_delete_without_writes(self):
        for config, rows in (
            (creation(), []),
            (params(enabled=False), [existing()]),
            (params(state="absent"), [existing()]),
        ):
            with self.subTest(config=config):
                client = FakeClient(rows)
                result = rule.reconcile(config, client, check_mode=True, diff=True)
                self.assertTrue(result["changed"])
                self.assertNotEqual(result["diff"]["before"], result["diff"]["after"])
                self.assertEqual(client.writes, [])
                self.assertNotIn("secret-test-key", json.dumps(result))

    def test_omitted_fields_adopt_and_preserve_unknown_settings(self):
        row = existing(
            proto="udp", log=True, enabled=False, future_setting={"value": 42}
        )
        client = FakeClient([row])
        self.assertFalse(rule.reconcile(params(), client)["changed"])
        rule.reconcile(params(forward={"port": "8443", "ip": None}), client)
        updated = client.rows[0]
        self.assertEqual(updated["fwd"], row["fwd"])
        self.assertEqual(updated["proto"], "udp")
        self.assertEqual(updated["future_setting"], {"value": 42})
        self.assertNotIn("site_id", client.writes[0][1])

    def test_missing_controller_defaults_do_not_cause_drift(self):
        row = existing()
        for key in (
            "src",
            "src_limiting_type",
            "src_firewall_group_id",
            "src_limiting_enabled",
            "destination_ips",
            "fwd_port",
        ):
            del row[key]
        client = FakeClient([row])
        self.assertFalse(rule.reconcile(creation(), client)["changed"])

    def test_duplicate_names_fail_but_explicit_id_disambiguates(self):
        client = FakeClient([existing(), existing(_id="rule-2")])
        with self.assertRaisesRegex(api.UnifiError, "Multiple"):
            rule.reconcile(params(state="absent"), client)
        rule.reconcile(params(id="rule-1", name="Renamed"), client)
        self.assertEqual(client.rows[0]["name"], "Renamed")
        self.assertEqual(client.rows[1]["name"], "Test forward")

    def test_unknown_id_does_not_create_or_fall_back_to_name(self):
        client = FakeClient([existing()])
        with self.assertRaisesRegex(api.UnifiError, "id does not exist"):
            rule.reconcile(creation(id="stale"), client)
        self.assertFalse(
            rule.reconcile(params(id="stale", state="absent"), client)["changed"]
        )
        self.assertEqual(client.writes, [])

    def test_creation_requires_forwarding_fields(self):
        with self.assertRaisesRegex(
            api.UnifiError, "requires name, wan.port, and forward.ip"
        ):
            rule.reconcile(params(), FakeClient())

    def test_source_type_switch_clears_inactive_fields(self):
        client = FakeClient([existing(src="203.0.113.1", src_limiting_enabled=True)])
        rule.reconcile(params(source_limiting={"firewall_group_id": "trusted"}), client)
        self.assertEqual(client.rows[0]["src_limiting_type"], "firewall_group")
        self.assertEqual(client.rows[0]["src"], "any")
        rule.reconcile(params(source_limiting={"ip": "203.0.113.0/24"}), client)
        self.assertEqual(client.rows[0]["src_limiting_type"], "ip")
        self.assertEqual(client.rows[0]["src_firewall_group_id"], "")
        rule.reconcile(params(source_limiting={"enabled": False, "ip": "any"}), client)
        self.assertFalse(client.rows[0]["src_limiting_enabled"])
        self.assertFalse(
            rule.reconcile(
                params(source_limiting={"enabled": False, "ip": "any"}), client
            )["changed"]
        )

    def test_source_group_clear_and_missing_group_validation(self):
        client = FakeClient(
            [
                existing(
                    src_limiting_type="firewall_group", src_firewall_group_id="trusted"
                )
            ]
        )
        rule.reconcile(params(source_limiting={"firewall_group_id": ""}), client)
        self.assertEqual(client.rows[0]["src_limiting_type"], "ip")
        with self.assertRaisesRegex(api.UnifiError, "requires a firewall_group_id"):
            rule.reconcile(params(source_limiting={"type": "firewall_group"}), client)

    def test_source_conflicting_inputs_are_rejected(self):
        for source in (
            {"ip": "192.0.2.1", "firewall_group_id": "group"},
            {"type": "ip", "firewall_group_id": "group"},
        ):
            with self.assertRaises(api.UnifiError):
                rule.validate(params(source_limiting=source))

    def test_multi_wan_order_and_clear(self):
        pairs = [
            {"interface": "wan", "destination_ip": "198.51.100.1"},
            {"interface": "wan2", "destination_ip": "any"},
        ]
        client = FakeClient([existing(destination_ips=pairs)])
        self.assertFalse(
            rule.reconcile(params(destination_ips=pairs[::-1]), client)["changed"]
        )
        self.assertTrue(rule.reconcile(params(destination_ips=[]), client)["changed"])
        self.assertEqual(client.rows[0]["destination_ips"], [])
        self.assertFalse(rule.reconcile(params(destination_ips=[]), client)["changed"])

    def test_port_validation_and_order_preservation(self):
        self.assertEqual(rule.port_expression("00443, 8000-8010"), "443,8000-8010")
        self.assertEqual(rule.port_expression("443,80"), "443,80")
        for expression in (
            "0",
            "65536",
            "2-1",
            "1:10",
            "1,",
            "1.0",
            ",".join(["80"] * 16),
        ):
            with self.subTest(expression=expression), self.assertRaises(api.UnifiError):
                rule.port_expression(expression)

    def test_source_expressions_match_controller_grammar(self):
        for expression in (
            "any",
            "192.0.2.1",
            "!192.0.2.0/24",
            "192.0.2.1-192.0.2.4",
            "!192.0.2.1-192.0.2.4",
        ):
            self.assertEqual(
                rule.address(expression, source=True, allow_any=True), expression
            )
        for expression in ("::1", "!any", "192.0.2.4-192.0.2.1", "192.0.2.1/33"):
            with self.assertRaises(api.UnifiError):
                rule.address(expression, source=True, allow_any=True)

    def test_lost_create_response_is_reconciled_without_second_post(self):
        client = FakeClient()
        client.uncertain_create = True
        self.assertTrue(rule.reconcile(creation(), client)["changed"])
        self.assertEqual(len(client.writes), 1)

    def test_readback_mismatch_is_not_reported_as_success(self):
        client = FakeClient([existing()])
        client.get_rule = Mock(return_value=existing())
        with self.assertRaisesRegex(api.UnifiUncertain, "read-back"):
            rule.reconcile(params(logging=True), client)

    def test_protected_rules_cannot_be_modified_or_deleted(self):
        for config, row in (
            (params(enabled=False), existing(attr_no_edit=True)),
            (params(state="absent"), existing(attr_no_delete=True)),
        ):
            client = FakeClient([row])
            with self.assertRaisesRegex(api.UnifiError, "protected"):
                rule.reconcile(config, client)
            self.assertFalse(client.writes)

    def test_timeout_and_identity_validation(self):
        for config in (
            params(name=""),
            params(site=""),
            params(request_timeout=0),
            params(timeouts={"read": -1}),
        ):
            with self.assertRaises(api.UnifiError):
                rule.validate(config)


class ClientTests(unittest.TestCase):
    def response(self, body, headers=None):
        result = Mock()
        result.headers = headers or {}
        result.read.return_value = json.dumps(body).encode()
        return result

    def client(self, **updates):
        client = api.UnifiClient(params(**updates))
        client.session = Mock()
        return client

    def test_api_key_paths_and_headers(self):
        client = self.client(site="a/b")
        client.session.open.return_value = self.response(
            {"meta": {"rc": "ok"}, "data": []}
        )
        client.login()
        client.list_rules()
        args, kwargs = client.session.open.call_args
        self.assertEqual(
            args,
            ("GET", "https://192.0.2.1/proxy/network/api/s/a%2Fb/rest/portforward"),
        )
        self.assertEqual(kwargs["headers"]["X-API-KEY"], "secret-test-key")
        self.assertEqual(client.session.open.call_count, 1)

    def test_session_login_paths_and_csrf_rotation(self):
        for kind, prefix, login in (
            ("unifi_os", "/proxy/network", "/api/auth/login"),
            ("standalone", "", "/api/login"),
        ):
            client = self.client(
                api_key=None,
                username="local-user",
                password="local-pass",
                controller_type=kind,
            )
            client.session.open.side_effect = [
                self.response({}, {"X-CSRF-Token": "one"}),
                self.response({"data": []}, {"X-Updated-CSRF-Token": "two"}),
            ]
            client.login()
            client.list_rules()
            calls = client.session.open.call_args_list
            self.assertEqual(calls[0].args[1], "https://192.0.2.1" + login)
            self.assertEqual(
                calls[1].args[1],
                "https://192.0.2.1" + prefix + "/api/s/default/rest/portforward",
            )
            self.assertEqual(calls[1].kwargs["headers"]["X-CSRF-Token"], "one")
            self.assertEqual(client.csrf, "two")

    def test_tls_redirect_and_netrc_configuration(self):
        with patch.object(api, "Request") as request:
            api.UnifiClient(params(validate_certs=False))
            kwargs = request.call_args.kwargs
            self.assertFalse(kwargs["validate_certs"])
            self.assertFalse(kwargs["use_netrc"])
            self.assertFalse(kwargs["use_proxy"])
            self.assertEqual(kwargs["follow_redirects"], "none")

    def test_invalid_origin_and_standalone_key(self):
        for url in (
            "https://user:pass@host",
            "https://host/api",
            "https://host?q=key",
            "file:///tmp/test",
            "host",
        ):
            with self.assertRaises(api.UnifiError):
                self.client(api_url=url)
        with self.assertRaises(api.UnifiError):
            self.client(controller_type="standalone")
        with self.assertRaisesRegex(api.UnifiError, "non-empty"):
            self.client(api_key="")

    def test_api_and_http_errors_do_not_expose_response(self):
        client = self.client()
        client.session.open.return_value = self.response(
            {"meta": {"rc": "error", "msg": "secret-test-key"}}
        )
        with self.assertRaises(api.UnifiError) as caught:
            client.list_rules()
        self.assertNotIn("secret-test-key", str(caught.exception))
        client.session.open.side_effect = HTTPError(
            "private-url", 403, "secret-test-key", {}, io.BytesIO(b"secret-test-key")
        )
        with self.assertRaisesRegex(api.UnifiError, "permission denied") as caught:
            client.list_rules()
        self.assertNotIn("secret-test-key", str(caught.exception))

    def test_missing_collection_is_not_empty_site(self):
        client = self.client()
        client.session.open.side_effect = HTTPError("url", 404, "not found", {}, None)
        with self.assertRaises(api.UnifiNotFound):
            client.list_rules()
        self.assertIsNone(client.get_rule("missing"))

    def test_read_retries_but_writes_do_not(self):
        client = self.client()
        client.session.open.side_effect = [
            URLError("secret-test-key"),
            self.response({"data": []}),
        ]
        with patch.object(api.time, "sleep"):
            self.assertEqual(client.list_rules(), [])
        client.session.open.reset_mock()
        client.session.open.side_effect = URLError("secret-test-key")
        with self.assertRaises(api.UnifiUncertain) as caught:
            client.create_rule({})
        self.assertEqual(client.session.open.call_count, 1)
        self.assertNotIn("secret-test-key", str(caught.exception))

    def test_rate_limit_retry_honors_retry_after(self):
        client = self.client()
        client.session.open.side_effect = [
            HTTPError("url", 429, "rate limit", {"Retry-After": "3"}, None),
            self.response({"data": []}),
        ]
        with patch.object(api.time, "sleep") as sleep:
            client.list_rules()
        sleep.assert_called_once_with(3)

    def test_truncated_write_response_is_uncertain_and_not_retried(self):
        client = self.client()
        response = self.response({})
        response.read.side_effect = IncompleteRead(b"partial response")
        client.session.open.return_value = response
        with self.assertRaises(api.UnifiUncertain):
            client.create_rule({})
        self.assertEqual(client.session.open.call_count, 1)
        response.close.assert_called_once()

    def test_collection_requires_unique_rule_ids(self):
        for rows in ([{"name": "missing ID"}], [{"_id": "same"}, {"_id": "same"}]):
            client = self.client()
            client.session.open.return_value = self.response({"data": rows})
            with self.assertRaisesRegex(api.UnifiError, "missing or duplicate IDs"):
                client.list_rules()

    def test_empty_update_response_is_accepted_for_readback(self):
        client = self.client()
        client.session.open.return_value = self.response(
            {"meta": {"rc": "ok"}, "data": []}
        )
        client.update_rule("id", {"log": True})
        self.assertEqual(client.session.open.call_args.args[0], "PUT")

    def test_operation_deadline_bounds_request(self):
        client = self.client(
            timeouts=dict.fromkeys(("create", "read", "update", "delete"), 1)
        )
        client.session.open.return_value = self.response({"data": []})
        client.list_rules()
        self.assertLessEqual(client.session.open.call_args.kwargs["timeout"], 1)
        client.deadline = 0
        with self.assertRaisesRegex(api.UnifiUncertain, "deadline"):
            client.list_rules()

    def test_invalid_responses_fail_closed(self):
        for body in ({}, {"data": None}, {"data": ["unexpected"]}):
            client = self.client()
            client.session.open.return_value = self.response(body)
            with self.assertRaises(api.UnifiError):
                client.list_rules()


@unittest.skipUnless(
    os.environ.get("UNIFI_RUN_LOCAL_INTEGRATION") == "1",
    "Opt-in local HTTP/Ansible packaging test",
)
class AnsibleIntegrationTests(unittest.TestCase):
    def test_real_playbook_lifecycle_against_local_http_controller(self):
        rows = []
        writes = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                if self.headers.get("X-API-KEY") != "local-test-key":
                    self.send_error(403)
                    return
                path = self.path
                prefix = "/proxy/network/api/s/default/rest/portforward"
                if not path.startswith(prefix):
                    self.send_error(404)
                    return
                key = path[len(prefix) :].strip("/")
                if self.command == "POST":
                    body = json.loads(
                        self.rfile.read(int(self.headers["Content-Length"]))
                    )
                    rows.append(dict(body, _id="fixture-id"))
                    writes.append("POST")
                    data = rows
                elif self.command == "PUT":
                    body = json.loads(
                        self.rfile.read(int(self.headers["Content-Length"]))
                    )
                    rows[:] = [dict(body, _id=key)]
                    writes.append("PUT")
                    data = []  # Real controllers can return an empty update response.
                elif self.command == "DELETE":
                    rows.clear()
                    writes.append("DELETE")
                    data = []
                else:
                    data = [row for row in rows if not key or row["_id"] == key]
                payload = json.dumps({"meta": {"rc": "ok"}, "data": data}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_DELETE = handle_request

        with (
            HTTPServer(("127.0.0.1", 0), Handler) as server,
            tempfile.TemporaryDirectory() as directory,
        ):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            temp = Path(directory)
            config = temp / "ansible.cfg"
            config.write_text(
                "[defaults]\nretry_files_enabled = False\nhost_key_checking = False\n"
            )
            variables = temp / "vars.yaml"
            variables.write_text(
                yaml.safe_dump(
                    {
                        "unifi_host": f"http://127.0.0.1:{server.server_port}",
                        "unifi_api_key": "local-test-key",
                    }
                )
            )
            play = [
                {
                    "name": "UniFi port-forward fixture",
                    "hosts": "127.0.0.1",
                    "connection": "local",
                    "gather_facts": False,
                    "vars_files": [str(variables)],
                    "vars": {"ansible_python_interpreter": sys.executable},
                    "module_defaults": {
                        "unifi_port_forward": {
                            "api_url": "{{ unifi_host }}",
                            "api_key": "{{ unifi_api_key }}",
                            "validate_certs": False,
                        }
                    },
                    "tasks": [
                        {
                            "name": "Reconcile fixture rules",
                            "unifi_port_forward": "{{ item }}",
                            "loop": "{{ unifi_port_forwards }}",
                        }
                    ],
                }
            ]
            playbook = temp / "play.yaml"
            playbook.write_text(yaml.safe_dump(play))
            rule_config = {
                "name": "Fixture",
                "wan": {"port": "443"},
                "forward": {"ip": "192.0.2.10"},
            }
            env = dict(
                os.environ,
                ANSIBLE_CONFIG=str(config),
                ANSIBLE_LIBRARY=str(ROOT / "library"),
                ANSIBLE_MODULE_UTILS=str(ROOT / "module_utils"),
                ANSIBLE_LOCAL_TEMP=str(temp / "local"),
                ANSIBLE_REMOTE_TEMP=str(temp / "remote"),
                ANSIBLE_NOCOLOR="1",
            )

            def run(config, check=False, changed=0):
                args = [
                    "ansible-playbook",
                    "-i",
                    "127.0.0.1,",
                    str(playbook),
                    "--diff",
                    "-e",
                    json.dumps({"unifi_port_forwards": [config]}),
                ]
                if check:
                    args.append("--check")
                result = subprocess.run(
                    args,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertRegex(result.stdout, rf"changed={changed}\s")
                self.assertNotIn("local-test-key", result.stdout + result.stderr)

            run(rule_config, check=True, changed=1)
            self.assertFalse(writes)
            run(rule_config, changed=1)
            run(rule_config)
            rule_config["logging"] = True
            run(rule_config, check=True, changed=1)
            self.assertEqual(writes, ["POST"])
            run(rule_config, changed=1)
            run(rule_config)
            absent = {"id": "fixture-id", "state": "absent"}
            run(absent, check=True, changed=1)
            run(absent, changed=1)
            run(absent)
            self.assertEqual(writes, ["POST", "PUT", "DELETE"])


if __name__ == "__main__":
    unittest.main()
