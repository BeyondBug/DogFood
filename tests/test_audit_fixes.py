"""Regression tests for review-found defects (duplicate judge accept, bearer logout, organizer peer read)."""

import unittest
import uuid

from test_lifecycle import call, creator_cookie


def register(prefix):
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@example.org"
    status, _, cookie = call("POST", "/api/auth/register", {
        "name": prefix.title(), "email": email, "password": "RegressionPass2026!",
    })
    assert status == 201, status
    return email, cookie.split(";", 1)[0]


def new_event(admin):
    status, event, _ = call("POST", "/api/events", {
        "name": f"Regression {uuid.uuid4().hex[:6]}",
        "submissions_close": "2030-01-01T00:00:00+00:00", "tracks": ["Main"],
    }, admin)
    assert status == 201, status
    return event["id"]


class AuditFixTests(unittest.TestCase):
    def test_second_judge_invite_for_same_account_is_conflict_not_500(self):
        admin = creator_cookie()
        event_id = new_event(admin)
        email, judge = register("judge")
        for expected in (200, 409):
            _, invite, _ = call("POST", f"/api/events/{event_id}/judges/invites", {"email": email}, admin)
            token = invite["invite_url"].rsplit("/", 1)[-1]
            status, _, _ = call("POST", f"/api/judge-invites/{token}/accept", cookie=judge)
            self.assertEqual(status, expected)

    def test_logout_revokes_session(self):
        _, session = register("logout")
        self.assertEqual(call("GET", "/api/auth/me", cookie=session)[0], 200)
        self.assertEqual(call("POST", "/api/auth/logout", cookie=session)[0], 204)
        self.assertEqual(call("GET", "/api/auth/me", cookie=session)[0], 401)

    def test_organizer_may_read_judge_scores_but_other_judge_may_not(self):
        admin = creator_cookie()
        event_id = new_event(admin)
        emails = []
        sessions = []
        for _ in range(2):
            email, session = register("judge")
            _, invite, _ = call("POST", f"/api/events/{event_id}/judges/invites", {"email": email}, admin)
            token = invite["invite_url"].rsplit("/", 1)[-1]
            call("POST", f"/api/judge-invites/{token}/accept", cookie=session)
            emails.append(email)
            sessions.append(session)
        first = call("GET", "/api/judge/scores", cookie=sessions[0])[1]["judge_id"]
        second = call("GET", "/api/judge/scores", cookie=sessions[1])[1]["judge_id"]
        self.assertEqual(call("GET", f"/api/judge/scores?judge={first}", cookie=sessions[1])[0], 403)
        self.assertEqual(call("GET", f"/api/judge/scores?judge={second}", cookie=admin)[0], 200)


if __name__ == "__main__":
    unittest.main()
