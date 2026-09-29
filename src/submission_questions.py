"""Event-specific submission questions and transactional answer validation."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import has_event_role, require_event_role, require_login
from .core import audit, time_value
from .db import connect


router = APIRouter(prefix="/api")


class QuestionInput(BaseModel):
    label: str = Field(min_length=3, max_length=200)
    required: bool = False


class QuestionsInput(BaseModel):
    questions: list[QuestionInput] = Field(max_length=10)


@router.get("/events/{event_id}/submission-questions")
def list_questions(event_id: str):
    with closing(connect()) as db:
        event = db.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        rows = db.execute("SELECT id,label,required,sort_order FROM submission_questions"
                          " WHERE event_id=? ORDER BY sort_order", (event_id,)).fetchall()
    return {"questions": [dict(row) for row in rows]}


@router.get("/events/{event_id}/projects/{project_id}/answers")
def project_answers(event_id: str, project_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        project = db.execute("SELECT team_id FROM projects WHERE id=? AND event_id=?", (project_id, event_id)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        permitted = has_event_role(db, principal, event_id, "organizer")
        if not permitted:
            permitted = db.execute("SELECT 1 FROM team_members WHERE team_id=? AND user_id=?",
                                   (project["team_id"], principal.user_id)).fetchone() is not None
        if not permitted:
            permitted = db.execute("SELECT 1 FROM judge_assignments a JOIN judge_profiles j ON j.id=a.judge_id"
                                   " WHERE a.project_id=? AND a.event_id=? AND j.user_id=?",
                                   (project_id, event_id, principal.user_id)).fetchone() is not None
        if not permitted:
            raise HTTPException(status_code=403, detail="Project answers are private to its team and assigned reviewers")
        rows = db.execute("SELECT q.id,q.label,q.required,a.answer FROM submission_questions q"
                          " LEFT JOIN project_answers a ON a.question_id=q.id AND a.project_id=?"
                          " WHERE q.event_id=? ORDER BY q.sort_order", (project_id, event_id)).fetchall()
    return {"answers": [dict(row) for row in rows]}


@router.put("/events/{event_id}/submission-questions")
def configure_questions(event_id: str, payload: QuestionsInput, request: Request):
    principal = require_login(request)
    labels = [question.label.strip() for question in payload.questions]
    if any(len(label) < 3 for label in labels) or len({label.casefold() for label in labels}) != len(labels):
        raise HTTPException(status_code=422, detail="Question labels must be unique and at least three characters")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        event = db.execute("SELECT submissions_close,results_published_at FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        if datetime.now(timezone.utc) >= time_value(event["submissions_close"]):
            raise HTTPException(status_code=409, detail="Submissions are closed; questions are locked")
        if event["results_published_at"] or db.execute("SELECT 1 FROM projects WHERE event_id=? LIMIT 1", (event_id,)).fetchone():
            raise HTTPException(status_code=409, detail="Questions lock after the first project draft")
        db.execute("DELETE FROM submission_questions WHERE event_id=?", (event_id,))
        rows = []
        for index, question in enumerate(payload.questions):
            question_id = "sq_" + uuid4().hex
            db.execute("INSERT INTO submission_questions(id,event_id,label,required,sort_order) VALUES(?,?,?,?,?)",
                       (question_id, event_id, labels[index], int(question.required), index))
            rows.append({"id": question_id, "label": labels[index], "required": question.required,
                         "sort_order": index})
        audit(db, event_id, principal.user_id, "submission_questions.configured", "event", event_id,
              {"count": len(rows)})
        db.commit()
    return {"questions": rows}


def validate_answers(db, event_id: str, project_id: str | None, answers: dict[str, str] | None,
                     status: str) -> dict[str, str]:
    questions = db.execute("SELECT id,required FROM submission_questions WHERE event_id=?", (event_id,)).fetchall()
    required = {row["id"] for row in questions if row["required"]}
    known = {row["id"] for row in questions}
    existing = {}
    if project_id:
        existing = {row["question_id"]: row["answer"] for row in db.execute(
            "SELECT question_id,answer FROM project_answers WHERE project_id=?", (project_id,))}
    if answers is None:
        answers = existing
    if set(answers) - known:
        raise HTTPException(status_code=422, detail="Unknown submission question")
    if any(not isinstance(value, str) or len(value) > 2000 for value in answers.values()):
        raise HTTPException(status_code=422, detail="Answers must be text of at most 2000 characters")
    cleaned = {key: value.strip() for key, value in answers.items()}
    if status == "submitted" and any(not cleaned.get(key) for key in required):
        raise HTTPException(status_code=422, detail="Answer every required submission question")
    return cleaned


def save_answers(db, project_id: str, answers: dict[str, str]) -> None:
    db.execute("DELETE FROM project_answers WHERE project_id=?", (project_id,))
    for question_id, answer in answers.items():
        if answer:
            db.execute("INSERT INTO project_answers(project_id,question_id,answer) VALUES(?,?,?)",
                       (project_id, question_id, answer))
