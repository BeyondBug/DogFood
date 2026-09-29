"""Every audited API action queues a signed webhook delivery in the same transaction."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from test_lifecycle import call, creator_cookie


class WebhookOutboxTests(unittest.TestCase):
    def test_audited_actions_are_queued_for_configured_webhooks(self):
        admin = creator_cookie()
        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        status, event, _ = call("POST", "/api/events", {
            "name": f"Outbox {uuid.uuid4().hex[:6]}", "submissions_close": future, "tracks": ["Main"],
        }, admin)
        self.assertEqual(status, 201)
        event_id = event["id"]
        status, hook, _ = call("POST", f"/api/events/{event_id}/webhooks",
                               {"url": "https://example.invalid/outbox"}, admin)
        self.assertEqual(status, 201)
        self.assertEqual(call("PATCH", f"/api/events/{event_id}",
                              {"description": "Outbox check"}, admin)[0], 200)
        # A rejected action commits nothing, so it must not notify anyone.
        self.assertEqual(call("PATCH", f"/api/events/{event_id}",
                              {"submissions_close": None}, admin)[0], 422)
        deliveries = call("GET", f"/api/events/{event_id}/webhooks/deliveries", cookie=admin)[1]["deliveries"]
        types = [row["event_type"] for row in deliveries]
        self.assertIn("webhook.created", types)
        self.assertEqual(types.count("event.updated"), 1)
        self.assertTrue(all(row["webhook_id"] == hook["id"] for row in deliveries))


if __name__ == "__main__":
    unittest.main()
