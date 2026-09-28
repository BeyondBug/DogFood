"""End-to-end invitation ballot, abuse controls, comments and publication."""

import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from test_lifecycle import creator_cookie, call
from src.public import order_ballot


class VotingTests(unittest.TestCase):
    def test_ballot_order_is_stable_and_varies_by_voter(self):
        projects = [{"id": f"prj_{letter}"} for letter in "abcde"]
        seed = "11" * 32
        first = [row["id"] for row in order_ballot(projects, seed, "voter-a")]
        second = [row["id"] for row in order_ballot(projects, seed, "voter-b")]
        self.assertEqual(first, ["prj_d", "prj_a", "prj_e", "prj_b", "prj_c"])
        self.assertEqual(second, ["prj_d", "prj_c", "prj_e", "prj_b", "prj_a"])
        self.assertEqual(first, [row["id"] for row in order_ballot(list(reversed(projects)), seed, "voter-a")])

    def test_participant_ballot_blocks_self_vote_sybil_and_retries(self):
        suffix = uuid.uuid4().hex[:10]

        def account(prefix):
            status, body, cookie = call("POST", "/api/auth/register", {
                "name": "Ballot participant", "email": f"{prefix}-{suffix}@example.org",
                "password": "A-long-local-test-password!",
            })
            self.assertEqual(status, 201, body)
            return cookie.split(";", 1)[0]

        organizer = creator_cookie()
        status, event, _ = call("POST", "/api/events", {
            "name": f"Participant ballot {suffix}",
            "submissions_close": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "tracks": ["Software"],
        }, organizer)
        self.assertEqual(status, 201, event)
        event_id = event["id"]
        _, detail, _ = call("GET", f"/api/events/{event_id}")
        track_id = detail["tracks"][0]["id"]

        def project(cookie, team_name, title):
            status, _, _ = call("POST", f"/api/events/{event_id}/registration", {}, cookie)
            self.assertEqual(status, 201)
            status, team, _ = call("POST", f"/api/events/{event_id}/teams", {"name": team_name}, cookie)
            self.assertEqual(status, 201)
            status, result, _ = call("POST", f"/api/events/{event_id}/projects", {
                "team_id": team["id"], "track_id": track_id, "title": title, "status": "submitted",
            }, cookie)
            self.assertEqual(status, 201, result)
            return result["id"]

        own_project = project(organizer, "My team", "My work")
        other = account("pother")
        other_project = project(other, "Other team", "Other work")
        now = datetime.now(timezone.utc)
        status, _, _ = call("PATCH", f"/api/events/{event_id}", {
            "submissions_close": (now - timedelta(minutes=2)).isoformat(),
        }, organizer)
        self.assertEqual(status, 200)
        status, _, _ = call("PUT", f"/api/events/{event_id}/voting", {
            "mode": "participants", "opens_at": (now + timedelta(seconds=1)).isoformat(),
            "closes_at": (now + timedelta(hours=1)).isoformat(),
        }, organizer)
        self.assertEqual(status, 200)
        time.sleep(1.2)
        status, ballot, _ = call("GET", f"/api/events/{event_id}/ballot", cookie=organizer)
        self.assertEqual(status, 200, ballot)
        self.assertEqual([item["id"] for item in ballot["projects"]], [other_project])
        status, _, _ = call("POST", f"/api/events/{event_id}/votes", {"project_id": own_project}, organizer)
        self.assertEqual(status, 403)
        status, _, _ = call("POST", f"/api/events/{event_id}/votes", {"project_id": other_project}, organizer)
        self.assertEqual(status, 201)
        for _ in range(3):
            status, _, _ = call("POST", f"/api/events/{event_id}/votes", {"project_id": other_project}, organizer)
            self.assertEqual(status, 409)
        status, _, _ = call("POST", f"/api/events/{event_id}/votes", {"project_id": other_project}, organizer)
        self.assertEqual(status, 429)
        late_account = account("plate")
        status, _, _ = call("POST", f"/api/events/{event_id}/registration", {}, late_account)
        self.assertEqual(status, 201)
        status, _, _ = call("GET", f"/api/events/{event_id}/ballot", cookie=late_account)
        self.assertEqual(status, 403)
        status, summary, _ = call("GET", f"/api/events/{event_id}/votes/summary", cookie=organizer)
        self.assertEqual(status, 200)
        self.assertEqual(summary["attempts"]["self_vote"], 1)
        self.assertEqual(summary["attempts"]["rate_limited"], 1)

    def test_invited_ballot_stays_private_until_publication(self):
        suffix = uuid.uuid4().hex[:10]

        def account(name, prefix):
            email = f"{prefix}-{suffix}@example.org"
            status, body, cookie = call("POST", "/api/auth/register", {
                "name": name, "email": email, "password": "A-long-local-test-password!",
            })
            self.assertEqual(status, 201, body)
            return email, cookie.split(";", 1)[0]

        organizer_email, _ = account("Voting organizer", "vorg")
        organizer = creator_cookie()
        status, event, _ = call("POST", "/api/events", {
            "name": f"Voting {suffix}",
            "submissions_close": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "tracks": ["Software"],
        }, organizer)
        self.assertEqual(status, 201, event)
        event_id = event["id"]
        status, detail, _ = call("GET", f"/api/events/{event_id}")
        track_id = detail["tracks"][0]["id"]

        def submit(cookie, team_name, title):
            status, _, _ = call("POST", f"/api/events/{event_id}/registration", {}, cookie)
            self.assertEqual(status, 201)
            status, team, _ = call("POST", f"/api/events/{event_id}/teams", {"name": team_name}, cookie)
            self.assertEqual(status, 201, team)
            status, project, _ = call("POST", f"/api/events/{event_id}/projects", {
                "team_id": team["id"], "track_id": track_id, "title": title, "status": "submitted",
            }, cookie)
            self.assertEqual(status, 201, project)
            return project["id"]

        first_project = submit(organizer, "First team", "First project")
        _, second_author = account("Other maker", "vmaker")
        second_project = submit(second_author, "Second team", "Second project")

        now = datetime.now(timezone.utc)
        status, _, _ = call("PATCH", f"/api/events/{event_id}", {
            "submissions_close": (now - timedelta(minutes=3)).isoformat(),
        }, organizer)
        self.assertEqual(status, 200)
        status, _, _ = call("PUT", f"/api/events/{event_id}/voting", {
            "mode": "invite_only", "opens_at": (now - timedelta(minutes=1)).isoformat(),
            "closes_at": (now + timedelta(seconds=8)).isoformat(),
        }, organizer)
        self.assertEqual(status, 200)
        status, public_event, _ = call("GET", f"/api/events/{event_id}")
        self.assertEqual(status, 200)
        self.assertNotIn("ballot_seed", public_event["event"])
        status, organizer_page, _ = call("GET", f"/organizer/{event_id}", cookie=organizer)
        self.assertEqual(status, 200)
        self.assertIn("Save event details", organizer_page)
        status, _, _ = call("PATCH", f"/api/events/{event_id}", {
            "submissions_close": (now + timedelta(minutes=1)).isoformat(),
        }, organizer)
        self.assertEqual(status, 422)

        voter_email, voter = account("Invited voter", "vvoter")
        status, invite, _ = call("POST", f"/api/events/{event_id}/voter-invites", {
            "email": voter_email,
        }, organizer)
        self.assertEqual(status, 201, invite)
        status, _, _ = call("GET", f"/api/events/{event_id}/ballot", cookie=voter)
        self.assertEqual(status, 403)
        token = invite["invite_url"].split("/")[-1]
        status, accepted, _ = call("POST", f"/api/voter-invites/{token}/accept", {}, voter)
        self.assertEqual(status, 200, accepted)
        status, ballot, _ = call("GET", f"/api/events/{event_id}/ballot", cookie=voter)
        self.assertEqual(status, 200, ballot)
        self.assertEqual({item["id"] for item in ballot["projects"]}, {first_project, second_project})
        self.assertNotIn("votes", str(ballot))
        status, again, _ = call("GET", f"/api/events/{event_id}/ballot", cookie=voter)
        self.assertEqual(status, 200, again)
        self.assertEqual([item["id"] for item in ballot["projects"]],
                         [item["id"] for item in again["projects"]])
        status, page, _ = call("GET", f"/vote/{event_id}", cookie=voter)
        self.assertEqual(status, 200, page)
        status, vote, _ = call("POST", f"/api/events/{event_id}/votes", {"project_id": first_project}, voter)
        self.assertEqual(status, 201, vote)
        status, _, _ = call("PATCH", f"/api/events/{event_id}", {
            "submissions_close": (now - timedelta(minutes=4)).isoformat(),
        }, organizer)
        self.assertEqual(status, 409)
        status, _, _ = call("POST", f"/api/events/{event_id}/votes", {"project_id": second_project}, voter)
        self.assertEqual(status, 409)
        status, _, _ = call("GET", f"/api/events/{event_id}/votes/results")
        self.assertEqual(status, 404)
        status, _, _ = call("POST", f"/api/events/{event_id}/results/publish", {}, organizer)
        self.assertEqual(status, 409)

        status, comment, _ = call("POST", f"/api/projects/{first_project}/comments", {
            "body": "A thoughtful question about the build.",
        }, voter)
        self.assertEqual(status, 201, comment)
        status, _, _ = call("POST", f"/api/projects/{first_project}/comments", {
            "body": "A thoughtful question about the build.",
        }, voter)
        self.assertEqual(status, 409)
        status, comments, _ = call("GET", f"/api/projects/{first_project}/comments")
        self.assertEqual(status, 200)
        self.assertEqual(len(comments["comments"]), 1)
        status, _, _ = call("DELETE", f"/api/comments/{comment['id']}", cookie=organizer)
        self.assertEqual(status, 200)
        status, comments, _ = call("GET", f"/api/projects/{first_project}/comments")
        self.assertEqual(status, 200)
        self.assertEqual(len(comments["comments"]), 0)
        for index in range(4):
            status, _, _ = call("POST", f"/api/projects/{first_project}/comments", {
                "body": f"Different discussion point {index} about the project.",
            }, voter)
            self.assertEqual(status, 201)
        status, _, _ = call("POST", f"/api/projects/{first_project}/comments", {
            "body": "One comment above the hourly limit.",
        }, voter)
        self.assertEqual(status, 429)
        status, audit, _ = call("GET", f"/api/events/{event_id}/audit", cookie=organizer)
        self.assertEqual(status, 200)
        self.assertTrue(any(row["action"] == "comment.hidden" for row in audit["entries"]))

        judge_email, judge = account("Voting judge", "vjudge")
        status, judge_invite, _ = call("POST", f"/api/events/{event_id}/judges/invites", {
            "email": judge_email,
        }, organizer)
        self.assertEqual(status, 201)
        status, accepted_judge, _ = call("POST", f"/api/judge-invites/{judge_invite['invite_url'].split('/')[-1]}/accept", {}, judge)
        self.assertEqual(status, 200)
        status, _, _ = call("PUT", f"/api/events/{event_id}/judges/{accepted_judge['judge_id']}/tracks", {
            "tracks": [track_id],
        }, organizer)
        self.assertEqual(status, 200)
        status, assignments, _ = call("POST", f"/api/events/{event_id}/assignments/batch", {
            "reviews_per_project": 1,
        }, organizer)
        self.assertEqual(status, 200, assignments)
        self.assertEqual(len(assignments["created"]), 2)
        for item in assignments["created"]:
            status, _, _ = call("PUT", f"/api/judge/assignments/{item['assignment_id']}/scorecard", {
                "criteria": {"functionality": 4, "quality": 4, "impact": 4},
                "status": "submitted",
            }, judge)
            self.assertEqual(status, 200)

        remaining = (now + timedelta(seconds=8) - datetime.now(timezone.utc)).total_seconds()
        if remaining > 0:
            time.sleep(remaining + 0.2)
        status, published, _ = call("POST", f"/api/events/{event_id}/results/publish", {}, organizer)
        self.assertEqual(status, 200, published)
        status, tally, _ = call("GET", f"/api/events/{event_id}/votes/results")
        self.assertEqual(status, 200, tally)
        self.assertEqual(tally["total_votes"], 1)
        self.assertEqual(next(item["votes"] for item in tally["projects"] if item["id"] == first_project), 1)


if __name__ == "__main__":
    unittest.main()
