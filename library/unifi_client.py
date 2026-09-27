#!/usr/bin/python
"""Manage a persistent UniFi client by site and MAC address."""

DOCUMENTATION = r"""
---
module: unifi_client
short_description: Manage a UniFi network client
version_added: '1.0.0'
description:
  - Creates or adopts an existing MAC, reconciles its settings, and explicitly forgets it with C(state=absent).
  - Feature baseline is ubiquiti-community/unifi Terraform provider 0.55.0.
  - Omitting a task never forgets a client. Omitted optional fields preserve controller values, except C(blocked), which defaults to false.
  - Empty strings clear fixed IP, DNS, AP affinity, and virtual network override; C(groups=[]) clears group membership. C(qos_rate={}) clears bandwidth group assignment.
options:
  api_url:
    description: Controller origin, including scheme, without an API path.
    type: str
    required: true
  api_key:
    description: UniFi OS API key.
    type: str
  username:
    description: Local controller username.
    type: str
  password:
    description: Local controller password.
    type: str
  controller_type:
    description: Controller API style.
    type: str
    choices: [unifi_os, standalone]
    default: unifi_os
  validate_certs:
    description: Verify the TLS certificate.
    type: bool
    default: true
  request_timeout:
    description: Maximum seconds for an individual HTTP request.
    type: int
    default: 30
  timeouts:
    description: Operation deadlines in seconds.
    type: dict
    suboptions:
      create: {description: Creation deadline., type: int, default: 1200}
      read: {description: Discovery deadline., type: int, default: 1200}
      update: {description: Update deadline., type: int, default: 1200}
      delete: {description: Forget deadline., type: int, default: 1200}
  site:
    description: Legacy controller site name.
    type: str
    default: default
  mac:
    description: Site-scoped client MAC address. Colons, hyphens, and bare hexadecimal are accepted.
    type: str
    required: true
  state:
    description: Present or explicitly forget the entire client.
    type: str
    choices: [present, absent]
    default: present
  name:
    description: Client name. Empty string clears it.
    type: str
  display_name:
    description: Client display name. Empty string clears it.
    type: str
  note:
    description: Client note. Empty string clears it.
    type: str
  fixed_ip:
    description: Reserved IPv4 address. Empty string disables the reservation.
    type: str
  network_id:
    description: Virtual network override ID. Empty string disables the override.
    type: str
  local_dns_record:
    description: Local DNS record. Empty string disables it.
    type: str
  fixed_ap_mac:
    description: Preferred AP MAC. Empty string disables affinity.
    type: str
  blocked:
    description: Block the client. Defaults to false even for adopted clients.
    type: bool
    default: false
  groups:
    description: Names of network member groups. Unknown names are created as CLIENTS groups. Empty list clears membership.
    type: list
    elements: str
  qos_rate:
    description: Bandwidth profile. ID selects an existing usergroup directly; name looks up or creates a group; rates without a name derive a profile name. Rate updates to a named profile affect every client using it. Empty dict clears assignment and never deletes the profile.
    type: dict
    suboptions:
      id: {description: "Existing usergroup ID, used directly.", type: str}
      name: {description: Profile name to find or create., type: str}
      max_up: {description: Upload rate in kbps. Use -1 for unlimited., type: int}
      max_down: {description: Download rate in kbps. Use -1 for unlimited., type: int}
attributes:
  check_mode: {support: full}
  diff_mode: {support: full}
notes:
  - Read-only hostname and last_ip are returned but excluded from change comparison.
  - Check mode reads client and referenced groups without writes.
  - Controller fields outside this module's schema are preserved on update.
"""

EXAMPLES = r"""
- name: Assign a DHCP reservation to a known client
  unifi_client:
    api_url: "{{ unifi_host }}"
    api_key: "{{ unifi_api_key }}"
    mac: "{{ client_mac }}"
    name: NAS
    fixed_ip: 192.0.2.25
    blocked: false

- name: Explicitly forget a retired client
  unifi_client:
    api_url: "{{ unifi_host }}"
    api_key: "{{ unifi_api_key }}"
    mac: "{{ retired_client_mac }}"
    state: absent
"""

RETURN = r"""
id:
  description: Controller client ID, or null for an uncreated/forgotten client.
  type: str
  returned: always
client:
  description: Normalized client configuration plus observed hostname and last_ip.
  type: dict
  returned: always
diff:
  description: Before and after configuration, excluding changing observations.
  type: dict
  returned: when diff mode is requested
"""

import copy
import ipaddress
import re

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.unifi import UnifiClient, UnifiError, UnifiUncertain

SCALARS = ("name", "display_name", "note")
FEATURES = {
    "fixed_ip": "use_fixedip",
    "fixed_ap_mac": "fixed_ap_enabled",
    "local_dns_record": "local_dns_record_enabled",
    "network_id": "virtual_network_override_enabled",
}
RAW_FEATURES = {"network_id": "virtual_network_override_id"}
READ_ONLY = {"_id", "site_id", "hostname", "last_ip", "last_seen", "mac", "network_id"}


def canonical_mac(value):
    if not isinstance(value, str):
        raise UnifiError("mac must contain exactly 12 hexadecimal digits")
    digits = re.sub(r"[:-]", "", value).lower()
    if not re.fullmatch(r"[0-9a-f]{12}", digits):
        raise UnifiError("mac must contain exactly 12 hexadecimal digits")
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def validate(params):
    if not params.get("site"):
        raise UnifiError("site must not be empty")
    mac = canonical_mac(params["mac"])
    if params["request_timeout"] <= 0 or any(
        v <= 0 for v in params["timeouts"].values()
    ):
        raise UnifiError("Request and operation timeouts must be positive")
    if params.get("fixed_ip"):
        try:
            ipaddress.IPv4Address(params["fixed_ip"])
        except ValueError:
            raise UnifiError("fixed_ip must be a valid IPv4 address") from None
    if params.get("fixed_ap_mac"):
        canonical_mac(params["fixed_ap_mac"])
    groups = params.get("groups")
    if groups is not None and (
        any(not g or not g.strip() for g in groups) or len(groups) != len(set(groups))
    ):
        raise UnifiError("groups must contain unique non-empty names")
    qos = (
        {k: v for k, v in (params.get("qos_rate") or {}).items() if v is not None}
        if params.get("qos_rate") is not None
        else None
    )
    if qos and not (
        qos.get("id")
        or qos.get("name")
        or qos.get("max_up") is not None
        or qos.get("max_down") is not None
    ):
        raise UnifiError("qos_rate requires id, name, or a rate; use {} to clear")
    if (
        qos
        and qos.get("id")
        and any(qos.get(k) is not None for k in ("name", "max_up", "max_down"))
    ):
        raise UnifiError("qos_rate.id cannot be combined with name or rates")
    for key in ("max_up", "max_down"):
        if (
            qos
            and qos.get(key) is not None
            and qos[key] != -1
            and not 2 <= qos[key] <= 100000
        ):
            raise UnifiError("qos_rate rates must be -1 (unlimited) or 2..100000 kbps")
    return mac


def by_mac(rows, mac):
    if any(not isinstance(r.get("mac"), str) for r in rows):
        raise UnifiUncertain("UniFi returned a client without a MAC address")
    matches = [r for r in rows if canonical_mac(r["mac"]) == mac]
    if len(matches) > 1:
        raise UnifiError("Multiple clients have this MAC in the site")
    return matches[0] if matches else None


def by_name(rows, name, resource):
    matches = [r for r in rows if r.get("name") == name]
    if len(matches) > 1:
        raise UnifiError("Multiple " + resource + " objects have the same name")
    return matches[0] if matches else None


def group_names(ids, rows):
    if ids is None:
        ids = []
    if not isinstance(ids, list) or any(not isinstance(i, str) or not i for i in ids):
        raise UnifiUncertain("UniFi returned invalid network members group IDs")
    if any(not isinstance(r.get("name"), str) or not r["name"] for r in rows):
        raise UnifiUncertain("UniFi returned an invalid network members group name")
    index = {r["_id"]: r["name"] for r in rows}
    return sorted(index.get(i, "id:" + i) for i in ids)


def blocked_value(value):
    if value in (None, False, 0, "false", "False", "0"):
        return False
    if value in (True, 1, "true", "True", "1"):
        return True
    raise UnifiUncertain("UniFi returned an invalid blocked value")


def qos_view(group_id, rows):
    if not group_id:
        return None
    row = next((r for r in rows if r["_id"] == group_id), None)
    if row is None:
        return {"id": group_id, "name": None, "max_up": None, "max_down": None}
    return {
        "id": group_id,
        "name": row.get("name"),
        "max_up": qos_number(row.get("qos_rate_max_up")),
        "max_down": qos_number(row.get("qos_rate_max_down")),
    }


def qos_number(value):
    if value in (None, ""):
        return None if value is None else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        raise UnifiUncertain(
            "UniFi returned an invalid bandwidth profile rate"
        ) from None


def normalized(raw, network_groups=(), qos_groups=()):
    if raw is None:
        return {}
    result = {"mac": canonical_mac(raw["mac"])}
    for key in SCALARS:
        result[key] = raw.get(key) or ""
    for key, enabled in FEATURES.items():
        value = (raw.get(RAW_FEATURES.get(key, key)) or "") if raw.get(enabled) else ""
        if key == "fixed_ap_mac" and value:
            value = canonical_mac(value)
        result[key] = value
    result["blocked"] = blocked_value(raw.get("blocked"))
    result["groups"] = group_names(raw.get("network_members_group_ids"), network_groups)
    result["qos_rate"] = qos_view(raw.get("usergroup_id"), qos_groups)
    result["hostname"] = raw.get("hostname") or ""
    result["last_ip"] = raw.get("last_ip") or ""
    return result


def comparable(view):
    return {k: v for k, v in view.items() if k not in ("hostname", "last_ip")}


def client_comparable(view):
    result = comparable(view)
    if result.get("qos_rate"):
        result["qos_rate"] = result["qos_rate"]["id"]
    return result


def clean_payload(raw):
    return {
        k: copy.deepcopy(v)
        for k, v in raw.items()
        if k not in READ_ONLY and not k.startswith("attr_")
    }


def reconcile(params, client, check_mode=False, diff=False):
    mac = validate(params)
    client.login()
    rows = client.list_resource("user")
    current = by_mac(rows, mac)
    if current is not None:
        full = client.get_resource("user", current["_id"])
        if full is None or canonical_mac(full.get("mac", "")) != mac:
            raise UnifiUncertain(
                "Client changed during discovery; re-read before retrying"
            )
        current = full
    network_groups = (
        client.list_network_groups()
        if (current and current.get("network_members_group_ids"))
        or params.get("groups")
        else []
    )
    qos_groups = (
        client.list_resource("usergroup")
        if (current and current.get("usergroup_id")) or params.get("qos_rate")
        else []
    )
    before = normalized(current, network_groups, qos_groups)
    if params["state"] == "absent":
        changed = current is not None
        if changed and current.get("attr_no_delete"):
            raise UnifiError("Controller protects this client from deletion")
        if changed and not check_mode:
            client.start_operation("delete")
            try:
                client.forget_client(mac)
            except UnifiUncertain:
                if by_mac(client.list_resource("user"), mac):
                    raise
            if by_mac(client.list_resource("user"), mac):
                raise UnifiUncertain(
                    "Forget was accepted but client remains; re-read before retrying"
                )
        result = {
            "changed": changed,
            "id": current["_id"] if check_mode and current else None,
            "client": {},
        }
        if diff:
            result["diff"] = {"before": comparable(before), "after": {}}
        return result

    desired = copy.deepcopy(current) if current else {"mac": mac}
    desired["mac"] = mac
    for key in SCALARS:
        if params.get(key) is not None:
            desired[key] = params[key]
    for key, enabled in FEATURES.items():
        value = params.get(key)
        if value is not None:
            if key == "fixed_ap_mac" and value:
                value = canonical_mac(value)
            desired[RAW_FEATURES.get(key, key)] = value
            desired[enabled] = bool(value)
    desired["blocked"] = params["blocked"]
    group_create = []
    if params.get("groups") is not None:
        ids = []
        for name in params["groups"]:
            row = by_name(network_groups, name, "network member group")
            if row is None:
                group_create.append(name)
                ids.append("pending:" + name)
                network_groups.append({"_id": "pending:" + name, "name": name})
            else:
                if row.get("type") != "CLIENTS":
                    raise UnifiError(
                        "Network members group " + name + " is not a CLIENTS group"
                    )
                ids.append(row["_id"])
        desired["network_members_group_ids"] = ids
    qos_create = None
    qos_update = None
    requested_rates = {}
    qos = (
        {k: v for k, v in (params.get("qos_rate") or {}).items() if v is not None}
        if params.get("qos_rate") is not None
        else None
    )
    if qos is not None:
        if not qos:
            desired["usergroup_id"] = ""
        elif qos.get("id"):
            if not any(g["_id"] == qos["id"] for g in qos_groups):
                raise UnifiError("qos_rate.id was not found in this site")
            desired["usergroup_id"] = qos["id"]
        else:
            name = qos.get("name") or "qos-up%s-down%s" % (
                qos["max_up"] if "max_up" in qos else -1,
                qos["max_down"] if "max_down" in qos else -1,
            )
            row = by_name(qos_groups, name, "usergroup")
            rates = {
                ("qos_rate_" + key): qos[key]
                for key in ("max_up", "max_down")
                if qos.get(key) is not None
            }
            requested_rates = rates
            if row is None:
                qos_create = {"name": name, **rates}
                row = {"_id": "pending:" + name, **qos_create}
                qos_groups.append(row)
            elif any(qos_number(row.get(k)) != v for k, v in rates.items()):
                qos_update = (row["_id"], {**clean_payload(row), **rates})
                row.update(rates)
            desired["usergroup_id"] = row["_id"]
    after = normalized(desired, network_groups, qos_groups)
    config_changed = comparable(before) != comparable(after)
    client_changed = client_comparable(before) != client_comparable(after)
    changed = config_changed or bool(group_create or qos_create or qos_update)
    if changed and current and current.get("attr_no_edit") and client_changed:
        raise UnifiError("Controller protects this client from editing")
    if changed and not check_mode:
        client.start_operation("create" if current is None else "update")
        for name in group_create:
            try:
                row = client.create_network_group(
                    {"name": name, "members": [], "type": "CLIENTS"}
                )
            except UnifiUncertain:
                row = by_name(
                    client.list_network_groups(), name, "network member group"
                )
                if row is None:
                    raise
            if row.get("name") != name or row.get("type") != "CLIENTS":
                raise UnifiUncertain(
                    "Created network members group did not match request"
                )
            desired["network_members_group_ids"] = [
                row["_id"] if i == "pending:" + name else i
                for i in desired["network_members_group_ids"]
            ]
        if qos_create:
            try:
                row = client.create_resource("usergroup", qos_create)
            except UnifiUncertain:
                row = by_name(
                    client.list_resource("usergroup"), qos_create["name"], "usergroup"
                )
                if row is None:
                    raise
            if row.get("name") != qos_create["name"]:
                raise UnifiUncertain("Created bandwidth profile did not match request")
            desired["usergroup_id"] = row["_id"]
        if qos_update:
            try:
                client.update_resource("usergroup", *qos_update)
            except UnifiUncertain:
                pass  # Profile read-back below resolves a lost response.
        if current is None:
            try:
                created = client.create_resource("user", {"mac": mac})
            except UnifiUncertain:
                created = by_mac(client.list_resource("user"), mac)
                if created is None:
                    raise
            current = client.get_resource("user", created["_id"])
            if current is None or canonical_mac(current.get("mac", "")) != mac:
                raise UnifiUncertain("Created client could not be confirmed by MAC")
            # Merge newly created controller metadata before updating.
            merged = copy.deepcopy(current)
            merged.update(clean_payload(desired))
            desired = merged
        if client_changed or group_create or qos_create:
            payload = clean_payload(desired)
            payload["mac"] = mac
            try:
                client.update_resource("user", current["_id"], payload)
            except UnifiUncertain:
                pass  # Read-back below determines whether the write reached the controller.
        actual = client.get_resource("user", current["_id"])
        if actual is None or canonical_mac(actual.get("mac", "")) != mac:
            raise UnifiUncertain("Client write outcome could not be confirmed")
        network_groups = (
            client.list_network_groups()
            if actual.get("network_members_group_ids")
            else []
        )
        qos_groups = (
            client.list_resource("usergroup") if actual.get("usergroup_id") else []
        )
        if qos_update or qos_create:
            expected_group = qos_update[1] if qos_update else qos_create
            updated_group = next(
                (g for g in qos_groups if g["_id"] == desired["usergroup_id"]), None
            )
            if (
                updated_group is None
                or updated_group.get("name") != expected_group.get("name")
                or any(
                    qos_number(updated_group.get(k)) != v
                    for k, v in requested_rates.items()
                )
            ):
                raise UnifiUncertain(
                    "Bandwidth profile read-back did not match request"
                )
        if group_create:
            group_map = {g["_id"]: g for g in network_groups}
            if any(
                group_map.get(group_id, {}).get("type") != "CLIENTS"
                for group_id in desired["network_members_group_ids"]
            ):
                raise UnifiUncertain(
                    "Network members group read-back did not match request"
                )
        expected = normalized(desired, network_groups, qos_groups)
        observed = normalized(actual, network_groups, qos_groups)
        if comparable(expected) != comparable(observed):
            raise UnifiUncertain(
                "Client read-back did not match request; re-read with --check --diff"
            )
        after = observed
    result = {
        "changed": changed,
        "id": current["_id"] if current else None,
        "client": after,
    }
    if diff:
        result["diff"] = {"before": comparable(before), "after": comparable(after)}
    return result


def argument_spec():
    return {
        "api_url": {"type": "str", "required": True},
        "api_key": {"type": "str", "no_log": True},
        "username": {"type": "str", "no_log": True},
        "password": {"type": "str", "no_log": True},
        "controller_type": {
            "type": "str",
            "choices": ["unifi_os", "standalone"],
            "default": "unifi_os",
        },
        "validate_certs": {"type": "bool", "default": True},
        "request_timeout": {"type": "int", "default": 30},
        "timeouts": {
            "type": "dict",
            "default": {},
            "options": {
                op: {"type": "int", "default": 1200}
                for op in ("create", "read", "update", "delete")
            },
        },
        "site": {"type": "str", "default": "default"},
        "mac": {"type": "str", "required": True},
        "state": {
            "type": "str",
            "choices": ["present", "absent"],
            "default": "present",
        },
        "name": {"type": "str"},
        "display_name": {"type": "str"},
        "note": {"type": "str"},
        "fixed_ip": {"type": "str"},
        "network_id": {"type": "str"},
        "local_dns_record": {"type": "str"},
        "fixed_ap_mac": {"type": "str"},
        "blocked": {"type": "bool", "default": False},
        "groups": {"type": "list", "elements": "str"},
        "qos_rate": {
            "type": "dict",
            "options": {
                k: {"type": t}
                for k, t in (
                    ("id", "str"),
                    ("name", "str"),
                    ("max_up", "int"),
                    ("max_down", "int"),
                )
            },
        },
    }


def main():
    module = AnsibleModule(
        argument_spec=argument_spec(),
        supports_check_mode=True,
        required_one_of=[["api_key", "username"]],
        required_together=[["username", "password"]],
        mutually_exclusive=[["api_key", "username"], ["api_key", "password"]],
    )
    try:
        client = UnifiClient(module.params)
        module.exit_json(
            **reconcile(module.params, client, module.check_mode, module._diff)
        )
    except UnifiError as error:
        module.fail_json(msg=str(error))


if __name__ == "__main__":
    main()
