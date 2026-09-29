"""Portable pre-judging event exchange; full historical state uses SQLite backup."""

from __future__ import annotations

import secrets
from contextlib import closing
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .auth import hash_password, require_event_role, require_login
from .core import audit, identifier, reconcile_submitted_duplicates, require_web_url, time_value
from .db import connect, utc_now


router = APIRouter(prefix="/api")
FORMAT = "beyondbug-event-starter-v1"


class Person(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)


class Prompt(BaseModel):
    label: str = Field(min_length=3, max_length=200)
    required: bool = False


class Prize(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)


class Project(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=800)
    description: str = Field(default="", max_length=5000)
    repo_url: str = Field(default="", max_length=1000)
    demo_url: str = Field(default="", max_length=1000)
    live_url: str = Field(default="", max_length=1000)
    video_url: str = Field(default="", max_length=1000)
    thumbnail_url: str = Field(default="", max_length=1000)
    image_urls: str = Field(default="", max_length=5000)
    tech_tags: str = Field(default="", max_length=500)
    track: str
    status: str = "draft"
    submitted_at: str | None = None
    answers: dict[str, str] = Field(default_factory=dict)


class Team(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    members: list[str] = Field(min_length=1, max_length=4)
    projects: list[Project] = Field(default_factory=list, max_length=5)


class Judge(Person):
    tracks: list[str] = Field(default_factory=list, max_length=100)


class Bundle(BaseModel):
    format: str
    event: dict = Field(default_factory=dict)
    tracks: list[str] = Field(min_length=1, max_length=100)
    prizes: list[Prize] = Field(default_factory=list, max_length=100)
    questions: list[Prompt] = Field(default_factory=list, max_length=10)
    participants: list[Person] = Field(default_factory=list, max_length=2000)
    teams: list[Team] = Field(default_factory=list, max_length=500)
    judges: list[Judge] = Field(default_factory=list, max_length=200)


def _email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or email.count("@") != 1 or any(char.isspace() for char in email):
        raise HTTPException(status_code=422, detail=f"Invalid account email: {value}")
    local, domain = email.split("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise HTTPException(status_code=422, detail=f"Invalid account email: {value}")
    return email


def _unique(values: list[str], description: str) -> None:
    if len(values) != len({value.casefold() for value in values}):
        raise HTTPException(status_code=422, detail=f"Duplicate {description}")


def _validate(bundle: Bundle, deadline: str) -> dict:
    if bundle.format != FORMAT:
        raise HTTPException(status_code=422, detail="Unsupported portable bundle format")
    tracks = [name.strip() for name in bundle.tracks]
    if any(not name or len(name) > 160 for name in tracks):
        raise HTTPException(status_code=422, detail="Invalid track name")
    _unique(tracks, "track names")
    _unique([prize.name.strip() for prize in bundle.prizes], "prize names")
    if any(not prize.name.strip() for prize in bundle.prizes):
        raise HTTPException(status_code=422, detail="Invalid prize name")
    _unique([question.label.strip() for question in bundle.questions], "question labels")
    participants = {_email(person.email): person for person in bundle.participants}
    if len(participants) != len(bundle.participants):
        raise HTTPException(status_code=422, detail="Duplicate participant email")
    if any(len(person.name.strip()) < 2 for person in [*bundle.participants, *bundle.judges]):
        raise HTTPException(status_code=422, detail="Imported account names must contain at least two characters")
    _unique([_email(judge.email) for judge in bundle.judges], "judge emails")
    track_names = {name.casefold() for name in tracks}
    question_labels = {question.label.strip() for question in bundle.questions}
    required_labels = {question.label.strip() for question in bundle.questions if question.required}
    seen_members = set()
    for judge in bundle.judges:
        _unique([name.strip() for name in judge.tracks], "judge tracks")
        if any(name.casefold() not in track_names for name in judge.tracks):
            raise HTTPException(status_code=422, detail="Judge has an unknown track")
    for team in bundle.teams:
        if len(team.name.strip()) < 2:
            raise HTTPException(status_code=422, detail="Team names must contain at least two characters")
        members = [_email(value) for value in team.members]
        if len(members) != len(set(members)):
            raise HTTPException(status_code=422, detail="A team repeats a member")
        if any(member not in participants for member in members):
            raise HTTPException(status_code=422, detail="Every team member must appear in participants")
        if seen_members.intersection(members):
            raise HTTPException(status_code=422, detail="A participant cannot belong to two imported teams")
        seen_members.update(members)
        for project in team.projects:
            if project.track.casefold() not in track_names or project.status not in {"draft", "submitted"}:
                raise HTTPException(status_code=422, detail="Project track or status is invalid")
            for url in (project.repo_url, project.demo_url, project.live_url, project.video_url, project.thumbnail_url):
                require_web_url(url)
            images = [url.strip() for url in project.image_urls.splitlines() if url.strip()]
            if len(images) > 5:
                raise HTTPException(status_code=422, detail="At most five project images")
            for url in images:
                require_web_url(url)
            if set(project.answers) - question_labels or any(len(answer) > 2000 for answer in project.answers.values()):
                raise HTTPException(status_code=422, detail="Unknown or oversized project answer")
            if project.status == "submitted" and any(not project.answers.get(label, "").strip() for label in required_labels):
                raise HTTPException(status_code=422, detail="Imported submission lacks a required answer")
            if project.submitted_at:
                submitted_at = time_value(project.submitted_at)
                if submitted_at > time_value(deadline):
                    raise HTTPException(status_code=422, detail="Imported submission is after the target deadline")
    return {"participants": len(bundle.participants), "teams": len(bundle.teams),
            "projects": sum(len(team.projects) for team in bundle.teams), "judges": len(bundle.judges)}


@router.get("/events/{event_id}/exports/portable.json")
def export_portable(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        event = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        tracks = [row["name"] for row in db.execute("SELECT name FROM tracks WHERE event_id=? ORDER BY name", (event_id,))]
        prizes = [dict(row) for row in db.execute("SELECT name,description FROM prizes WHERE event_id=? ORDER BY name", (event_id,))]
        questions = [dict(row) for row in db.execute("SELECT label,required FROM submission_questions WHERE event_id=? ORDER BY sort_order", (event_id,))]
        participants = [dict(row) for row in db.execute(
            "SELECT u.name,u.email FROM event_roles r JOIN users u ON u.id=r.user_id"
            " WHERE r.event_id=? AND r.role='participant' ORDER BY u.email", (event_id,))]
        teams = []
        for team in db.execute("SELECT id,name FROM teams WHERE event_id=? ORDER BY id", (event_id,)):
            members = [row["email"] for row in db.execute("SELECT u.email FROM team_members m"
                " JOIN users u ON u.id=m.user_id WHERE m.team_id=? ORDER BY CASE m.role WHEN 'captain' THEN 0 ELSE 1 END,m.joined_at,u.email", (team["id"],))]
            portable_projects = []
            for project in db.execute("SELECT p.*,t.name AS track FROM projects p JOIN tracks t ON t.id=p.track_id"
                                      " WHERE p.team_id=? ORDER BY p.updated_at,p.id", (team["id"],)):
                fields = ("title", "summary", "description", "repo_url", "demo_url", "live_url", "video_url",
                          "thumbnail_url", "image_urls", "tech_tags", "track", "status", "submitted_at")
                portable_project = {field: project[field] for field in fields}
                portable_project["answers"] = {row["label"]: row["answer"] for row in db.execute(
                    "SELECT q.label,a.answer FROM project_answers a JOIN submission_questions q ON q.id=a.question_id"
                    " WHERE a.project_id=? ORDER BY q.sort_order", (project["id"],))}
                portable_projects.append(portable_project)
            teams.append({"name": team["name"], "members": members, "projects": portable_projects})
        judges = []
        for judge in db.execute("SELECT j.id,u.name,u.email FROM judge_profiles j JOIN users u ON u.id=j.user_id"
                                " WHERE j.event_id=? ORDER BY u.email", (event_id,)):
            judge_tracks = [row["name"] for row in db.execute("SELECT t.name FROM judge_tracks jt"
                " JOIN tracks t ON t.id=jt.track_id WHERE jt.judge_id=? ORDER BY t.name", (judge["id"],))]
            judges.append({"name": judge["name"], "email": judge["email"], "tracks": judge_tracks})
    event_fields = ("name", "description", "registration_open", "registration_close", "submissions_open",
                    "submissions_close", "judging_open", "judging_close")
    return {"format": FORMAT, "event": {field: event[field] for field in event_fields}, "tracks": tracks,
            "prizes": prizes, "questions": questions, "participants": participants,
            "teams": teams, "judges": judges}


@router.post("/events/{event_id}/imports/portable.json")
def import_portable(event_id: str, payload: Bundle, request: Request, dry_run: bool = Query(default=False)):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        event = db.execute("SELECT submissions_close,results_published_at FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        if event["results_published_at"] or datetime.now(timezone.utc) >= time_value(event["submissions_close"]):
            raise HTTPException(status_code=409, detail="Import needs an open target event")
        if db.execute("SELECT 1 FROM teams WHERE event_id=? LIMIT 1", (event_id,)).fetchone() or db.execute(
            "SELECT 1 FROM projects WHERE event_id=? LIMIT 1", (event_id,)).fetchone():
            raise HTTPException(status_code=409, detail="Import needs an event without teams or projects")
        if db.execute("SELECT 1 FROM judge_profiles WHERE event_id=? LIMIT 1", (event_id,)).fetchone():
            raise HTTPException(status_code=409, detail="Import needs an event without judge profiles")
        counts = _validate(payload, event["submissions_close"])
        prior_questions = db.execute("SELECT label,required FROM submission_questions WHERE event_id=? ORDER BY sort_order", (event_id,)).fetchall()
        if prior_questions and [(row["label"], bool(row["required"])) for row in prior_questions] != [
            (question.label.strip(), question.required) for question in payload.questions]:
            raise HTTPException(status_code=409, detail="Target event questions differ from the bundle")
        if dry_run:
            return {"valid": True, "dry_run": True, **counts}
        now = utc_now()
        track_ids = {row["name"].casefold(): row["id"] for row in db.execute(
            "SELECT id,name FROM tracks WHERE event_id=?", (event_id,))}
        for name in payload.tracks:
            if name.casefold() not in track_ids:
                track_id = identifier("trk")
                db.execute("INSERT INTO tracks(id,event_id,name) VALUES(?,?,?)", (track_id, event_id, name.strip()))
                track_ids[name.casefold()] = track_id
        existing_prizes = {row["name"].casefold() for row in db.execute("SELECT name FROM prizes WHERE event_id=?", (event_id,))}
        for prize in payload.prizes:
            if prize.name.casefold() not in existing_prizes:
                db.execute("INSERT INTO prizes(id,event_id,name,description) VALUES(?,?,?,?)",
                           (identifier("prz"), event_id, prize.name.strip(), prize.description.strip()))
        if not prior_questions:
            for index, question in enumerate(payload.questions):
                db.execute("INSERT INTO submission_questions(id,event_id,label,required,sort_order) VALUES(?,?,?,?,?)",
                           (identifier("sq"), event_id, question.label.strip(), int(question.required), index))
        question_ids = {row["label"]: row["id"] for row in db.execute(
            "SELECT id,label FROM submission_questions WHERE event_id=?", (event_id,))}
        credentials = []
        user_ids = {}

        def ensure_user(person: Person) -> str:
            email = _email(person.email)
            if email in user_ids:
                return user_ids[email]
            prior = db.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
            if prior:
                user_ids[email] = prior["id"]
            else:
                password = secrets.token_urlsafe(18)
                user_ids[email] = identifier("usr")
                db.execute("INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)",
                           (user_ids[email], email, person.name.strip(), hash_password(password), now))
                credentials.append({"email": email, "temporary_password": password})
            return user_ids[email]

        for person in payload.participants:
            user_id = ensure_user(person)
            db.execute("INSERT OR IGNORE INTO event_roles(event_id,user_id,role) VALUES(?,?,'participant')",
                       (event_id, user_id))
        for team in payload.teams:
            captain = user_ids[_email(team.members[0])]
            team_id = identifier("tm")
            db.execute("INSERT INTO teams(id,event_id,name,created_by,created_at) VALUES(?,?,?,?,?)",
                       (team_id, event_id, team.name.strip(), captain, now))
            for index, email in enumerate(team.members):
                member_id = user_ids[_email(email)]
                db.execute("INSERT INTO team_members(team_id,user_id,role,joined_at) VALUES(?,?,?,?)",
                           (team_id, member_id, "captain" if index == 0 else "member", now))
            for project in team.projects:
                project_id = identifier("prj")
                submitted_at = (time_value(project.submitted_at).isoformat() if project.submitted_at else now) if project.status == "submitted" else None
                db.execute("INSERT INTO projects(id,event_id,team_id,track_id,title,summary,description,repo_url,demo_url,"
                           "thumbnail_url,image_urls,video_url,live_url,tech_tags,status,submitted_at,updated_at)"
                           " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (project_id, event_id, team_id, track_ids[project.track.casefold()], project.title.strip(),
                            project.summary.strip(), project.description.strip(), project.repo_url.strip(),
                            project.demo_url.strip(), project.thumbnail_url.strip(), project.image_urls.strip(),
                            project.video_url.strip(), project.live_url.strip(), project.tech_tags.strip(),
                            project.status, submitted_at, now))
                for label, answer in project.answers.items():
                    if answer.strip():
                        db.execute("INSERT INTO project_answers(project_id,question_id,answer) VALUES(?,?,?)",
                                   (project_id, question_ids[label], answer.strip()))
        for judge in payload.judges:
            user_id = ensure_user(judge)
            db.execute("INSERT OR IGNORE INTO event_roles(event_id,user_id,role) VALUES(?,?,'judge')",
                       (event_id, user_id))
            profile_id = identifier("jdg")
            db.execute("INSERT INTO judge_profiles(id,event_id,user_id,status) VALUES(?,?,?,'accepted')",
                       (profile_id, event_id, user_id))
            for track in judge.tracks:
                db.execute("INSERT INTO judge_tracks(judge_id,track_id) VALUES(?,?)",
                           (profile_id, track_ids[track.casefold()]))
        reconcile_submitted_duplicates(db, event_id)
        audit(db, event_id, principal.user_id, "event.portable_imported", "event", event_id, counts)
        db.commit()
    return {"imported": True, **counts, "new_account_credentials": credentials}
