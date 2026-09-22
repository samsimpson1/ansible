#!/usr/bin/python
"""Manage a single UniFi controller port-forwarding rule."""

DOCUMENTATION = r"""
---
module: unifi_port_forward
short_description: Manage UniFi gateway port forwarding
description:
  - Creates, adopts, updates, and deletes individual port-forwarding rules.
  - Uses the controller REST API, which is not part of the documented Network integration API.
  - Feature baseline is ubiquiti-community/unifi Terraform provider 0.55.0.
  - Omitted settings preserve existing values. Defaults described here apply to creation only.
  - Rules are identified by O(id), or by an exact O(name) within O(site).
author:
  - Sam Simpson
options:
  api_url:
    description: Controller origin, including scheme, without an API path.
    type: str
    required: true
  api_key:
    description: UniFi OS API key. Mutually exclusive with username and password.
    type: str
  username:
    description: Local controller username for session authentication.
    type: str
  password:
    description: Local controller password. Required together with username.
    type: str
  controller_type:
    description: Selects the API prefix and session login endpoint.
    type: str
    choices: [unifi_os, standalone]
    default: unifi_os
  validate_certs:
    description: Verify the controller TLS certificate.
    type: bool
    default: true
  request_timeout:
    description: Maximum seconds for an individual HTTP request, bounded by the operation deadline.
    type: int
    default: 30
  timeouts:
    description: Operation deadlines in seconds, including any read retries or verification.
    type: dict
    default: {}
    suboptions:
      create:
        description: Creation deadline.
        type: int
        default: 1200
      read:
        description: Discovery and authentication deadline.
        type: int
        default: 1200
      update:
        description: Update deadline.
        type: int
        default: 1200
      delete:
        description: Deletion deadline.
        type: int
        default: 1200
  site:
    description: Legacy controller site name, not the integration API site UUID.
    type: str
    default: default
  id:
    description:
      - Existing controller rule ID. Takes precedence over name matching and allows renaming.
      - An unknown ID with state=present fails instead of creating a replacement.
    type: str
  name:
    description: Exact rule name. Required to create a rule or to find one without an ID.
    type: str
  state:
    description: Whether the specified rule should exist. Removing a task does not delete a rule.
    type: str
    choices: [present, absent]
    default: present
  enabled:
    description: Enable the rule. Defaults to true on creation. False retains a disabled rule.
    type: bool
  logging:
    description: Enable syslog logging. Defaults to false on creation.
    type: bool
  protocol:
    description: Traffic protocol. Defaults to tcp_udp on creation.
    type: str
    choices: [tcp, udp, tcp_udp]
  wan:
    description: External traffic matching settings.
    type: dict
    suboptions:
      interface:
        description: WAN interface. Defaults to wan on creation.
        type: str
        choices: [wan, wan2, both]
      ip_address:
        description: Destination IPv4 address or any. Defaults to any on creation.
        type: str
      port:
        description: External port expression. Required on creation. Supports ports, ranges, and comma-separated lists.
        type: str
  forward:
    description: Internal forwarding destination.
    type: dict
    suboptions:
      ip:
        description: Destination IPv4 address. Required on creation.
        type: str
      port:
        description: Internal port expression. Defaults to wan.port on creation.
        type: str
  source_limiting:
    description:
      - Source matching configuration. Defaults to disabled with IP any on creation.
      - Set enabled=false to disable filtering; set ip=any to clear an IP restriction.
      - Selecting an IP clears the firewall-group reference; selecting a group clears the IP restriction.
    type: dict
    suboptions:
      enabled:
        description: Enable source filtering. Specifying an IP or group alone does not enable filtering.
        type: bool
      type:
        description: Inferred from ip or firewall_group_id when supplied; otherwise preserves the current type.
        type: str
        choices: [ip, firewall_group]
      ip:
        description: IPv4 address, CIDR, address range, any, or an address/CIDR/range prefixed with an exclamation mark.
        type: str
      firewall_group_id:
        description: Existing firewall-group ID. An empty string clears the reference and selects IP matching.
        type: str
  destination_ips:
    description: Additional WAN address/interface pairs. An empty list clears them. Omission preserves them.
    type: list
    elements: dict
    suboptions:
      destination_ip:
        description: IPv4 address or any.
        type: str
        required: true
      interface:
        description: WAN interface for this address.
        type: str
        choices: [wan, wan2]
        required: true
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
notes:
  - Check mode authenticates and reads state but makes no rule changes.
  - Existing fields outside this module's schema are preserved on update.
  - Session authentication requires a local account; interactive MFA is not supported.
  - Place this file in library/ and the client in module_utils/unifi.py alongside the playbook.
"""

EXAMPLES = r"""
- name: Forward HTTPS on a specific WAN address
  unifi_port_forward:
    api_url: "{{ unifi_host }}"
    api_key: "{{ unifi_api_key }}"
    name: HTTPS
    protocol: tcp
    wan:
      interface: wan
      ip_address: 198.51.100.10
      port: "443"
    forward:
      ip: 192.0.2.10
      port: "8443"

- name: Restrict an existing forward to trusted sources
  unifi_port_forward:
    api_url: "{{ unifi_host }}"
    api_key: "{{ unifi_api_key }}"
    name: HTTPS
    source_limiting:
      enabled: true
      ip: 203.0.113.0/24

- name: Remove a forward
  unifi_port_forward:
    api_url: "{{ unifi_host }}"
    api_key: "{{ unifi_api_key }}"
    name: HTTPS
    state: absent
"""

RETURN = r"""
id:
  description: Rule ID, or null when check mode predicts creation or an absent rule was not found.
  type: str
  returned: always
rule:
  description: Normalized final rule configuration; empty when absent. Predicted configuration in check mode.
  type: dict
  returned: always
diff:
  description: Normalized before and after configuration, excluding credentials and controller metadata.
  type: dict
  returned: when diff mode is requested
"""

import copy
import ipaddress
import re

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.unifi import UnifiClient, UnifiError, UnifiUncertain

DEFAULTS = {
    "enabled": True,
    "log": False,
    "proto": "tcp_udp",
    "pfwd_interface": "wan",
    "destination_ip": "any",
    "destination_ips": [],
    "src": "any",
    "src_limiting_enabled": False,
    "src_limiting_type": "ip",
    "src_firewall_group_id": "",
}
FIELDS = {
    "name": "name",
    "enabled": "enabled",
    "logging": "log",
    "protocol": "proto",
    "wan": {
        "interface": "pfwd_interface",
        "ip_address": "destination_ip",
        "port": "dst_port",
    },
    "forward": {"ip": "fwd", "port": "fwd_port"},
    "source_limiting": {
        "enabled": "src_limiting_enabled",
        "type": "src_limiting_type",
        "ip": "src",
        "firewall_group_id": "src_firewall_group_id",
    },
    "destination_ips": "destination_ips",
}


def port_expression(value):
    """Canonicalize lists without merging ranges (which may change port mapping)."""
    parts = value.split(",")
    if not 1 <= len(parts) <= 15:
        raise UnifiError("Port expressions must contain 1 to 15 ports or ranges")
    result = []
    for part in parts:
        if not re.fullmatch(r"[0-9]+(?:-[0-9]+)?", part.strip()):
            raise UnifiError(
                "Ports must use numbers, hyphenated ranges, and comma-separated lists"
            )
        numbers = [int(number) for number in part.strip().split("-")]
        if (
            any(number < 1 or number > 65535 for number in numbers)
            or numbers[0] > numbers[-1]
        ):
            raise UnifiError("Ports must be between 1 and 65535 with ascending ranges")
        result.append("-".join(map(str, numbers)))
    return ",".join(result)


def address(value, source=False, allow_any=False):
    if value == "any" and allow_any:
        return value
    original = value
    if source and value.startswith("!"):
        value = value[1:]
    try:
        if source and "/" in value:
            ipaddress.IPv4Network(value, strict=False)
        elif source and "-" in value:
            start, end = value.split("-")
            if ipaddress.IPv4Address(start) > ipaddress.IPv4Address(end):
                raise ValueError()
        else:
            ipaddress.IPv4Address(value)
    except ValueError:
        raise UnifiError("Invalid IPv4 address or source expression") from None
    return original


def configured(params):
    """Exclude Ansible's None defaults so omitted nested fields remain unmanaged."""
    result = {}
    for name, field in FIELDS.items():
        value = params.get(name)
        if value is None:
            continue
        if isinstance(field, dict):
            for child, raw_name in field.items():
                if value.get(child) is not None:
                    result[raw_name] = copy.deepcopy(value[child])
        else:
            result[field] = copy.deepcopy(value)
    return result


def validate(params):
    if not params.get("id") and not params.get("name"):
        raise UnifiError("Specify a non-empty id or name")
    if not params.get("site"):
        raise UnifiError("site must not be empty")
    if params.get("name") is not None and not 1 <= len(params["name"]) <= 128:
        raise UnifiError("name must contain 1 to 128 characters")
    if params["request_timeout"] <= 0 or any(
        value <= 0 for value in params["timeouts"].values()
    ):
        raise UnifiError("Request and operation timeouts must be positive")
    values = configured(params)
    for key in ("dst_port", "fwd_port"):
        if key in values:
            port_expression(values[key])
    for key in ("destination_ip", "fwd", "src"):
        if key in values:
            address(values[key], source=key == "src", allow_any=key != "fwd")
    destinations = values.get("destination_ips", [])
    pairs = set()
    for item in destinations:
        address(item["destination_ip"], allow_any=True)
        pair = (item["interface"], item["destination_ip"])
        if pair in pairs:
            raise UnifiError(
                "destination_ips must not contain duplicate address/interface pairs"
            )
        pairs.add(pair)
    source = params.get("source_limiting") or {}
    if source.get("firewall_group_id") and source.get("ip") not in (None, "any"):
        raise UnifiError(
            "Specify either a source IP restriction or a firewall group, not both"
        )
    if source.get("type") == "ip" and source.get("firewall_group_id"):
        raise UnifiError("Source type ip cannot use a firewall group")
    if source.get("type") == "firewall_group" and source.get("ip") not in (None, "any"):
        raise UnifiError("Source type firewall_group cannot use an IP restriction")


def normalized(raw):
    if raw is None:
        return {}
    values = copy.deepcopy(DEFAULTS)
    values.update({key: value for key, value in raw.items() if value is not None})
    for key in ("destination_ip", "src"):
        values[key] = values.get(key) or "any"
    values["src_firewall_group_id"] = values.get("src_firewall_group_id") or ""
    values["src_limiting_type"] = values.get("src_limiting_type") or "ip"
    # Controller responses can omit the internal port when it equals the external port.
    values["fwd_port"] = values.get("fwd_port") or values.get("dst_port")
    for key in ("dst_port", "fwd_port"):
        if values.get(key):
            values[key] = port_expression(str(values[key]))
    # The order of independent WAN destination pairs has no forwarding semantics.
    values["destination_ips"] = sorted(
        [
            {
                "destination_ip": item.get("destination_ip") or "any",
                "interface": item["interface"],
            }
            for item in (values.get("destination_ips") or [])
        ],
        key=lambda item: (item["interface"], item["destination_ip"]),
    )
    result = {}
    for name, field in FIELDS.items():
        if isinstance(field, dict):
            result[name] = {
                child: values.get(raw_name) for child, raw_name in field.items()
            }
        else:
            result[name] = values.get(field)
    return result


def desired_rule(params, current):
    desired = copy.deepcopy(current if current is not None else DEFAULTS)
    desired.update(configured(params))
    if current is None:
        if not all(desired.get(field) for field in ("name", "dst_port", "fwd")):
            raise UnifiError("Creating a rule requires name, wan.port, and forward.ip")
        if not desired.get("fwd_port"):
            desired["fwd_port"] = desired["dst_port"]
    source = params.get("source_limiting") or {}
    source_type = source.get("type")
    if source_type is None:
        if source.get("firewall_group_id"):
            source_type = "firewall_group"
        elif source.get("ip") is not None or source.get("firewall_group_id") == "":
            source_type = "ip"
    if source_type == "firewall_group":
        desired["src_limiting_type"] = source_type
        desired["src"] = "any"
    elif source_type == "ip":
        desired["src_limiting_type"] = source_type
        desired["src_firewall_group_id"] = ""
    if desired.get("src_limiting_type") == "firewall_group" and not desired.get(
        "src_firewall_group_id"
    ):
        raise UnifiError("Source type firewall_group requires a firewall_group_id")
    for key in ("dst_port", "fwd_port"):
        if desired.get(key):
            desired[key] = port_expression(str(desired[key]))
    # Preserve unknown writable settings without echoing identity/read-only metadata.
    return {
        key: value
        for key, value in desired.items()
        if key not in ("_id", "site_id") and not key.startswith("attr_")
    }


def by_name(rows, name):
    matches = [row for row in rows if row.get("name") == name]
    if len(matches) > 1:
        raise UnifiError(
            "Multiple rules have this name in the site; supply an explicit id"
        )
    return matches[0] if matches else None


def reconcile(params, client, check_mode=False, diff=False):
    validate(params)
    client.login()
    # Always validate the collection endpoint/site, including explicit-ID deletion.
    rows = client.list_rules()
    rule_id = params.get("id")
    current = (
        next((row for row in rows if row.get("_id") == rule_id), None)
        if rule_id
        else by_name(rows, params.get("name"))
    )
    if rule_id and current is None and params["state"] == "present":
        raise UnifiError(
            "The specified id does not exist in this site; omit id to create by name"
        )
    rule_id = current.get("_id") if current else None
    before = normalized(current)
    desired = desired_rule(params, current) if params["state"] == "present" else None
    after = normalized(desired)
    changed = before != after
    if (
        changed
        and current
        and (current.get("attr_no_edit") if desired else current.get("attr_no_delete"))
    ):
        raise UnifiError(
            "The controller marks this rule as protected from this operation"
        )
    if changed and not check_mode:
        if desired is None:
            client.start_operation("delete")
            client.delete_rule(rule_id)
            if client.get_rule(rule_id) is not None:
                raise UnifiUncertain(
                    "Deletion was accepted but the rule still exists; re-read before retrying"
                )
        else:
            if current is None:
                client.start_operation("create")
                try:
                    created = client.create_rule(desired)
                except UnifiUncertain:
                    # A POST may have succeeded even when its response was lost.
                    # Resolve by exact name, never repeat that POST automatically.
                    created = by_name(client.list_rules(), desired["name"])
                    if created is None:
                        raise UnifiUncertain(
                            "Creation outcome could not be confirmed; rerun the same named task to reconcile"
                        ) from None
                rule_id = created.get("_id")
                if not rule_id:
                    raise UnifiUncertain(
                        "Created rule has no ID; re-read before retrying"
                    )
            else:
                client.start_operation("update")
                client.update_rule(rule_id, desired)
            actual = client.get_rule(rule_id)
            if actual is None or normalized(actual) != after:
                raise UnifiUncertain(
                    "Controller read-back did not match the requested rule; re-read with --check --diff"
                )
            after = normalized(actual)
    result = {"changed": changed, "id": rule_id, "rule": after}
    if diff:
        result["diff"] = {"before": before, "after": after}
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
                operation: {"type": "int", "default": 1200}
                for operation in ("create", "read", "update", "delete")
            },
        },
        "site": {"type": "str", "default": "default"},
        "id": {"type": "str"},
        "name": {"type": "str"},
        "state": {
            "type": "str",
            "choices": ["present", "absent"],
            "default": "present",
        },
        "enabled": {"type": "bool"},
        "logging": {"type": "bool"},
        "protocol": {"type": "str", "choices": ["tcp", "udp", "tcp_udp"]},
        "wan": {
            "type": "dict",
            "options": {
                "interface": {"type": "str", "choices": ["wan", "wan2", "both"]},
                "ip_address": {"type": "str"},
                "port": {"type": "str"},
            },
        },
        "forward": {
            "type": "dict",
            "options": {"ip": {"type": "str"}, "port": {"type": "str"}},
        },
        "source_limiting": {
            "type": "dict",
            "options": {
                "enabled": {"type": "bool"},
                "type": {"type": "str", "choices": ["ip", "firewall_group"]},
                "ip": {"type": "str"},
                "firewall_group_id": {"type": "str"},
            },
        },
        "destination_ips": {
            "type": "list",
            "elements": "dict",
            "options": {
                "destination_ip": {"type": "str", "required": True},
                "interface": {
                    "type": "str",
                    "required": True,
                    "choices": ["wan", "wan2"],
                },
            },
        },
    }


def main():
    module = AnsibleModule(
        argument_spec=argument_spec(),
        supports_check_mode=True,
        required_one_of=[["api_key", "username"], ["id", "name"]],
        required_together=[["username", "password"]],
        mutually_exclusive=[["api_key", "username"], ["api_key", "password"]],
    )
    try:
        validate(module.params)
        client = UnifiClient(module.params)
        module.exit_json(
            **reconcile(module.params, client, module.check_mode, module._diff)
        )
    except UnifiError as error:
        module.fail_json(msg=str(error))


if __name__ == "__main__":
    main()
