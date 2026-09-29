"""A signed judge record can be verified outside the database and detects edits."""

import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

from src.auth import Principal
from src.db import connect, initialize
from src.judge_records import (_ensure_key, _public_key, _sign, issue_judge_records,
                               verify_judge_record, verify_signature)


class JudgeRecordTests(unittest.TestCase):
    def test_published_event_issues_one_immutable_record_per_reviewing_judge(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(Path(directory) / "portal.sqlite3")}):
                initialize()
                with closing(connect()) as db:
                    db.execute("INSERT INTO users(id,email,name,created_at) VALUES('org','org@example.org','Organizer','2026-09-29T00:00:00Z')")
                    db.execute("INSERT INTO users(id,email,name,created_at) VALUES('judge','judge@example.org','Judge','2026-09-29T00:00:00Z')")
                    db.execute("INSERT INTO events(id,name,submissions_close,results_published_at,created_at) VALUES('event','Event','2026-09-28T00:00:00Z','2026-09-29T00:00:00Z','2026-09-27T00:00:00Z')")
                    db.execute("INSERT INTO event_roles(event_id,user_id,role) VALUES('event','org','organizer')")
                    db.execute("INSERT INTO tracks(id,event_id,name) VALUES('track','event','Open')")
                    db.execute("INSERT INTO teams(id,event_id,name,created_at) VALUES('team','event','Team','2026-09-27T00:00:00Z')")
                    db.execute("INSERT INTO projects(id,event_id,team_id,track_id,title,status,updated_at) VALUES('project','event','team','track','Project','submitted','2026-09-28T00:00:00Z')")
                    db.execute("INSERT INTO judge_profiles(id,event_id,user_id) VALUES('profile','event','judge')")
                    db.execute("INSERT INTO rubrics(id,event_id,version,name,created_at) VALUES('rubric','event',1,'Rubric','2026-09-27T00:00:00Z')")
                    db.execute("INSERT INTO judge_assignments(id,event_id,project_id,judge_id,assigned_at) VALUES('assignment','event','project','profile','2026-09-28T00:00:00Z')")
                    db.execute("INSERT INTO scorecards(id,assignment_id,rubric_id,status,updated_at) VALUES('card','assignment','rubric','submitted','2026-09-29T00:00:00Z')")
                    db.commit()
                request = Request({"type": "http", "method": "POST", "path": "/api/events/event/judge-records/issue", "headers": []})
                with patch("src.judge_records.require_login", return_value=Principal("org", "org@example.org", "Organizer", False)):
                    first = issue_judge_records("event", request)
                    second = issue_judge_records("event", request)
                self.assertEqual(first["count"], 1)
                self.assertEqual(second["count"], 0)
                record = verify_judge_record(first["issued"][0])
                self.assertTrue(record["verified"])
                self.assertEqual(record["payload"]["completed_reviews"], 1)

    def test_ed25519_signature_detects_payload_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(Path(directory) / "portal.sqlite3")}):
                key = _ensure_key()
                self.assertEqual(key.stat().st_mode & 0o777, 0o600)
                self.assertEqual(_ensure_key(), key)
                payload = '{"completed_reviews":3,"judge":"Ada"}'
                public_key = _public_key(key)
                signature = _sign(payload.encode(), key)
                self.assertTrue(verify_signature(payload, signature, public_key))
                self.assertFalse(verify_signature(payload.replace("3", "4"), signature, public_key))
                self.assertFalse(verify_signature(payload, "invalid", public_key))


if __name__ == "__main__":
    unittest.main()
