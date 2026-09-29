"""Portable event exchange validates before writing and preserves primary data."""

import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from src.auth import Principal
from src.auth import verify_password
from src.db import connect, initialize
from src.portable_bundle import Bundle, export_portable, import_portable
from src.event_archive import export_event_archive, import_event_archive
from src.seed import seed


class PortableBundleTests(unittest.TestCase):
    def test_complete_archive_round_trip_preserves_historical_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(__file__).resolve().parents[1]
            source = Path(directory) / "source.sqlite3"
            target = Path(directory) / "target.sqlite3"
            request = Request({"type": "http", "method": "POST", "path": "/api/archive", "headers": []})
            organizer = Principal("org_demo", "organizer@beyondbug.local", "Organizer", False)
            with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(source),
                                         "DOGFOOD_FIXTURES_PATH": str(root / "fixtures.json"),
                                         "DOGFOOD_DEMO_MODE": "0"}):
                initialize()
                seed()
                with closing(connect()) as db:
                    voter = db.execute("SELECT user_id FROM event_roles WHERE event_id='evt_01'"
                                       " AND role='participant' LIMIT 1").fetchone()[0]
                    project = db.execute("SELECT id FROM projects WHERE event_id='evt_01'"
                                         " AND duplicate_of IS NULL LIMIT 1").fetchone()[0]
                    db.execute("INSERT INTO ballots(id,event_id,voter_user_id,project_id,cast_at)"
                               " VALUES('ballot_archive','evt_01',?,?,'2026-09-29T01:00:00Z')", (voter, project))
                    db.execute("INSERT INTO prizes(id,event_id,name,description)"
                               " VALUES('prize_archive','evt_01','Archive prize','Round-trip evidence')")
                    db.execute("INSERT INTO event_awards(prize_id,event_id,project_id,assigned_by,assigned_at)"
                               " VALUES('prize_archive','evt_01',?,'org_demo','2026-09-29T01:01:00Z')", (project,))
                    db.execute("INSERT INTO certificates(id,event_id,user_id,project_id,kind,prize_id,issued_at,design_json)"
                               " VALUES('cert_archive','evt_01',?,?,'winner','prize_archive','2026-09-29T01:02:00Z','{}')",
                               (voter, project))
                    db.execute("INSERT INTO audit_entries(event_id,actor_user_id,action,entity_type,entity_id,details_json,created_at)"
                               " VALUES('evt_01','org_demo','archive.test','event','evt_01','{}','2026-09-29T01:03:00Z')")
                    db.commit()
                with patch("src.event_archive.require_login", return_value=organizer):
                    archive = export_event_archive("evt_01", request)
                self.assertEqual(len(archive["tables"]["scorecards"]), 126)
                self.assertEqual(len(archive["tables"]["ballots"]), 1)
                self.assertEqual(len(archive["tables"]["certificates"]), 1)
            admin = Principal("install-admin", "admin@example.org", "Admin", True)
            with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(target), "DOGFOOD_DEMO_MODE": "0"}):
                initialize()
                with patch("src.event_archive.require_login", return_value=admin):
                    restored = import_event_archive(archive, request)
                self.assertEqual(restored["event_id"], "evt_01")
                with closing(connect()) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM projects WHERE event_id='evt_01'").fetchone()[0], 41)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM scorecards s JOIN judge_assignments a"
                                                " ON a.id=s.assignment_id WHERE a.event_id='evt_01'").fetchone()[0], 126)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM ballots WHERE event_id='evt_01'").fetchone()[0], 1)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM certificates WHERE event_id='evt_01'").fetchone()[0], 1)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_entries WHERE event_id='evt_01'").fetchone()[0],
                                     len(archive["tables"]["audit_entries"]))

    def test_fixture_bundle_keeps_all_forty_one_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(__file__).resolve().parents[1]
            with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(Path(directory) / "portal.sqlite3"),
                                         "DOGFOOD_FIXTURES_PATH": str(root / "fixtures.json"),
                                         "DOGFOOD_DEMO_MODE": "0"}):
                initialize()
                seed()
                with closing(connect()) as db:
                    db.execute("INSERT INTO events(id,name,submissions_close,created_by,created_at)"
                               " VALUES('target','Target','2026-10-10T00:00:00Z','org_demo','2026-09-29T00:00:00Z')")
                    db.execute("INSERT INTO event_roles(event_id,user_id,role) VALUES('target','org_demo','organizer')")
                    db.commit()
                request = Request({"type": "http", "method": "POST", "path": "/api/events/target/imports/portable.json", "headers": []})
                with patch("src.portable_bundle.require_login", return_value=Principal("org_demo", "organizer@beyondbug.local", "Organizer", False)):
                    bundle = Bundle.model_validate(export_portable("evt_01", request))
                    self.assertEqual(sum(len(team.projects) for team in bundle.teams), 41)
                    imported = import_portable("target", bundle, request, dry_run=False)
                self.assertEqual(imported["projects"], 41)
                with closing(connect()) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM projects WHERE event_id='target'").fetchone()[0], 41)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM teams WHERE event_id='target'").fetchone()[0], 40)

    def test_dry_run_and_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(Path(directory) / "portal.sqlite3")}):
                initialize()
                with closing(connect()) as db:
                    for user in ("org", "member", "judge", "outsider"):
                        db.execute("INSERT INTO users(id,email,name,created_at) VALUES(?,?,?,'2026-09-29T00:00:00Z')",
                                   (user, user + "@example.org", user))
                    for event in ("source", "target"):
                        db.execute("INSERT INTO events(id,name,submissions_close,created_by,created_at)"
                                   " VALUES(?,?,?,?,?)", (event, event.title(), "2026-10-10T00:00:00Z", "org", "2026-09-29T00:00:00Z"))
                        db.execute("INSERT INTO event_roles(event_id,user_id,role) VALUES(?,?,'organizer')", (event, "org"))
                    db.execute("INSERT INTO tracks(id,event_id,name) VALUES('track','source','Open')")
                    db.execute("INSERT INTO prizes(id,event_id,name) VALUES('prize','source','Grand prize')")
                    db.execute("INSERT INTO submission_questions(id,event_id,label,required,sort_order)"
                               " VALUES('question','source','What did you learn?',1,0)")
                    db.execute("INSERT INTO event_roles(event_id,user_id,role) VALUES('source','member','participant')")
                    db.execute("INSERT INTO event_roles(event_id,user_id,role) VALUES('source','judge','judge')")
                    db.execute("INSERT INTO teams(id,event_id,name,created_by,created_at)"
                               " VALUES('team','source','Team','member','2026-09-29T00:00:00Z')")
                    db.execute("INSERT INTO team_members(team_id,user_id,role,joined_at)"
                               " VALUES('team','member','captain','2026-09-29T00:00:00Z')")
                    db.execute("INSERT INTO projects(id,event_id,team_id,track_id,title,status,submitted_at,updated_at)"
                               " VALUES('project','source','team','track','Project','submitted','2026-09-29T00:00:00Z','2026-09-29T00:00:00Z')")
                    db.execute("INSERT INTO project_answers(project_id,question_id,answer)"
                               " VALUES('project','question','A careful answer')")
                    db.execute("INSERT INTO projects(id,event_id,team_id,track_id,title,status,submitted_at,updated_at)"
                               " VALUES('project2','source','team','track','Project two','submitted','2026-09-29T00:00:00Z','2026-09-29T00:00:00Z')")
                    db.execute("INSERT INTO project_answers(project_id,question_id,answer)"
                               " VALUES('project2','question','A second answer')")
                    db.execute("INSERT INTO judge_profiles(id,event_id,user_id,status)"
                               " VALUES('profile','source','judge','accepted')")
                    db.execute("INSERT INTO judge_tracks(judge_id,track_id) VALUES('profile','track')")
                    db.commit()
                request = Request({"type": "http", "method": "POST", "path": "/api/events/target/imports/portable.json", "headers": []})
                organizer = Principal("org", "org@example.org", "org", False)
                with patch("src.portable_bundle.require_login", return_value=organizer):
                    exported = export_portable("source", request)
                    self.assertEqual([project["answers"] for project in exported["teams"][0]["projects"]],
                                     [{"What did you learn?": "A careful answer"},
                                      {"What did you learn?": "A second answer"}])
                    exported["participants"].append({"name": "New participant", "email": "new@example.org"})
                    bundle = Bundle.model_validate(exported)
                    invalid = bundle.model_copy(deep=True)
                    invalid.teams[0].projects[0].track = "Missing track"
                    with self.assertRaises(HTTPException) as bad_bundle:
                        import_portable("target", invalid, request, dry_run=False)
                    self.assertEqual(bad_bundle.exception.status_code, 422)
                    preflight = import_portable("target", bundle, request, dry_run=True)
                    self.assertEqual(preflight["projects"], 2)
                    with closing(connect()) as db:
                        self.assertEqual(db.execute("SELECT COUNT(*) FROM teams WHERE event_id='target'").fetchone()[0], 0)
                    imported = import_portable("target", bundle, request, dry_run=False)
                    self.assertEqual(imported["projects"], 2)
                    self.assertEqual(len(imported["new_account_credentials"]), 1)
                    with closing(connect()) as db:
                        account = db.execute("SELECT password_hash FROM users WHERE email='new@example.org'").fetchone()
                    self.assertTrue(verify_password(imported["new_account_credentials"][0]["temporary_password"],
                                                    account["password_hash"]))
                    copy = export_portable("target", request)
                    self.assertEqual(sorted(project["answers"]["What did you learn?"]
                                            for project in copy["teams"][0]["projects"]),
                                     ["A careful answer", "A second answer"])
                    with self.assertRaises(HTTPException) as repeated:
                        import_portable("target", bundle, request, dry_run=False)
                    self.assertEqual(repeated.exception.status_code, 409)
                with patch("src.portable_bundle.require_login", return_value=Principal("outsider", "outsider@example.org", "outsider", False)):
                    with self.assertRaises(HTTPException) as denied:
                        export_portable("source", request)
                self.assertEqual(denied.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
