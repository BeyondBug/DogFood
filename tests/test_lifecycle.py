"""HTTP integration tests run only against scripts/test_fresh.py's disposable portal."""

import json
import os
import unittest
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


BASE = os.getenv("DOGFOOD_TEST_URL", "").rstrip("/")


def call(method, path, body=None, cookie=None):
    if not BASE or BASE.rstrip("/").lower() in {"http://localhost:8080", "http://127.0.0.1:8080"}:
        raise RuntimeError(
            "HTTP integration tests require a disposable portal. "
            "Run python3 scripts/test_fresh.py instead of testing localhost:8080."
        )
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


def creator_cookie():
    status, _, cookie = call("POST", "/api/auth/login", {
        "email": "integration-admin@beyondbug.local", "password": "DisposableTestAdmin2026!",
    })
    if status != 200:
        raise AssertionError(f"Disposable admin login failed: {status}")
    return cookie.split(";", 1)[0]


class LifecycleTests(unittest.TestCase):
    def test_participant_dashboard_tracks_event_team_and_submission(self):
        suffix = uuid.uuid4().hex[:10]
        status, event, _ = call("POST", "/api/events", {
            "name": f"Progress {suffix}", "submissions_close":
            (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(), "tracks": ["Software"],
        }, creator_cookie())
        self.assertEqual(status, 201, event)
        event_id = event["id"]
        track_id = call("GET", f"/api/events/{event_id}")[1]["tracks"][0]["id"]
        status, _, cookie = call("POST", "/api/auth/register", {
            "name": "Progress participant", "email": f"progress-{suffix}@example.org",
            "password": "A-long-local-test-password!",
        })
        self.assertEqual(status, 201)
        cookie = cookie.split(";", 1)[0]
        self.assertEqual(call("POST", f"/api/events/{event_id}/registration", {}, cookie)[0], 201)
        dashboard = call("GET", "/dashboard", cookie=cookie)[1]
        self.assertIn("Team: not formed", dashboard)
        self.assertIn("Submissions open", dashboard)
        self.assertIn("Create team", dashboard)
        self.assertIn('href="/my/certificates"', dashboard)
        status, team, _ = call("POST", f"/api/events/{event_id}/teams", {"name": "Progress team"}, cookie)
        self.assertEqual(status, 201)
        dashboard = call("GET", "/dashboard", cookie=cookie)[1]
        self.assertIn("Team: Progress team", dashboard)
        self.assertIn("Team members: 1", dashboard)
        self.assertIn("Start submission", dashboard)
        status, project, _ = call("POST", f"/api/events/{event_id}/projects", {
            "team_id": team["id"], "track_id": track_id, "title": "Progress project", "status": "draft",
        }, cookie)
        self.assertEqual(status, 201, project)
        dashboard = call("GET", "/dashboard", cookie=cookie)[1]
        self.assertIn("Project: Progress project (draft, Software)", dashboard)
        self.assertIn("Continue draft", dashboard)

    def test_admin_provisions_judge_and_judge_changes_password(self):
        suffix = uuid.uuid4().hex[:10]
        track_id = call("GET", "/api/events/evt_01")[1]["tracks"][0]["id"]
        status, _, participant = call("POST", "/api/auth/register", {
            "name": "Cannot provision", "email": f"nonadmin-{suffix}@example.org",
            "password": "A-long-local-test-password!",
        })
        self.assertEqual(status, 201)
        participant = participant.split(";", 1)[0]
        payload = {"name": "Provisioned judge", "email": f"judge-{suffix}@example.org", "tracks": [track_id]}
        self.assertEqual(call("POST", "/api/admin/events/evt_01/judges", payload, participant)[0], 403)
        self.assertEqual(call("POST", "/api/admin/events/evt_01/judges", {
            **payload, "tracks": ["trk_wrong_event"],
        }, creator_cookie())[0], 422)
        status, created, _ = call("POST", "/api/admin/events/evt_01/judges", payload, creator_cookie())
        self.assertEqual(status, 201, created)
        self.assertGreaterEqual(len(created["temporary_password"]), 20)
        self.assertEqual(call("POST", "/api/admin/events/evt_01/judges", payload, creator_cookie())[0], 409)
        status, _, judge = call("POST", "/api/auth/login", {
            "email": payload["email"], "password": created["temporary_password"],
        })
        self.assertEqual(status, 200)
        judge = judge.split(";", 1)[0]
        dashboard = call("GET", "/dashboard", cookie=judge)[1]
        self.assertIn("Reviews: 0 of 0 submitted", dashboard)
        self.assertIn(f'href="/judge/evt_01"', dashboard)
        self.assertNotIn('href="/my/certificates"', dashboard)
        self.assertNotIn('data-action="create-event"', dashboard)
        self.assertNotIn('href="/admin"', dashboard)
        self.assertEqual(call("GET", "/judge/evt_01", cookie=judge)[0], 200)
        self.assertEqual(call("GET", "/api/events/evt_01/ml-review-signals", cookie=judge)[0], 403)
        self.assertEqual(call("GET", "/api/judge/assignments?event_id=evt_01", cookie=judge)[0], 200)
        self.assertEqual(call("POST", "/api/auth/password", {
            "current_password": "wrong-password", "new_password": "ChangedJudgePassword2026!",
        }, judge)[0], 403)
        self.assertEqual(call("POST", "/api/auth/password", {
            "current_password": created["temporary_password"], "new_password": "ChangedJudgePassword2026!",
        }, judge)[0], 204)
        self.assertEqual(call("GET", "/api/auth/me", cookie=judge)[0], 401)
        self.assertEqual(call("POST", "/api/auth/login", {
            "email": payload["email"], "password": created["temporary_password"],
        })[0], 401)
        self.assertEqual(call("POST", "/api/auth/login", {
            "email": payload["email"], "password": "ChangedJudgePassword2026!",
        })[0], 200)

    def test_header_sign_out_revokes_session(self):
        suffix = uuid.uuid4().hex[:10]
        status, _, cookie = call("POST", "/api/auth/register", {
            "name": "Menu tester", "email": f"menu-{suffix}@example.org",
            "password": "A-long-local-test-password!",
        })
        self.assertEqual(status, 201)
        cookie = cookie.split(";", 1)[0]
        status, gallery, _ = call("GET", "/projects", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn('class="account-menu"', gallery)
        self.assertIn('href="/dashboard">Dashboard', gallery)
        self.assertIn('data-action="logout"', gallery)
        status, dashboard, _ = call("GET", "/dashboard", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertNotIn('data-action="create-event"', dashboard)
        self.assertNotIn('href="/my/certificates"', dashboard)
        self.assertNotIn('href="/admin"', dashboard)
        self.assertEqual(call("POST", "/api/events", {
            "name": "Forbidden event", "submissions_close": "2026-12-31T18:00:00Z",
            "tracks": ["Software"],
        }, cookie)[0], 403)
        status, _, organizer_session = call("POST", "/api/auth/login", {
            "email": "organizer@beyondbug.local", "password": "BeyondBugDemo2026!",
        })
        self.assertEqual(status, 200)
        organizer_session = organizer_session.split(";", 1)[0]
        status, organizer_dashboard, _ = call("GET", "/dashboard", cookie=organizer_session)
        self.assertEqual(status, 200)
        self.assertNotIn('data-action="create-event"', organizer_dashboard)
        self.assertNotIn('href="/admin"', organizer_dashboard)
        self.assertEqual(call("POST", "/api/events", {
            "name": "Organizer cannot create", "submissions_close": "2026-12-31T18:00:00Z",
            "tracks": ["Software"],
        }, organizer_session)[0], 403)
        admin = creator_cookie()
        admin_dashboard = call("GET", "/dashboard", cookie=admin)[1]
        self.assertIn('data-action="create-event"', admin_dashboard)
        self.assertIn('href="/admin"', admin_dashboard)
        status, _, _ = call("POST", "/api/auth/logout", cookie=cookie)
        self.assertEqual(status, 204)
        self.assertEqual(call("GET", "/api/auth/me", cookie=cookie)[0], 401)

    def test_http_helper_refuses_the_default_portal(self):
        for address in ("", "http://localhost:8080", "http://127.0.0.1:8080/"):
            with self.subTest(address=address), patch(__name__ + ".BASE", address):
                with self.assertRaisesRegex(RuntimeError, "disposable portal"):
                    call("GET", "/health")

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
            if status == 429:
                self.skipTest("The shared test portal's IP throttle is already full; run scripts/test_fresh.py")
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
        status, body, _ = call("POST", "/api/auth/login", {
            "email": other_email, "password": password,
        })
        if status == 429:
            self.skipTest("The shared test portal's IP throttle is already full; run scripts/test_fresh.py")
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
        }, creator_cookie())
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
        }, creator_cookie())
        self.assertEqual(status, 200)
        status, _, _ = call("PATCH", f"/api/events/{event_id}", {
            "submissions_close": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        }, creator_cookie())
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
        }, creator_cookie())
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
        organizer_cookie = creator_cookie()
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
        status, _, admin_cookie = call("POST", "/api/auth/login", {
            "email": "integration-admin@beyondbug.local", "password": "DisposableTestAdmin2026!",
        })
        self.assertEqual(status, 200)
        admin_cookie = admin_cookie.split(";", 1)[0]
        for kind, design in (
            ("participant", {"layout": "modern", "palette": "coral", "issuer_line": "BeyondBug Test"}),
            ("winner", {"layout": "bold", "palette": "violet", "issuer_line": "BeyondBug Awards"}),
        ):
            status, saved, _ = call("PUT", f"/api/admin/events/{event_id}/certificate-designs/{kind}",
                                    design, admin_cookie)
            self.assertEqual(status, 200, saved)
            self.assertEqual(saved["design"], design)
            preview_path = f"/events/{event_id}/certificates/preview/{kind}.svg"
            status, preview, _ = call("GET", preview_path, cookie=admin_cookie)
            self.assertEqual(status, 200)
            self.assertIn(design["issuer_line"] + " / TEMPLATE PREVIEW", preview)
        self.assertEqual(call("PUT", f"/api/admin/events/{event_id}/certificate-designs/winner", {
            "layout": "classic", "palette": "gold", "issuer_line": "No access",
        }, judge_cookie)[0], 403)
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
        self.assertEqual(participant_record["recipient"], "Local administrator")
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
        self.assertIn("BeyondBug Awards / OFFICIAL RECORD", art)
        self.assertIn('stroke-width="7"', art)
        status, participant_art, _ = call("GET", f"/certificates/{participant_id}.svg")
        self.assertEqual(status, 200)
        self.assertIn("BeyondBug Test / OFFICIAL RECORD", participant_art)
        status, _, _ = call("PUT", f"/api/admin/events/{event_id}/certificate-designs/winner", {
            "layout": "classic", "palette": "gold", "issuer_line": "Changed later",
        }, admin_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(call("GET", f"/certificates/{winner_id}.svg")[1], art)
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
        cookie = creator_cookie()
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

    def test_duplicate_flag_ignores_drafts_and_follows_current_repo(self):
        suffix = uuid.uuid4().hex[:10]

        def account(label):
            status, body, cookie = call("POST", "/api/auth/register", {
                "name": label, "email": f"duplicate-{label.lower()}-{suffix}@example.org",
                "password": "A-long-local-test-password!",
            })
            self.assertEqual(status, 201, body)
            return cookie.split(";", 1)[0]

        first = account("First")
        second = account("Second")
        status, event, _ = call("POST", "/api/events", {
            "name": f"Duplicate review {suffix}",
            "submissions_close": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            "tracks": ["Software"],
        }, creator_cookie())
        self.assertEqual(status, 201, event)
        event_id = event["id"]
        track_id = call("GET", f"/api/events/{event_id}")[1]["tracks"][0]["id"]

        def team(cookie, name):
            self.assertEqual(call("POST", f"/api/events/{event_id}/registration", {}, cookie)[0], 201)
            status, result, _ = call("POST", f"/api/events/{event_id}/teams", {"name": name}, cookie)
            self.assertEqual(status, 201, result)
            return result["id"]

        first_team = team(first, "First team")
        second_team = team(second, "Second team")
        shared_repo = "https://example.org/shared-repository"
        status, draft, _ = call("POST", f"/api/events/{event_id}/projects", {
            "team_id": first_team, "track_id": track_id, "title": "Draft candidate",
            "repo_url": shared_repo, "status": "draft",
        }, first)
        self.assertEqual(status, 201, draft)
        status, submitted, _ = call("POST", f"/api/events/{event_id}/projects", {
            "team_id": second_team, "track_id": track_id, "title": "Submitted candidate",
            "repo_url": shared_repo, "status": "submitted",
        }, second)
        self.assertEqual(status, 201, submitted)

        def ranked_projects():
            status, result, _ = call("GET", f"/api/events/{event_id}/rankings", cookie=creator_cookie())
            self.assertEqual(status, 200, result)
            return {row["id"]: row for row in result["projects"]}

        self.assertIsNone(ranked_projects()[submitted["id"]]["duplicate_of"])
        status, _, _ = call("PUT", f"/api/projects/{draft['id']}", {
            "title": "Draft candidate", "track_id": track_id,
            "repo_url": shared_repo, "status": "submitted",
        }, first)
        self.assertEqual(status, 200)
        rows = ranked_projects()
        self.assertEqual(rows[draft["id"]]["duplicate_of"], submitted["id"])
        self.assertIsNone(rows[submitted["id"]]["duplicate_of"])
        status, _, _ = call("PUT", f"/api/projects/{submitted['id']}", {
            "title": "Submitted candidate", "track_id": track_id,
            "repo_url": "https://example.org/independent-repository", "status": "submitted",
        }, second)
        self.assertEqual(status, 200)
        rows = ranked_projects()
        self.assertIsNone(rows[draft["id"]]["duplicate_of"])
        self.assertIsNone(rows[submitted["id"]]["duplicate_of"])

    def test_fixture_deadline_and_roles(self):
        participant = "session=bb_demo_participant_2026_local_only"
        organizer = "session=bb_demo_organizer_2026_local_only"
        judge_a = "session=bb_demo_judge_a_2026_local_only"
        judge_b = "session=bb_demo_judge_b_2026_local_only"
        status, landing, _ = call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn('href="/events">Events', landing)
        self.assertIn('href="/account">Sign in', landing)
        self.assertIn('data-style-choice="studio"', landing)
        self.assertIn('data-style-choice="pulse"', landing)
        self.assertIn('href="/projects?event=evt_01', landing)
        status, landing, _ = call("GET", "/", cookie=participant)
        self.assertEqual(status, 200)
        self.assertIn('href="/dashboard">Dashboard', landing)
        status, dashboard, _ = call("GET", "/dashboard", cookie=participant)
        self.assertEqual(status, 200)
        self.assertNotIn('data-setup-wizard', dashboard)
        self.assertIn('Browse events', dashboard)
        status, _, _ = call("GET", "/admin?check=1", cookie=participant)
        self.assertEqual(status, 403)
        status, _, _ = call("POST", "/api/admin/backups", cookie=participant)
        self.assertEqual(status, 403)
        status, _, _ = call("GET", "/api/admin/backups/backup-20260927T000000Z-000000000000.sqlite3", cookie=participant)
        self.assertEqual(status, 403)
        status, event_page, _ = call("GET", "/events/evt_01")
        self.assertEqual(status, 200)
        self.assertIn('data-back-link href="/events"', event_page)
        status, gallery, _ = call("GET", "/projects?page=9999")
        self.assertEqual(status, 200)
        self.assertIn('data-back-link href="/events/evt_01"', gallery)
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
        self.assertIn("rule", insight["attention"])
        self.assertGreater(len(insight["attention"]["items"]), 0)
        candidate = insight["attention"]["items"][0]
        self.assertGreaterEqual(candidate["peer_count"], 2)
        scorecard_path = f"/api/events/evt_01/scorecards/{candidate['scorecard_id']}"
        page_path = f"/organizer/evt_01/reviews/{candidate['scorecard_id']}"
        status, review, _ = call("GET", scorecard_path, cookie=organizer)
        self.assertEqual(status, 200)
        self.assertEqual(review["project_title"], candidate["project"])
        self.assertTrue(review["criteria"])
        status, page, _ = call("GET", page_path, cookie=organizer)
        self.assertEqual(status, 200)
        self.assertIn(review["project_title"], page)
        self.assertIn("Criterion scores", page)
        for denied in (judge_a, participant):
            self.assertEqual(call("GET", scorecard_path, cookie=denied)[0], 403)
            self.assertEqual(call("GET", page_path, cookie=denied)[0], 403)
        status, _, _ = call("GET", "/api/events/evt_01/judging-insight", cookie=judge_a)
        self.assertEqual(status, 403)
        status, organizer_page, _ = call("GET", "/organizer/evt_01?activity=Judging", cookie=organizer)
        self.assertEqual(status, 200)
        self.assertIn("Judging insight", organizer_page)
        self.assertIn("Activity log", organizer_page)
        self.assertIn("Model-assisted review", organizer_page)
        self.assertIn("trained on synthetic events", organizer_page)
        self.assertEqual(call("GET", "/organizer/evt_01", cookie=judge_a)[0], 403)
        status, _, admin_cookie = call("POST", "/api/auth/login", {
            "email": "integration-admin@beyondbug.local", "password": "DisposableTestAdmin2026!",
        })
        self.assertEqual(status, 200)
        admin_cookie = admin_cookie.split(";", 1)[0]
        self.assertEqual(call("GET", "/admin/certificates?event_id=evt_01", cookie=organizer)[0], 403)
        self.assertEqual(call("PUT", "/api/admin/events/evt_01/certificate-designs/winner", {
            "layout": "modern", "palette": "gold", "issuer_line": "BeyondBug",
        }, organizer)[0], 403)
        status, studio, _ = call("GET", "/admin/certificates?event_id=evt_01", cookie=admin_cookie)
        self.assertEqual(status, 200)
        self.assertIn("Participation certificate", studio)
        self.assertIn("Winner certificate", studio)
        status, before, _ = call("GET", "/api/events/evt_01/certificates", cookie=organizer)
        self.assertEqual(status, 200)
        for kind in ("participant", "winner"):
            preview_path = f"/events/evt_01/certificates/preview/{kind}.svg"
            status, art, _ = call("GET", preview_path, cookie=admin_cookie)
            self.assertEqual(status, 200)
            self.assertIn("SAMPLE TEMPLATE · NOT A CERTIFICATE", art)
            self.assertIn("BEYONDBUG / TEMPLATE PREVIEW", art)
            self.assertIn("Sample Hack 2026", art)
            self.assertIn("NO VERIFICATION CODE", art)
            for denied in (judge_a, participant, organizer):
                self.assertEqual(call("GET", preview_path, cookie=denied)[0], 403)
        status, after, _ = call("GET", "/api/events/evt_01/certificates", cookie=organizer)
        self.assertEqual(status, 200)
        self.assertEqual(after, before)
        status, model_signals, _ = call("GET", "/api/events/evt_01/ml-review-signals", cookie=organizer)
        self.assertEqual(status, 200)
        self.assertEqual(model_signals["version"], "judge-anomaly-iforest-v2")
        self.assertGreater(model_signals["evaluated"], 0)
        for denied in (judge_a, participant):
            self.assertEqual(call("GET", "/api/events/evt_01/ml-review-signals", cookie=denied)[0], 403)


if __name__ == "__main__":
    unittest.main()
