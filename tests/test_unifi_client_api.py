"""Verify the legacy client and v2 group HTTP contracts from the UniFi SDK."""

import json
import unittest
from unittest.mock import Mock

from test_unifi_client import api, params


class ClientApiTests(unittest.TestCase):
    def client(self, **updates):
        client = api.UnifiClient(params(**updates))
        client.session = Mock()
        return client

    @staticmethod
    def response(body):
        response = Mock()
        response.headers = {}
        response.read.return_value = json.dumps(body).encode()
        return response

    def test_v2_group_list_and_create_use_distinct_paths_and_bare_json(self):
        for kind, prefix in (("unifi_os", "/proxy/network"), ("standalone", "")):
            with self.subTest(kind=kind):
                client = self.client(
                    controller_type=kind,
                    api_key=None,
                    username="fixture-user",
                    password="fixture-password",
                    site="site/one",
                )
                group = {
                    "id": "group-1",
                    "name": "Servers",
                    "type": "CLIENTS",
                    "members": [],
                }
                client.session.open.side_effect = [
                    self.response([group]),
                    self.response(group),
                ]
                self.assertEqual(client.list_network_groups()[0]["_id"], "group-1")
                payload = {key: value for key, value in group.items() if key != "id"}
                self.assertEqual(client.create_network_group(payload)["_id"], "group-1")
                calls = client.session.open.call_args_list
                base = "https://192.0.2.1" + prefix + "/v2/api/site/site%2Fone/"
                self.assertEqual(
                    calls[0].args, ("GET", base + "network-members-groups")
                )
                self.assertEqual(
                    calls[1].args, ("POST", base + "network-members-group")
                )
                self.assertEqual(json.loads(calls[1].kwargs["data"]), payload)

    def test_invalid_v2_collection_cannot_be_treated_as_no_groups(self):
        for body in (
            {},
            {"data": []},
            [None],
            [{"id": ""}],
            [{"id": 12}],
            [{"id": "same"}, {"id": "same"}],
        ):
            with self.subTest(body=body):
                client = self.client()
                client.session.open.return_value = self.response(body)
                with self.assertRaises(api.UnifiError):
                    client.list_network_groups()

    def test_invalid_created_identity_is_an_uncertain_write(self):
        for identity in (None, "", 42, ["unexpected"]):
            for resource in ("user", "usergroup", "network-group"):
                with self.subTest(identity=identity, resource=resource):
                    client = self.client()
                    if resource == "network-group":
                        body = {"id": identity}
                    else:
                        body = {"meta": {"rc": "ok"}, "data": [{"_id": identity}]}
                    client.session.open.return_value = self.response(body)
                    with self.assertRaises(api.UnifiUncertain):
                        if resource == "network-group":
                            client.create_network_group({"name": "Servers"})
                        else:
                            client.create_resource(resource, {})
                    self.assertEqual(client.session.open.call_count, 1)

    def test_v2_support_does_not_accept_bare_arrays_for_legacy_resources(self):
        client = self.client()
        client.session.open.return_value = self.response([])
        with self.assertRaises(api.UnifiUncertain):
            client.list_resource("user")

    def test_absent_uses_explicit_forget_command(self):
        client = self.client(site="site/one")
        client.session.open.return_value = self.response(
            {"data": [{"mac": "aa:bb:cc:dd:ee:ff"}]}
        )
        client.forget_client("aa:bb:cc:dd:ee:ff")
        args, kwargs = client.session.open.call_args
        self.assertEqual(
            args,
            ("POST", "https://192.0.2.1/proxy/network/api/s/site%2Fone/cmd/stamgr"),
        )
        self.assertEqual(
            json.loads(kwargs["data"]),
            {"cmd": "forget-sta", "macs": ["aa:bb:cc:dd:ee:ff"]},
        )


if __name__ == "__main__":
    unittest.main()
