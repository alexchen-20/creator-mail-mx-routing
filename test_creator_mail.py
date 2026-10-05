import unittest

from creator_mail import CreatorMailRequest, InfraiError, configure_mail


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, path, *, query=None, body=None, request_id=None):
        self.calls.append((method, path, query, body, request_id))
        if path == "/v1/dns/domain/get":
            return {"zone_id": "zone-42"}
        if path == "/v1/email/domain/list":
            return [{"domain": "updates.example.org"}]
        return {}


class CreatorMailTests(unittest.TestCase):
    def test_priority_order_and_shared_client(self):
        item = CreatorMailRequest.parse({
            "domain": "creator.example.org",
            "mx_targets": [{"host": "backup.example.org", "priority": 20},
                           {"host": "primary.example.org", "priority": 10}],
            "digital_asset_delivery": True, "subscriber_updates": True,
            "content_processing": False,
        })
        client = FakeClient()
        result = configure_mail(client, item)
        self.assertEqual([call[3]["priority"] for call in client.calls[1:3]], [10, 20])
        self.assertTrue(all(call[3]["zone_id"] == "zone-42" for call in client.calls[1:3]))
        self.assertEqual(client.calls[0][2], {"domain": "creator.example.org"})
        self.assertEqual(client.calls[-1][1], "/v1/email/domain/list")
        self.assertTrue(all(call[4] for call in client.calls[1:3]))
        self.assertEqual(result["sending_domains"], [{"domain": "updates.example.org"}])
        self.assertTrue(result["workflows"]["digital_asset_delivery"])

    def test_duplicate_priorities_are_rejected_before_writes(self):
        with self.assertRaisesRegex(ValueError, "priorities must be distinct"):
            CreatorMailRequest.parse({
                "domain": "creator.example.org",
                "mx_targets": [{"host": "a.example.org", "priority": 10},
                               {"host": "b.example.org", "priority": 10}],
                "digital_asset_delivery": True, "subscriber_updates": False,
                "content_processing": True,
            })

    def test_missing_zone_id_is_rejected_before_writes(self):
        item = CreatorMailRequest.parse({
            "domain": "missing.example.org",
            "mx_targets": [{"host": "mx.example.org", "priority": 10}],
            "digital_asset_delivery": True, "subscriber_updates": False,
            "content_processing": True,
        })
        client = FakeClient()
        client.request = lambda method, path, **kwargs: client.calls.append(path) or {"zone_id": ""}

        with self.assertRaisesRegex(ValueError, "not available in the account"):
            configure_mail(client, item)
        self.assertEqual(client.calls, ["/v1/dns/domain/get"])


if __name__ == "__main__":
    unittest.main()
