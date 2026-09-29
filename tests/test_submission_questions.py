"""Submission questions remain event-scoped and required only at final submit."""

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
from src.main import ProjectInput, create_project
from src.core import ProjectUpdate, update_project
from src.submission_questions import (QuestionInput, QuestionsInput, configure_questions,
                                      project_answers, validate_answers)


class SubmissionQuestionTests(unittest.TestCase):
    def test_required_answer_draft_lock_and_private_read(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(Path(directory) / "portal.sqlite3")}):
                initialize()
                with closing(connect()) as db:
                    for user in ("org", "member", "outsider"):
                        db.execute("INSERT INTO users(id,email,name,created_at) VALUES(?,?,?,'2026-09-29T00:00:00Z')",
                                   (user, user + "@example.org", user))
                    db.execute("INSERT INTO events(id,name,submissions_close,created_at) VALUES('event','Event','2026-10-01T00:00:00Z','2026-09-29T00:00:00Z')")
                    db.execute("INSERT INTO event_roles(event_id,user_id,role) VALUES('event','org','organizer')")
                    db.execute("INSERT INTO event_roles(event_id,user_id,role) VALUES('event','member','participant')")
                    db.execute("INSERT INTO tracks(id,event_id,name) VALUES('track','event','Open')")
                    db.execute("INSERT INTO teams(id,event_id,name,created_at) VALUES('team','event','Team','2026-09-29T00:00:00Z')")
                    db.execute("INSERT INTO team_members(team_id,user_id,role,joined_at) VALUES('team','member','captain','2026-09-29T00:00:00Z')")
                    db.commit()
                request = Request({"type": "http", "method": "PUT", "path": "/api/events/event/submission-questions", "headers": []})
                with patch("src.submission_questions.require_login", return_value=Principal("org", "org@example.org", "org", False)):
                    configured = configure_questions("event", QuestionsInput(questions=[
                        QuestionInput(label="What problem do you solve?", required=True)]), request)
                question_id = configured["questions"][0]["id"]
                with closing(connect()) as db:
                    self.assertEqual(validate_answers(db, "event", None, {}, "draft"), {})
                    with self.assertRaises(HTTPException) as missing:
                        validate_answers(db, "event", None, {}, "submitted")
                    self.assertEqual(missing.exception.status_code, 422)
                    with self.assertRaises(HTTPException):
                        validate_answers(db, "event", None, {"other": "answer"}, "submitted")
                with patch("src.main.require_login", return_value=Principal("member", "member@example.org", "member", False)):
                    with self.assertRaises(HTTPException) as no_answer:
                        create_project("event", ProjectInput(team_id="team", track_id="track", title="Project",
                                                             status="submitted", answers={}), request)
                    self.assertEqual(no_answer.exception.status_code, 422)
                    created = create_project("event", ProjectInput(team_id="team", track_id="track", title="Project",
                                                                     status="draft"), request)
                project_id = created["id"]
                with patch("src.core.require_login", return_value=Principal("member", "member@example.org", "member", False)):
                    update_project(project_id, ProjectUpdate(title="Project", track_id="track", status="submitted",
                                                             answers={question_id: "  A clear answer  "}), request)
                with patch("src.submission_questions.require_login", return_value=Principal("member", "member@example.org", "member", False)):
                    result = project_answers("event", project_id, request)
                self.assertEqual(result["answers"][0]["answer"], "A clear answer")
                with patch("src.submission_questions.require_login", return_value=Principal("outsider", "outsider@example.org", "outsider", False)):
                    with self.assertRaises(HTTPException) as denied:
                        project_answers("event", project_id, request)
                self.assertEqual(denied.exception.status_code, 403)
                with patch("src.submission_questions.require_login", return_value=Principal("org", "org@example.org", "org", False)):
                    with self.assertRaises(HTTPException) as locked:
                        configure_questions("event", QuestionsInput(questions=[]), request)
                self.assertEqual(locked.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
