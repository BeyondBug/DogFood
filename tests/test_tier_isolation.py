"""Adversarial T2 check: a track judge cannot receive or score another track."""

import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from src.auth import Principal
from src.db import connect, initialize
from src.judging import BatchInput, ScorecardInput, batch_assign, own_assignments, save_scorecard


class TierIsolationTests(unittest.TestCase):
    def test_batch_and_scorecard_enforce_track_and_judge_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(Path(directory) / "portal.sqlite3")}):
                initialize()
                with closing(connect()) as db:
                    for user in ("org", "a", "b"):
                        db.execute("INSERT INTO users(id,email,name,created_at) VALUES(?,?,?,'2026-09-29T00:00:00Z')",
                                   (user, user + "@example.org", user))
                    db.execute("INSERT INTO events(id,name,submissions_close,created_at)"
                               " VALUES('event','Event','2026-09-28T00:00:00Z','2026-09-27T00:00:00Z')")
                    db.execute("INSERT INTO event_roles(event_id,user_id,role) VALUES('event','org','organizer')")
                    for judge in ("a", "b"):
                        db.execute("INSERT INTO event_roles(event_id,user_id,role) VALUES('event',?,'judge')", (judge,))
                    for track in ("track_a", "track_b"):
                        db.execute("INSERT INTO tracks(id,event_id,name) VALUES(?,'event',?)", (track, track))
                    for team, track, project in (("team_a", "track_a", "project_a"),
                                                 ("team_b", "track_b", "project_b")):
                        db.execute("INSERT INTO teams(id,event_id,name,created_at)"
                                   " VALUES(?,'event',?,'2026-09-27T00:00:00Z')", (team, team))
                        db.execute("INSERT INTO projects(id,event_id,team_id,track_id,title,status,updated_at)"
                                   " VALUES(?,'event',?,?,?,'submitted','2026-09-28T00:00:00Z')",
                                   (project, team, track, project))
                    for judge, track in (("a", "track_a"), ("b", "track_b")):
                        db.execute("INSERT INTO judge_profiles(id,event_id,user_id,status)"
                                   " VALUES(?,'event',?,'accepted')", (judge, judge))
                        db.execute("INSERT INTO judge_tracks(judge_id,track_id) VALUES(?,?)", (judge, track))
                    db.execute("INSERT INTO rubrics(id,event_id,version,name,created_at)"
                               " VALUES('rubric','event',1,'Rubric','2026-09-27T00:00:00Z')")
                    db.commit()
                request = Request({"type": "http", "method": "POST", "path": "/api/events/event/assignments/batch", "headers": []})
                with patch("src.judging.require_login", return_value=Principal("org", "org@example.org", "org", False)):
                    result = batch_assign("event", BatchInput(reviews_per_project=1), request)
                self.assertEqual(len(result["created"]), 2)
                self.assertEqual(result["shortages"], [])
                with closing(connect()) as db:
                    pairs = {(row["project_id"], row["judge_id"]) for row in db.execute(
                        "SELECT project_id,judge_id FROM judge_assignments WHERE event_id='event'")}
                self.assertEqual(pairs, {("project_a", "a"), ("project_b", "b")})
                with patch("src.judging.require_login", return_value=Principal("a", "a@example.org", "a", False)):
                    queue = own_assignments(request, "event")
                    self.assertEqual([item["project_id"] for item in queue["assignments"]], ["project_a"])
                    foreign_assignment = next(item["assignment_id"] for item in result["created"]
                                              if item["project_id"] == "project_b")
                    with self.assertRaises(HTTPException) as denied:
                        save_scorecard(foreign_assignment, ScorecardInput(criteria={}, status="draft"), request)
                self.assertEqual(denied.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
