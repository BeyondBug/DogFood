"""Integration coverage for the isolated T4 and Pairwise Mode features."""

import base64
import json
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_lifecycle import call, creator_cookie


class StretchTests(unittest.TestCase):
    def test_pairwise_bulk_embed_webhook_and_signed_judge_record(self):
        admin = creator_cookie()
        suffix = uuid.uuid4().hex[:8]
        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        status, event, _ = call("POST", "/api/events", {
            "name": f"Stretch {suffix}", "submissions_close": future, "tracks": ["Main"],
        }, admin)
        self.assertEqual(status, 201, event)
        event_id = event["id"]
        track_id = call("GET", f"/api/events/{event_id}")[1]["tracks"][0]["id"]

        csv_text = f"name,email,password\nBulk Person,bulk-{suffix}@example.org,TemporaryPass2026!\n"
        status, imported, _ = call("POST", f"/api/admin/events/{event_id}/bulk/participants",
                                   {"csv_text": csv_text}, admin)
        self.assertEqual(status, 200, imported)
        self.assertEqual(imported["created"], 1)
        self.assertEqual(len(imported["new_account_credentials"]), 1)
        status, archive, _ = call("GET", f"/api/events/{event_id}/export.json", cookie=admin)
        self.assertEqual(status, 200, archive)
        self.assertEqual(archive["format"], "beyondbug-event-archive-v1")
        self.assertNotIn("password_hash", json.dumps(archive))

        participant_sessions = []
        for index in range(3):
            email = f"stretch-{index}-{suffix}@example.org"
            status, _, cookie = call("POST", "/api/auth/register", {
                "name": f"Stretch {index}", "email": email, "password": "ParticipantPass2026!",
            })
            self.assertEqual(status, 201)
            cookie = cookie.split(";", 1)[0]
            participant_sessions.append(cookie)
            self.assertEqual(call("POST", f"/api/events/{event_id}/registration", {}, cookie)[0], 201)
            status, team, _ = call("POST", f"/api/events/{event_id}/teams", {"name": f"Team {index}"}, cookie)
            self.assertEqual(status, 201, team)
            status, project, _ = call("POST", f"/api/events/{event_id}/projects", {
                "team_id": team["id"], "track_id": track_id, "title": f"Project {index}",
                "summary": "A complete stretch test project", "description": "Test detail",
                "repo_url": f"https://example.org/{suffix}/{index}", "status": "submitted",
            }, cookie)
            self.assertEqual(status, 201, project)

        status, embed, _ = call("GET", f"/embed/{event_id}")
        self.assertEqual(status, 200)
        self.assertIn("Project 0", embed)

        status, judge_account, _ = call("POST", f"/api/admin/events/{event_id}/judges", {
            "name": "Pair Judge", "email": f"judge-{suffix}@example.org", "tracks": [track_id],
        }, admin)
        self.assertEqual(status, 201, judge_account)
        status, _, judge_cookie = call("POST", "/api/auth/login", {
            "email": judge_account["email"], "password": judge_account["temporary_password"],
        })
        self.assertEqual(status, 200)
        judge_cookie = judge_cookie.split(";", 1)[0]

        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.assertEqual(call("PATCH", f"/api/events/{event_id}", {"submissions_close": past}, admin)[0], 200)
        status, pairs, _ = call("POST", f"/api/events/{event_id}/pairwise/assignments/batch",
                                {"comparisons_per_project": 2}, admin)
        self.assertEqual(status, 200, pairs)
        self.assertEqual(len(pairs["created"]), 3)
        assignments = call("GET", f"/api/events/{event_id}/pairwise/my-assignments", cookie=judge_cookie)[1]["assignments"]
        for pair in assignments:
            winner_id = pair["project_a_id"] if pair["project_a"] < pair["project_b"] else pair["project_b_id"]
            status, _, _ = call("PUT", f"/api/pairwise/assignments/{pair['id']}",
                                {"winner_id": winner_id}, judge_cookie)
            self.assertEqual(status, 200)
        ranking = call("GET", f"/api/events/{event_id}/pairwise/rankings", cookie=admin)[1]
        self.assertEqual(ranking["completed"], 3)
        self.assertEqual([row["title"] for row in ranking["projects"]],
                         ["Project 0", "Project 1", "Project 2"])

        status, batch, _ = call("POST", f"/api/events/{event_id}/assignments/batch",
                                {"reviews_per_project": 1}, admin)
        self.assertEqual(status, 200, batch)
        for assignment in batch["created"]:
            status, body, _ = call("PUT", f"/api/judge/assignments/{assignment['assignment_id']}/scorecard", {
                "criteria": {"functionality": 4, "quality": 4, "impact": 4},
                "comment": "A complete review.", "status": "submitted",
            }, judge_cookie)
            self.assertEqual(status, 200, body)
        status, published, _ = call("POST", f"/api/events/{event_id}/results/publish",
                                    {"acknowledge_limited_evidence": True}, admin)
        self.assertEqual(status, 200, published)

        status, issued, _ = call("POST", f"/api/events/{event_id}/judge-records/issue", {}, admin)
        self.assertEqual(status, 200, issued)
        self.assertEqual(len(issued["created"]), 1)
        record = call("GET", f"/api/judge-records/{issued['created'][0]}")[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "public.pem").write_text(record["public_key_pem"])
            (root / "payload.json").write_text(record["canonical_payload"])
            (root / "signature.bin").write_bytes(base64.b64decode(record["signature_base64"]))
            verified = subprocess.run([
                "openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(root / "public.pem"),
                "-in", str(root / "payload.json"), "-sigfile", str(root / "signature.bin"),
            ], capture_output=True)
        self.assertEqual(verified.returncode, 0, verified.stderr.decode())

        status, hook, _ = call("POST", f"/api/events/{event_id}/webhooks",
                               {"url": "https://example.invalid/beyondbug"}, admin)
        self.assertEqual(status, 201, hook)
        self.assertTrue(hook["secret"])
        self.assertEqual(call("POST", f"/api/events/{event_id}/webhooks/{hook['id']}/test", {}, admin)[0], 200)
        deliveries = call("GET", f"/api/events/{event_id}/webhooks/deliveries", cookie=admin)[1]
        self.assertEqual(deliveries["deliveries"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
