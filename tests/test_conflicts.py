"""A judge can recuse themself, but cannot alter another judge's assignment."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from test_lifecycle import call


class ConflictTests(unittest.TestCase):
    def test_judge_self_report_removes_assignment_and_blocks_reassignment(self):
        suffix = uuid.uuid4().hex[:10]

        def account(role):
            status, _, cookie = call("POST", "/api/auth/register", {
                "name": f"Conflict {role}", "email": f"conflict-{role}-{suffix}@example.org",
                "password": "A-long-local-test-password!",
            })
            self.assertEqual(status, 201)
            return cookie.split(";", 1)[0]

        organizer = account("organizer")
        status, event, _ = call("POST", "/api/events", {
            "name": f"Conflict event {suffix}",
            "submissions_close": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "tracks": ["Software"],
        }, organizer)
        self.assertEqual(status, 201, event)
        event_id = event["id"]
        _, detail, _ = call("GET", f"/api/events/{event_id}")
        track_id = detail["tracks"][0]["id"]
        self.assertEqual(call("POST", f"/api/events/{event_id}/registration", {}, organizer)[0], 201)
        _, team, _ = call("POST", f"/api/events/{event_id}/teams", {"name": "Maker team"}, organizer)
        status, project, _ = call("POST", f"/api/events/{event_id}/projects", {
            "team_id": team["id"], "track_id": track_id, "title": "Conflict candidate", "status": "submitted",
        }, organizer)
        self.assertEqual(status, 201, project)
        self.assertEqual(call("PUT", f"/api/events/{event_id}/rubric", {
            "name": "Review", "criteria": [{"slug": "quality", "name": "Quality", "weight": 1}],
        }, organizer)[0], 200)

        judge = account("judge")
        status, invite, _ = call("POST", f"/api/events/{event_id}/judges/invites", {
            "email": f"conflict-judge-{suffix}@example.org",
        }, organizer)
        self.assertEqual(status, 201)
        token = invite["invite_url"].split("/")[-1]
        status, accepted, _ = call("POST", f"/api/judge-invites/{token}/accept", {}, judge)
        self.assertEqual(status, 200)
        judge_id = accepted["judge_id"]
        self.assertEqual(call("PUT", f"/api/events/{event_id}/judges/{judge_id}/tracks", {
            "tracks": [track_id],
        }, organizer)[0], 200)
        status, assigned, _ = call("POST", f"/api/events/{event_id}/assignments/batch", {
            "reviews_per_project": 1,
        }, organizer)
        self.assertEqual(status, 200)
        self.assertEqual(len(assigned["created"]), 1)
        status, desk, _ = call("GET", f"/judge/{event_id}", cookie=judge)
        self.assertEqual(status, 200)
        self.assertIn("Report a conflict", desk)

        other = account("other")
        path = f"/api/events/{event_id}/judges/{judge_id}/conflicts/{project['id']}"
        self.assertEqual(call("PUT", path, {"reason": "Not my assignment"}, other)[0], 403)
        self.assertEqual(call("PUT", path, {"reason": "I know this team personally"}, judge)[0], 200)
        status, queue, _ = call("GET", f"/api/judge/assignments?event_id={event_id}", cookie=judge)
        self.assertEqual(status, 200)
        self.assertEqual(queue["assignments"], [])
        _, progress, _ = call("GET", f"/api/events/{event_id}/progress", cookie=organizer)
        self.assertEqual(progress["projects"][0]["assigned"], 0)
        _, audit, _ = call("GET", f"/api/events/{event_id}/audit", cookie=organizer)
        self.assertTrue(any(item["action"] == "judge.conflict_declared" for item in audit["entries"]))
        _, retry, _ = call("POST", f"/api/events/{event_id}/assignments/batch", {
            "reviews_per_project": 1,
        }, organizer)
        self.assertEqual(retry["created"], [])
        self.assertEqual(retry["shortages"][0]["missing"], 1)


if __name__ == "__main__":
    unittest.main()
