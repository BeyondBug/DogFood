"""Run against `docker compose up`: python3 -m unittest discover -s tests."""

import json
import os
import unittest
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone


BASE = os.getenv("DOGFOOD_TEST_URL", "http://localhost:8080")


def call(method, path, body=None, cookie=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if cookie:
        request.add_header("Cookie", cookie)
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with closing(response):
        status = response.status
        cookie_header = response.headers.get("Set-Cookie", "")
        content = response.read().decode()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = content
    return status, parsed, cookie_header


class LifecycleTests(unittest.TestCase):
    def test_login_throttle_uses_account_and_preserves_other_logins(self):
        suffix = uuid.uuid4().hex[:10]
        email = f"login-{suffix}@example.org"
        password = "A-long-local-test-password!"
        status, _, _ = call("POST", "/api/auth/register", {
            "name": "Login tester", "email": email, "password": password,
        })
        self.assertEqual(status, 201)
        for _ in range(5):
            status, body, _ = call("POST", "/api/auth/login", {
                "email": email, "password": "Incorrect-password-123!",
            })
            self.assertEqual(status, 401, body)
        status, body, _ = call("POST", "/api/auth/login", {
            "email": email, "password": password,
        })
        self.assertEqual(status, 429, body)
        self.assertIn("Too many login attempts", body["detail"])
        other_email = f"other-login-{suffix}@example.org"
        status, _, _ = call("POST", "/api/auth/register", {
            "name": "Second tester", "email": other_email, "password": password,
        })
        self.assertEqual(status, 201)
        status, _, _ = call("POST", "/api/auth/login", {
            "email": other_email, "password": password,
        })
        self.assertEqual(status, 200)

    def test_team_membership_and_workspace_lock_at_submission_close(self):
        suffix = uuid.uuid4().hex[:10]
        status, _, captain_cookie = call("POST", "/api/auth/register", {
            "name": "Deadline captain", "email": f"deadline-captain-{suffix}@example.org",
            "password": "A-long-local-test-password!",
        })
        self.assertEqual(status, 201)
        captain_cookie = captain_cookie.split(";", 1)[0]
        status, event, _ = call("POST", "/api/events", {
            "name": f"Deadline teams {suffix}",
            "submissions_close": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "tracks": ["Software"],
        }, captain_cookie)
        self.assertEqual(status, 201, event)
        event_id = event["id"]
        status, _, _ = call("POST", f"/api/events/{event_id}/registration", {}, captain_cookie)
        self.assertEqual(status, 201)
        status, team, _ = call("POST", f"/api/events/{event_id}/teams", {"name": "Deadline team"}, captain_cookie)
        self.assertEqual(status, 201)
        status, invite, _ = call("POST", f"/api/teams/{team['id']}/invites", {}, captain_cookie)
        self.assertEqual(status, 201)
        token = invite["invite_url"].split("/")[-1]
        status, _, newcomer_cookie = call("POST", "/api/auth/register", {
            "name": "Late teammate", "email": f"deadline-newcomer-{suffix}@example.org",
            "password": "A-long-local-test-password!",
        })
        self.assertEqual(status, 201)
        newcomer_cookie = newcomer_cookie.split(";", 1)[0]
        status, _, _ = call("PATCH", f"/api/events/{event_id}", {
            "submissions_close": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        }, captain_cookie)
        self.assertEqual(status, 200)
        status, _, _ = call("PATCH", f"/api/events/{event_id}", {
            "submissions_close": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        }, captain_cookie)
        self.assertEqual(status, 409)
        status, _, _ = call("POST", f"/api/team-invites/{token}/join", {}, newcomer_cookie)
        self.assertEqual(status, 409)
        status, invite_page, _ = call("GET", f"/join/{token}", cookie=newcomer_cookie)
        self.assertEqual(status, 200)
        self.assertIn("no longer available", invite_page)
        self.assertNotIn('data-action="accept-invite"', invite_page)
        status, _, _ = call("POST", f"/api/teams/{team['id']}/invites", {}, captain_cookie)
        self.assertEqual(status, 409)
        status, _, _ = call("POST", f"/api/events/{event_id}/registration", {}, newcomer_cookie)
        self.assertEqual(status, 201)
        status, _, _ = call("POST", f"/api/events/{event_id}/teams", {"name": "Late team"}, newcomer_cookie)
        self.assertEqual(status, 409)
        status, workspace, _ = call("GET", f"/workspace/{event_id}", cookie=captain_cookie)
        self.assertEqual(status, 200)
        self.assertIn("read-only", workspace)
        self.assertNotIn('data-action="project"', workspace)
        self.assertNotIn("Create invite link", workspace)

    def test_team_invite_is_single_use_and_team_stops_at_four(self):
        suffix = uuid.uuid4().hex[:10]
        status, _, captain_cookie = call("POST", "/api/auth/register", {
            "name": "Team captain", "email": f"captain-{suffix}@example.org",
            "password": "A-long-local-test-password!",
        })
        self.assertEqual(status, 201)
        captain_cookie = captain_cookie.split(";", 1)[0]
        status, event, _ = call("POST", "/api/events", {
            "name": f"Teams {suffix}", "submissions_close":
            (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(), "tracks": ["Software"],
        }, captain_cookie)
        self.assertEqual(status, 201, event)
        event_id = event["id"]
        status, _, _ = call("POST", f"/api/events/{event_id}/registration", {}, captain_cookie)
        self.assertEqual(status, 201)
        status, team, _ = call("POST", f"/api/events/{event_id}/teams", {"name": "Four people"}, captain_cookie)
        self.assertEqual(status, 201)
        last_token = ""
        last_member_cookie = ""
        for index in range(3):
            status, invite, _ = call("POST", f"/api/teams/{team['id']}/invites", {}, captain_cookie)
            self.assertEqual(status, 201, invite)
            last_token = invite["invite_url"].split("/")[-1]
            status, _, member_cookie = call("POST", "/api/auth/register", {
                "name": f"Member {index}", "email": f"member-{index}-{suffix}@example.org",
                "password": "Another-long-test-password!",
            })
            self.assertEqual(status, 201)
            last_member_cookie = member_cookie.split(";", 1)[0]
            status, _, _ = call("POST", f"/api/team-invites/{last_token}/join", {}, last_member_cookie)
            self.assertEqual(status, 200)
        status, _, _ = call("POST", f"/api/teams/{team['id']}/invites", {}, captain_cookie)
        self.assertEqual(status, 409)
        status, _, _ = call("POST", f"/api/team-invites/{last_token}/join", {}, last_member_cookie)
        self.assertEqual(status, 404)
        status, team_view, _ = call("GET", f"/api/events/{event_id}/my-team", cookie=captain_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(len(team_view["members"]), 4)

    def test_judging_publication_and_isolation(self):
        suffix = uuid.uuid4().hex[:10]
        status, _, organizer_cookie = call("POST", "/api/auth/register", {
            "name": "Review organizer", "email": f"review-org-{suffix}@example.org",
            "password": "A-long-local-test-password!",
        })
        self.assertEqual(status, 201)
        organizer_cookie = organizer_cookie.split(";", 1)[0]
        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        status, event, _ = call("POST", "/api/events", {
            "name": f"Review {suffix}", "submissions_close": future, "tracks": ["Software"],
            "prizes": ["Grand prize"],
        }, organizer_cookie)
        self.assertEqual(status, 201, event)
        event_id = event["id"]
        status, detail, _ = call("GET", f"/api/events/{event_id}")
        track_id = detail["tracks"][0]["id"]
        prize_id = detail["prizes"][0]["id"]
        status, _, _ = call("POST", f"/api/events/{event_id}/registration", {}, organizer_cookie)
        self.assertEqual(status, 201)
        status, team, _ = call("POST", f"/api/events/{event_id}/teams", {"name": "Review team"}, organizer_cookie)
        self.assertEqual(status, 201)
        status, project, _ = call("POST", f"/api/events/{event_id}/projects", {
            "team_id": team["id"], "track_id": track_id, "title": "Scored project " + suffix,
            "status": "submitted",
        }, organizer_cookie)
        self.assertEqual(status, 201, project)
        status, _, _ = call("PUT", f"/api/events/{event_id}/rubric", {
            "name": "Weighted review", "criteria": [
                {"slug": "quality", "name": "Quality", "weight": 3},
                {"slug": "impact", "name": "Impact", "weight": 1},
            ],
        }, organizer_cookie)
        self.assertEqual(status, 200)
        email = f"review-judge-{suffix}@example.org"
        status, invitation, _ = call("POST", f"/api/events/{event_id}/judges/invites", {"email": email}, organizer_cookie)
        self.assertEqual(status, 201, invitation)
        status, pending_page, _ = call("GET", f"/organizer/{event_id}", cookie=organizer_cookie)
        self.assertEqual(status, 200)
        self.assertIn("Judge invitations (1)", pending_page)
        self.assertIn("Pending", pending_page)
        status, _, judge_cookie = call("POST", "/api/auth/register", {
            "name": "Review judge", "email": email, "password": "Another-long-test-password!",
        })
        self.assertEqual(status, 201)
        judge_cookie = judge_cookie.split(";", 1)[0]
        token = invitation["invite_url"].split("/")[-1]
        status, accepted, _ = call("POST", f"/api/judge-invites/{token}/accept", {}, judge_cookie)
        self.assertEqual(status, 200, accepted)
        status, accepted_page, _ = call("GET", f"/organizer/{event_id}", cookie=organizer_cookie)
        self.assertEqual(status, 200)
        self.assertIn("Accepted", accepted_page)
        status, _, _ = call("PUT", f"/api/events/{event_id}/judges/{accepted['judge_id']}/tracks", {
            "tracks": [track_id],
        }, organizer_cookie)
        self.assertEqual(status, 200)
        status, _, _ = call("POST", f"/api/events/{event_id}/assignments/batch", {
            "reviews_per_project": 1,
        }, organizer_cookie)
        self.assertEqual(status, 409)
        status, _, _ = call("POST", f"/api/events/{event_id}/results/publish", {}, organizer_cookie)
        self.assertEqual(status, 409)
        status, _, _ = call("POST", f"/api/events/{event_id}/certificates/issue", {}, organizer_cookie)
        self.assertEqual(status, 409)
        status, _, _ = call("POST", f"/api/events/{event_id}/certificates/issue", {}, judge_cookie)
        self.assertEqual(status, 403)
        status, _, _ = call("PATCH", f"/api/events/{event_id}", {
            "submissions_close": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        }, organizer_cookie)
        self.assertEqual(status, 200)
        status, assigned, _ = call("POST", f"/api/events/{event_id}/assignments/batch", {
            "reviews_per_project": 1,
        }, organizer_cookie)
        self.assertEqual(status, 200, assigned)
        self.assertEqual(len(assigned["created"]), 1)
        assignment_id = assigned["created"][0]["assignment_id"]
        status, organizer_page, _ = call("GET", f"/organizer/{event_id}", cookie=organizer_cookie)
        self.assertEqual(status, 200)
        self.assertIn("Event readiness", organizer_page)
        self.assertIn("View judging progress", organizer_page)
        status, judge_page, _ = call("GET", f"/judge/{event_id}", cookie=judge_cookie)
        self.assertEqual(status, 200)
        self.assertIn("Continue judging", judge_page)
        self.assertIn('data-autosave="true"', judge_page)
        status, _, _ = call("PUT", f"/api/judge/assignments/{assignment_id}/scorecard", {
            "criteria": {"quality": 5, "impact": 1}, "status": "submitted",
        }, organizer_cookie)
        self.assertEqual(status, 403)
        for invalid in (float("nan"), float("inf")):
            status, _, _ = call("PUT", f"/api/judge/assignments/{assignment_id}/scorecard", {
                "criteria": {"quality": invalid, "impact": 1}, "status": "submitted",
            }, judge_cookie)
            self.assertEqual(status, 422)
        status, scorecard, _ = call("PUT", f"/api/judge/assignments/{assignment_id}/scorecard", {
            "criteria": {"quality": 5, "impact": 1}, "status": "submitted",
        }, judge_cookie)
        self.assertEqual(status, 200, scorecard)
        status, activity_page, _ = call("GET", f"/organizer/{event_id}?activity=Judging", cookie=organizer_cookie)
        self.assertEqual(status, 200)
        self.assertIn("Submitted review", activity_page)
        self.assertIn("Scored project " + suffix, activity_page)
        self.assertNotIn("Created team</strong>", activity_page)
        status, _, _ = call("GET", f"/api/events/{event_id}/results")
        self.assertEqual(status, 404)
        status, ranking, _ = call("GET", f"/api/events/{event_id}/rankings", cookie=organizer_cookie)
        self.assertEqual(status, 200, ranking)
        self.assertAlmostEqual(ranking["projects"][0]["raw_score"], 4.0)
        status, exported, _ = call("GET", f"/api/events/{event_id}/exports/assignments.csv", cookie=organizer_cookie)
        self.assertEqual(status, 200)
        self.assertIn("assignment_id,project_id", exported)
        status, _, _ = call("GET", f"/api/events/{event_id}/exports/assignments.csv", cookie=judge_cookie)
        self.assertEqual(status, 403)
        status, _, _ = call("GET", f"/api/events/{event_id}/rankings", cookie=judge_cookie)
        self.assertEqual(status, 403)
        status, published, _ = call("POST", f"/api/events/{event_id}/results/publish", {}, organizer_cookie)
        self.assertEqual(status, 200, published)
        status, _, _ = call("POST", f"/api/events/{event_id}/assignments/batch", {
            "reviews_per_project": 1,
        }, organizer_cookie)
        self.assertEqual(status, 409)
        status, results, _ = call("GET", f"/api/events/{event_id}/results")
        self.assertEqual(status, 200, results)
        status, _, _ = call("PUT", f"/api/events/{event_id}/prizes/{prize_id}/winner", {
            "project_id": project["id"],
        }, judge_cookie)
        self.assertEqual(status, 403)
        status, _, _ = call("PUT", f"/api/events/{event_id}/prizes/{prize_id}/winner", {
            "project_id": "prj_01",
        }, organizer_cookie)
        self.assertEqual(status, 404)
        status, _, _ = call("PUT", f"/api/events/{event_id}/prizes/{prize_id}/winner", {
            "project_id": project["id"],
        }, organizer_cookie)
        self.assertEqual(status, 200)
        status, issued, _ = call("POST", f"/api/events/{event_id}/certificates/issue", {}, organizer_cookie)
        self.assertEqual(status, 200, issued)
        self.assertEqual(issued["created"], {"participant": 1, "winner": 1})
        status, again, _ = call("POST", f"/api/events/{event_id}/certificates/issue", {}, organizer_cookie)
        self.assertEqual(status, 200, again)
        self.assertEqual(again["total_created"], 0)
        status, _, _ = call("POST", f"/api/events/{event_id}/certificates/issue", {}, judge_cookie)
        self.assertEqual(status, 403)
        status, owned, _ = call("GET", "/api/me/certificates", cookie=organizer_cookie)
        self.assertEqual(status, 200)
        records = [item for item in owned["certificates"] if item["event_name"] == f"Review {suffix}"]
        self.assertEqual({item["kind"] for item in records}, {"participant", "winner"})
        participant_id = next(item["id"] for item in records if item["kind"] == "participant")
        winner_id = next(item["id"] for item in records if item["kind"] == "winner")
        status, participant_record, _ = call("GET", f"/api/certificates/{participant_id}/verify")
        self.assertEqual(status, 200)
        self.assertEqual(participant_record["project"], "Scored project " + suffix)
        self.assertEqual(participant_record["event"], f"Review {suffix}")
        self.assertIsNone(participant_record["prize"])
        self.assertEqual(participant_record["recipient"], "Review organizer")
        status, verified, _ = call("GET", f"/api/certificates/{winner_id}/verify")
        self.assertEqual(status, 200)
        self.assertTrue(verified["verified"])
        self.assertEqual(verified["prize"], "Grand prize")
        self.assertEqual(verified["project"], participant_record["project"])
        self.assertEqual(verified["recipient"], participant_record["recipient"])
        status, judge_certificates, _ = call("GET", "/api/me/certificates", cookie=judge_cookie)
        self.assertEqual(status, 200)
        self.assertFalse(any(item["event_name"] == f"Review {suffix}"
                             for item in judge_certificates["certificates"]))
        status, art, _ = call("GET", f"/certificates/{winner_id}.svg")
        self.assertEqual(status, 200)
        self.assertIn("Certificate of distinction", art)
        status, page, _ = call("GET", f"/certificates/{winner_id}")
        self.assertEqual(status, 200)
        self.assertIn("Verified record", page)
        status, _, _ = call("GET", f"/api/events/{event_id}/certificates", cookie=judge_cookie)
        self.assertEqual(status, 403)
        status, _, _ = call("PUT", f"/api/judge/assignments/{assignment_id}/scorecard", {
            "criteria": {"quality": 1, "impact": 1}, "status": "submitted",
        }, judge_cookie)
        self.assertEqual(status, 409)
        status, _, _ = call("PUT", f"/api/projects/{project['id']}", {
            "title": "Changed after results", "track_id": track_id, "status": "submitted",
        }, organizer_cookie)
        self.assertEqual(status, 409)
        status, _, _ = call("POST", f"/api/events/{event_id}/projects", {
            "team_id": team["id"], "track_id": track_id,
            "title": "Late arrival after publication", "status": "submitted",
        }, organizer_cookie)
        self.assertEqual(status, 409)
        status, _, _ = call("PUT", f"/api/events/{event_id}/judges/{accepted['judge_id']}/conflicts/{project['id']}", {
            "reason": "Found a conflict after submitting",
        }, organizer_cookie)
        self.assertEqual(status, 409)

    def test_fresh_event_and_team_submission(self):
        suffix = uuid.uuid4().hex[:10]
        status, account, cookie = call("POST", "/api/auth/register", {
            "name": "Test organizer", "email": f"organizer-{suffix}@example.org",
            "password": "A-long-local-test-password!",
        })
        self.assertEqual(status, 201, account)
        cookie = cookie.split(";", 1)[0]
        now = datetime.now(timezone.utc)
        future = (now + timedelta(days=2)).isoformat()
        status, event, _ = call("POST", "/api/events", {
            "name": f"Lifecycle {suffix}", "description": "Integration test event",
            "submissions_close": future, "tracks": ["Software", "Design"], "prizes": ["Grand prize"],
        }, cookie)
        self.assertEqual(status, 201, event)
        event_id = event["id"]
        status, directory, _ = call("GET", f"/events?q=Lifecycle%20{suffix}")
        self.assertEqual(status, 200)
        self.assertIn(f'href="/events/{event_id}"', directory)
        self.assertIn(f"Lifecycle {suffix}", directory)
        status, last_page, _ = call("GET", "/events?page=9999")
        self.assertEqual(status, 200)
        self.assertIn("Showing ", last_page)
        status, detail, _ = call("GET", f"/api/events/{event_id}")
        self.assertEqual(status, 200)
        track_id = detail["tracks"][0]["id"]
        self.assertEqual(len(detail["prizes"]), 1)
        status, result, _ = call("POST", f"/api/events/{event_id}/registration", {}, cookie)
        self.assertEqual(status, 201, result)
        status, team, _ = call("POST", f"/api/events/{event_id}/teams", {"name": "Beyond Test"}, cookie)
        self.assertEqual(status, 201, team)
        status, invite, _ = call("POST", f"/api/teams/{team['id']}/invites", {}, cookie)
        self.assertEqual(status, 201, invite)
        status, account2, cookie2 = call("POST", "/api/auth/register", {
            "name": "Test teammate", "email": f"member-{suffix}@example.org",
            "password": "Another-long-test-password!",
        })
        self.assertEqual(status, 201, account2)
        cookie2 = cookie2.split(";", 1)[0]
        status, joined, _ = call("POST", "/api/team-invites/" + invite["invite_url"].split("/")[-1] + "/join", {}, cookie2)
        self.assertEqual(status, 200, joined)
        status, draft, _ = call("POST", f"/api/events/{event_id}/projects", {
            "team_id": team["id"], "track_id": track_id, "title": "Project " + suffix,
            "summary": "A working test project", "status": "draft",
        }, cookie2)
        self.assertEqual(status, 201, draft)
        status, final, _ = call("PUT", f"/api/projects/{draft['id']}", {
            "title": "Project " + suffix, "summary": "Finished", "track_id": track_id,
            "status": "submitted",
        }, cookie)
        self.assertEqual(status, 200, final)
        self.assertEqual(final["status"], "submitted")
        status, workspace, _ = call("GET", f"/workspace/{event_id}", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn("Submission check", workspace)
        self.assertIn("Preview judge view", workspace)
        status, team_view, _ = call("GET", f"/api/events/{event_id}/my-team", cookie=cookie2)
        self.assertEqual(status, 200)
        self.assertEqual(len(team_view["members"]), 2)

    def test_fixture_deadline_and_roles(self):
        participant = "session=bb_demo_participant_2026_local_only"
        organizer = "session=bb_demo_organizer_2026_local_only"
        judge_a = "session=bb_demo_judge_a_2026_local_only"
        judge_b = "session=bb_demo_judge_b_2026_local_only"
        status, landing, _ = call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn('href="/events">Events', landing)
        self.assertIn('href="/account">Sign in', landing)
        self.assertIn('href="/projects?event=evt_01', landing)
        status, landing, _ = call("GET", "/", cookie=participant)
        self.assertEqual(status, 200)
        self.assertIn('href="/dashboard">Dashboard', landing)
        status, dashboard, _ = call("GET", "/dashboard", cookie=participant)
        self.assertEqual(status, 200)
        self.assertIn('data-setup-wizard', dashboard)
        self.assertIn('Review before creating', dashboard)
        status, _, _ = call("GET", "/admin?check=1", cookie=participant)
        self.assertEqual(status, 403)
        status, gallery, _ = call("GET", "/projects?page=9999")
        self.assertEqual(status, 200)
        self.assertIn("Showing 1–41 of 41 projects", gallery)
        self.assertIn("Glass Signal", gallery)
        status, filtered, _ = call("GET", "/projects?q=Glass%20Signal")
        self.assertEqual(status, 200)
        self.assertIn("Showing 1–1 of 1 project", filtered)
        status, _, _ = call("POST", "/api/events/evt_01/projects", {"title": "Late"}, participant)
        self.assertEqual(status, 409)
        status, _, _ = call("GET", "/api/judge/scores?judge=jdg_01", cookie=judge_b)
        self.assertEqual(status, 403)
        status, scores, _ = call("GET", "/api/judge/scores", cookie=judge_a)
        self.assertEqual(status, 200)
        self.assertEqual(scores["judge_id"], "jdg_01")
        status, _, _ = call("GET", "/api/judge/scores", cookie=participant)
        self.assertEqual(status, 403)
        status, insight, _ = call("GET", "/api/events/evt_01/judging-insight", cookie=organizer)
        self.assertEqual(status, 200)
        self.assertEqual(insight["coverage"]["total"], 40)
        self.assertTrue(any(row["title"] == "Iron Switch" and row["raw_rank"] == 2
                            and row["adjusted_rank"] == 1 for row in insight["movements"]))
        status, _, _ = call("GET", "/api/events/evt_01/judging-insight", cookie=judge_a)
        self.assertEqual(status, 403)
        status, organizer_page, _ = call("GET", "/organizer/evt_01?activity=Judging", cookie=organizer)
        self.assertEqual(status, 200)
        self.assertIn("Judging insight", organizer_page)
        self.assertIn("Activity log", organizer_page)


if __name__ == "__main__":
    unittest.main()
