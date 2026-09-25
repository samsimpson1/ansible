"""Offline lifecycle and controller fixture tests for unifi_client."""

import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


api = load("ansible.module_utils.unifi", ROOT / "module_utils/unifi.py")
mod = load("unifi_client", ROOT / "library/unifi_client.py")


def params(**kwargs):
    value = {
        "api_url": "https://192.0.2.1",
        "api_key": "test-key",
        "controller_type": "unifi_os",
        "validate_certs": True,
        "request_timeout": 30,
        "timeouts": dict.fromkeys(("create", "read", "update", "delete"), 1200),
        "site": "default",
        "mac": "AA-BB-CC-DD-EE-FF",
        "state": "present",
        "blocked": False,
    }
    value.update(kwargs)
    return value


class FakeClient:
    def __init__(self, users=(), groups=(), qos=()):
        self.data = {
            "user": copy.deepcopy(list(users)),
            "network_members_group": copy.deepcopy(list(groups)),
            "usergroup": copy.deepcopy(list(qos)),
        }
        self.writes = []
        self.lost = None

    def login(self):
        pass

    def start_operation(self, operation):
        pass

    def list_resource(self, kind):
        return copy.deepcopy(self.data[kind])

    def list_network_groups(self):
        return self.list_resource("network_members_group")

    def create_network_group(self, payload):
        return self.create_resource("network_members_group", payload)

    def get_resource(self, kind, ident):
        return copy.deepcopy(
            next((x for x in self.data[kind] if x["_id"] == ident), None)
        )

    def create_resource(self, kind, payload):
        row = dict(copy.deepcopy(payload), _id=f"{kind}-{len(self.data[kind]) + 1}")
        self.data[kind].append(row)
        self.writes.append(("POST", kind, copy.deepcopy(payload)))
        if self.lost == ("POST", kind):
            raise api.UnifiUncertain("response lost")
        return copy.deepcopy(row)

    def update_resource(self, kind, ident, payload):
        self.data[kind] = [
            dict(copy.deepcopy(payload), _id=ident) if x["_id"] == ident else x
            for x in self.data[kind]
        ]
        self.writes.append(("PUT", kind, copy.deepcopy(payload)))
        if self.lost == ("PUT", kind):
            raise api.UnifiUncertain("response lost")

    def forget_client(self, mac):
        self.data["user"] = [x for x in self.data["user"] if x["mac"] != mac]
        self.writes.append(("POST", "forget-sta", mac))
        if self.lost == ("POST", "forget-sta"):
            raise api.UnifiUncertain("response lost")


def user(**updates):
    row = {
        "_id": "client-1",
        "mac": "aa:bb:cc:dd:ee:ff",
        "name": "old",
        "blocked": False,
        "hostname": "observed",
        "last_ip": "192.0.2.2",
        "future_setting": {"x": 1},
    }
    row.update(updates)
    return row


class ClientTests(unittest.TestCase):
    def test_mac_identity_and_duplicate(self):
        self.assertEqual(
            mod.canonical_mac("AABB.CCDD.EEFF".replace(".", "")), "aa:bb:cc:dd:ee:ff"
        )
        with self.assertRaises(api.UnifiError):
            mod.validate(params(mac="not-a-mac"))
        with self.assertRaisesRegex(api.UnifiError, "Multiple clients"):
            mod.reconcile(params(), FakeClient([user(), user(_id="client-2")]))

    def test_adoption_defaults_blocked_false_and_preserves_unknown(self):
        client = FakeClient([user(blocked=True)])
        result = mod.reconcile(params(), client, diff=True)
        self.assertTrue(result["changed"])
        self.assertFalse(result["client"]["blocked"])
        self.assertEqual(client.data["user"][0]["future_setting"], {"x": 1})
        self.assertFalse(mod.reconcile(params(), client)["changed"])
        self.assertNotIn("hostname", result["diff"]["after"])
        self.assertNotIn("last_ip", result["diff"]["after"])

    def test_create_idempotent_and_forget(self):
        client = FakeClient()
        result = mod.reconcile(params(name="new", fixed_ip="192.0.2.5"), client)
        self.assertTrue(result["changed"])
        self.assertTrue(client.data["user"][0]["use_fixedip"])
        self.assertFalse(
            mod.reconcile(params(name="new", fixed_ip="192.0.2.5"), client)["changed"]
        )
        self.assertTrue(mod.reconcile(params(state="absent"), client)["changed"])
        self.assertFalse(mod.reconcile(params(state="absent"), client)["changed"])
        self.assertEqual(
            [w[:2] for w in client.writes],
            [("POST", "user"), ("PUT", "user"), ("POST", "forget-sta")],
        )

    def test_feature_clears_and_stale_disabled_values(self):
        client = FakeClient(
            [
                user(
                    fixed_ip="192.0.2.5",
                    use_fixedip=True,
                    fixed_ap_mac="aa:bb:cc:dd:ee:01",
                    fixed_ap_enabled=True,
                    local_dns_record="old.example",
                    local_dns_record_enabled=True,
                    virtual_network_override_id="net-1",
                    virtual_network_override_enabled=True,
                )
            ]
        )
        config = params(
            fixed_ip="", fixed_ap_mac="", local_dns_record="", network_id=""
        )
        self.assertTrue(mod.reconcile(config, client)["changed"])
        for key in (
            "use_fixedip",
            "fixed_ap_enabled",
            "local_dns_record_enabled",
            "virtual_network_override_enabled",
        ):
            self.assertFalse(client.data["user"][0][key])
        self.assertFalse(mod.reconcile(config, client)["changed"])
        client.data["user"][0]["fixed_ip"] = "stale"
        self.assertFalse(mod.reconcile(config, client)["changed"])

    def test_check_mode_plans_related_resources_without_writes(self):
        client = FakeClient([user()])
        config = params(
            groups=["Cameras"],
            qos_rate={"name": "slow", "max_up": 100, "max_down": 200},
        )
        result = mod.reconcile(config, client, check_mode=True, diff=True)
        self.assertTrue(result["changed"])
        self.assertEqual(result["client"]["groups"], ["Cameras"])
        self.assertEqual(client.writes, [])
        mod.reconcile(config, client)
        self.assertEqual(
            [w[:2] for w in client.writes],
            [("POST", "network_members_group"), ("POST", "usergroup"), ("PUT", "user")],
        )
        self.assertFalse(mod.reconcile(config, client)["changed"])
        self.assertTrue(
            mod.reconcile(params(groups=[], qos_rate={}), client)["changed"]
        )
        self.assertEqual(client.data["user"][0]["usergroup_id"], "")
        self.assertEqual(client.data["user"][0]["network_members_group_ids"], [])

    def test_qos_profile_rate_update_is_change_without_client_put(self):
        qos = {
            "_id": "qos-1",
            "name": "slow",
            "qos_rate_max_up": "100",
            "qos_rate_max_down": "200",
        }
        client = FakeClient([user(usergroup_id="qos-1")], qos=[qos])
        config = params(qos_rate={"name": "slow", "max_up": 300})
        self.assertTrue(mod.reconcile(config, client, check_mode=True)["changed"])
        self.assertEqual(client.writes, [])
        self.assertTrue(mod.reconcile(config, client)["changed"])
        self.assertEqual([w[:2] for w in client.writes], [("PUT", "usergroup")])
        self.assertFalse(mod.reconcile(config, client)["changed"])

    def test_uncertain_create_update_forget_readback(self):
        client = FakeClient()
        client.lost = ("POST", "user")
        self.assertTrue(mod.reconcile(params(), client)["changed"])
        client.lost = ("PUT", "user")
        self.assertTrue(mod.reconcile(params(name="new"), client)["changed"])
        client.lost = ("POST", "forget-sta")
        self.assertTrue(mod.reconcile(params(state="absent"), client)["changed"])

    def test_protected_and_invalid_inputs(self):
        for config in (
            params(fixed_ip="::1"),
            params(qos_rate={"id": "x", "max_up": 1}),
            params(groups=["a", "a"]),
            params(qos_rate={"max_down": -2}),
        ):
            with self.assertRaises(api.UnifiError):
                mod.validate(config)
        with self.assertRaises(api.UnifiError):
            mod.reconcile(params(name="new"), FakeClient([user(attr_no_edit=True)]))
        with self.assertRaises(api.UnifiError):
            mod.reconcile(
                params(state="absent"),
                FakeClient([user(attr_no_delete=True)]),
                check_mode=True,
            )

    def test_ansible_expanded_empty_qos_clears_and_derived_name(self):
        expanded = {"id": None, "name": None, "max_up": None, "max_down": None}
        client = FakeClient(
            [user(usergroup_id="qos-1")], qos=[{"_id": "qos-1", "name": "old"}]
        )
        self.assertTrue(mod.reconcile(params(qos_rate=expanded), client)["changed"])
        self.assertEqual(client.data["user"][0]["usergroup_id"], "")
        client = FakeClient([user()])
        mod.reconcile(
            params(
                qos_rate={"id": None, "name": None, "max_up": 200, "max_down": None}
            ),
            client,
        )
        self.assertEqual(client.data["usergroup"][0]["name"], "qos-up200-down-1")

    def test_qos_created_rate_readback_must_match(self):
        class BadClient(FakeClient):
            def create_resource(self, kind, payload):
                row = super().create_resource(kind, payload)
                if kind == "usergroup":
                    self.data[kind][0]["qos_rate_max_up"] = 99
                return row

        with self.assertRaisesRegex(api.UnifiUncertain, "Bandwidth profile read-back"):
            mod.reconcile(
                params(qos_rate={"name": "slow", "max_up": 100}), BadClient([user()])
            )

    def test_controller_mac_and_bool_normalization(self):
        client = FakeClient(
            [
                user(
                    fixed_ap_mac="AA:BB:CC:DD:EE:01",
                    fixed_ap_enabled=True,
                    blocked="false",
                )
            ]
        )
        result = mod.reconcile(params(fixed_ap_mac="aa:bb:cc:dd:ee:01"), client)
        self.assertFalse(result["changed"])
        self.assertFalse(result["client"]["blocked"])
        for malformed in (
            user(blocked="maybe"),
            user(network_members_group_ids="group-1"),
        ):
            with self.assertRaises(api.UnifiError):
                mod.reconcile(params(), FakeClient([malformed]))
        with self.assertRaises(api.UnifiError):
            mod.reconcile(
                params(groups=["Cameras"]),
                FakeClient(
                    [user()],
                    groups=[{"_id": "group-1", "name": "Cameras", "type": "NETWORKS"}],
                ),
            )


if __name__ == "__main__":
    unittest.main()


# This fixture exercises Ansible packaging and HTTP paths without a real controller.
# It is opt-in because some sandboxes prohibit loopback sockets.
import json
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import yaml


@unittest.skipUnless(
    os.environ.get("UNIFI_RUN_LOCAL_INTEGRATION") == "1",
    "Opt-in local HTTP/Ansible fixture",
)
class AnsibleHTTPTests(unittest.TestCase):
    def test_lifecycle_with_v2_groups_and_qos(self):
        rows = {"user": [], "usergroup": [], "network_members_group": []}
        writes = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                if self.headers.get("X-API-KEY") != "local-test-key":
                    self.send_error(403)
                    return
                path = self.path
                root = "/proxy/network/api/s/default/"
                group_root = "/proxy/network/v2/api/site/default/"
                body = (
                    json.loads(
                        self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    )
                    if self.command in ("POST", "PUT")
                    else None
                )
                if path.startswith(root + "cmd/stamgr"):
                    if self.command != "POST" or body.get("cmd") != "forget-sta":
                        self.send_error(400)
                        return
                    rows["user"][:] = [
                        x for x in rows["user"] if x["mac"] not in body["macs"]
                    ]
                    writes.append(("forget", body["macs"]))
                    result = {"meta": {"rc": "ok"}, "data": [{"mac": body["macs"][0]}]}
                elif path.startswith(root + "rest/"):
                    tail = path[len(root + "rest/") :].split("/")
                    kind, ident = tail[0], tail[1] if len(tail) > 1 else None
                    if kind not in ("user", "usergroup"):
                        self.send_error(404)
                        return
                    if self.command == "GET":
                        data = [
                            x for x in rows[kind] if ident is None or x["_id"] == ident
                        ]
                    elif self.command == "POST":
                        item = dict(body, _id=f"{kind}-{len(rows[kind]) + 1}")
                        rows[kind].append(item)
                        writes.append(("POST", kind))
                        data = [item]
                    elif self.command == "PUT":
                        rows[kind][:] = [
                            dict(body, _id=ident) if x["_id"] == ident else x
                            for x in rows[kind]
                        ]
                        writes.append(("PUT", kind))
                        data = []
                    else:
                        self.send_error(405)
                        return
                    result = {"meta": {"rc": "ok"}, "data": data}
                elif path.startswith(group_root):
                    if (
                        path.endswith("network-members-groups")
                        and self.command == "GET"
                    ):
                        result = rows["network_members_group"]
                    elif (
                        path.endswith("network-members-group")
                        and self.command == "POST"
                    ):
                        item = dict(
                            body, id=f'group-{len(rows["network_members_group"]) + 1}'
                        )
                        rows["network_members_group"].append(item)
                        writes.append(("POST", "network_members_group"))
                        result = item
                    else:
                        self.send_error(404)
                        return
                else:
                    self.send_error(404)
                    return
                data = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = handle_request

        with HTTPServer(
            ("127.0.0.1", 0), Handler
        ) as server, tempfile.TemporaryDirectory() as directory:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            temp = Path(directory)
            (temp / "ansible.cfg").write_text(
                "[defaults]\nretry_files_enabled = False\n"
            )
            play = [
                {
                    "name": "Client fixture",
                    "hosts": "127.0.0.1",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": {"ansible_python_interpreter": sys.executable},
                    "module_defaults": {
                        "unifi_client": {
                            "api_url": f"http://127.0.0.1:{server.server_port}",
                            "api_key": "local-test-key",
                            "site": "default",
                        }
                    },
                    "tasks": [
                        {
                            "name": "Reconcile fixture client",
                            "unifi_client": "{{ item }}",
                            "loop": "{{ unifi_clients }}",
                        }
                    ],
                }
            ]
            path = temp / "play.yaml"
            path.write_text(yaml.safe_dump(play))
            env = dict(
                os.environ,
                ANSIBLE_CONFIG=str(temp / "ansible.cfg"),
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
                    str(path),
                    "--diff",
                    "-e",
                    json.dumps({"unifi_clients": [config]}),
                ]
                if check:
                    args.append("--check")
                result = subprocess.run(
                    args, env=env, text=True, capture_output=True, timeout=60
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertRegex(result.stdout, rf"changed={changed}\s")
                self.assertNotIn("local-test-key", result.stdout + result.stderr)

            config = {
                "mac": "AA-BB-CC-DD-EE-FF",
                "name": "fixture",
                "groups": ["Cameras"],
                "qos_rate": {"name": "slow", "max_up": 100},
            }
            run(config, check=True, changed=1)
            self.assertEqual(writes, [])
            run(config, changed=1)
            run(config, changed=0)
            updated = {"mac": config["mac"], "fixed_ip": "192.0.2.5"}
            run(updated, check=True, changed=1)
            run(updated, changed=1)
            run(updated, changed=0)
            absent = {"mac": config["mac"], "state": "absent"}
            run(absent, check=True, changed=1)
            run(absent, changed=1)
            run(absent, changed=0)
            self.assertEqual(
                writes,
                [
                    ("POST", "network_members_group"),
                    ("POST", "usergroup"),
                    ("POST", "user"),
                    ("PUT", "user"),
                    ("PUT", "user"),
                    ("forget", ["aa:bb:cc:dd:ee:ff"]),
                ],
            )
