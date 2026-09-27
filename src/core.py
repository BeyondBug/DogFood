"""Account, event, team and submission lifecycle APIs."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .auth import hash_password, require_event_role, require_login, verify_password
from .db import connect, utc_now


router = APIRouter(prefix="/api")


def identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def require_web_url(value: str) -> str:
    value = value.strip()
    if value:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise HTTPException(status_code=422, detail="Links must start with http:// or https://")
    return value


def csv_safe(value):
    """Prevent spreadsheet formula execution when organizers open an export."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def time_value(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Dates must be ISO 8601 timestamps") from error
    if moment.tzinfo is None:
        raise HTTPException(status_code=422, detail="Dates must include a timezone")
    return moment.astimezone(timezone.utc)


def require_before(value: str | None, message: str) -> None:
    if value and datetime.now(timezone.utc) >= time_value(value):
        raise HTTPException(status_code=409, detail=message)


def audit(db, event_id: str | None, actor: str, action: str, entity: str, entity_id: str, details: dict | None = None) -> None:
    db.execute(
        "INSERT INTO audit_entries(event_id,actor_user_id,action,entity_type,entity_id,details_json,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (event_id, actor, action, entity, entity_id, json.dumps(details or {}, sort_keys=True), utc_now()),
    )


class RegisterInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class LoginInput(BaseModel):
    email: str
    password: str


def _make_session(db, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.execute(
        "INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
        (hashlib.sha256(token.encode()).hexdigest(), user_id, now.isoformat(), (now + timedelta(days=7)).isoformat()),
    )
    return token


@router.post("/auth/register", status_code=201)
def register(payload: RegisterInput, response: Response):
    email = payload.email.strip().casefold()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    user_id = identifier("usr")
    with closing(connect()) as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)",
                (user_id, email, payload.name.strip(), hash_password(payload.password), utc_now()),
            )
            token = _make_session(db, user_id)
            db.commit()
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="An account already uses this email") from error
    response.set_cookie("session", token, httponly=True, samesite="strict",
                        secure=os.getenv("DOGFOOD_COOKIE_SECURE", "0") == "1", max_age=604800)
    return {"user_id": user_id, "name": payload.name.strip()}


@router.post("/auth/login")
def login(payload: LoginInput, response: Response):
    with closing(connect()) as db:
        user = db.execute("SELECT id,name,password_hash FROM users WHERE email=? COLLATE NOCASE", (payload.email.strip(),)).fetchone()
        if user is None or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Email or password is incorrect")
        token = _make_session(db, user["id"])
        db.commit()
    response.set_cookie("session", token, httponly=True, samesite="strict",
                        secure=os.getenv("DOGFOOD_COOKIE_SECURE", "0") == "1", max_age=604800)
    return {"user_id": user["id"], "name": user["name"]}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response):
    token = request.cookies.get("session")
    if token:
        with closing(connect()) as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
            db.commit()
    response.delete_cookie("session")


@router.get("/auth/me")
def me(request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        roles = db.execute("SELECT event_id,role FROM event_roles WHERE user_id=? ORDER BY event_id,role", (principal.user_id,)).fetchall()
    return {"id": principal.user_id, "email": principal.email, "name": principal.name,
            "is_admin": principal.is_admin, "roles": [dict(row) for row in roles]}


class EventCreate(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=2000)
    registration_open: str | None = None
    registration_close: str | None = None
    submissions_open: str | None = None
    submissions_close: str
    judging_open: str | None = None
    judging_close: str | None = None
    tracks: list[str] = Field(min_length=1)
    prizes: list[str] = Field(default_factory=list)


class EventPatch(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    registration_open: str | None = None
    registration_close: str | None = None
    submissions_open: str | None = None
    submissions_close: str | None = None
    judging_open: str | None = None
    judging_close: str | None = None


@router.get("/events")
def list_events():
    with closing(connect()) as db:
        events = db.execute("SELECT id,name,description,submissions_close,results_published_at FROM events ORDER BY created_at DESC").fetchall()
    return {"events": [dict(row) for row in events]}


@router.post("/events", status_code=201)
def create_event(payload: EventCreate, request: Request):
    principal = require_login(request)
    date_fields = ["registration_open", "registration_close", "submissions_open", "submissions_close", "judging_open", "judging_close"]
    dates = {key: time_value(getattr(payload, key)) for key in date_fields}
    for opening, closing_name in (("registration_open", "registration_close"), ("submissions_open", "submissions_close"), ("judging_open", "judging_close")):
        if dates[opening] and dates[closing_name] and dates[opening] >= dates[closing_name]:
            raise HTTPException(status_code=422, detail=f"{closing_name} must be after {opening}")
    tracks = [name.strip() for name in payload.tracks if name.strip()]
    if not tracks or len(tracks) != len(set(name.casefold() for name in tracks)):
        raise HTTPException(status_code=422, detail="Provide unique, nonempty tracks")
    event_id = identifier("evt")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT INTO events(id,name,description,registration_open,registration_close,submissions_open,submissions_close,judging_open,judging_close,created_by,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, payload.name.strip(), payload.description.strip(),
             *(dates[key].isoformat() if dates[key] else None for key in date_fields), principal.user_id, utc_now()),
        )
        db.execute("INSERT INTO event_roles(event_id,user_id,role) VALUES(?,?,'organizer')", (event_id, principal.user_id))
        for name in tracks:
            db.execute("INSERT INTO tracks(id,event_id,name) VALUES(?,?,?)", (identifier("trk"), event_id, name))
        for name in payload.prizes:
            if name.strip():
                db.execute("INSERT INTO prizes(id,event_id,name) VALUES(?,?,?)", (identifier("prz"), event_id, name.strip()))
        rubric_id = identifier("rubric")
        db.execute("INSERT INTO rubrics(id,event_id,version,name,created_at) VALUES(?,?,1,?,?)",
                   (rubric_id, event_id, "Default rubric", utc_now()))
        for position, (slug, name, weight) in enumerate((("functionality", "Functionality", 40),
                                                         ("quality", "Quality", 35),
                                                         ("impact", "Impact", 25))):
            db.execute("INSERT INTO rubric_criteria(id,rubric_id,slug,name,weight,max_score,sort_order)"
                       " VALUES(?,?,?,?,?,5,?)",
                       (identifier("crit"), rubric_id, slug, name, weight, position))
        audit(db, event_id, principal.user_id, "event.created", "event", event_id)
        db.commit()
    return {"id": event_id, "name": payload.name.strip()}


@router.get("/events/{event_id}")
def get_event(event_id: str):
    with closing(connect()) as db:
        event = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        tracks = db.execute("SELECT id,name FROM tracks WHERE event_id=? ORDER BY name", (event_id,)).fetchall()
        prizes = db.execute("SELECT id,name,description FROM prizes WHERE event_id=? ORDER BY name", (event_id,)).fetchall()
    public_event = dict(event)
    public_event.pop("ballot_seed", None)
    return {"event": public_event, "tracks": [dict(row) for row in tracks], "prizes": [dict(row) for row in prizes]}


@router.patch("/events/{event_id}")
def update_event(event_id: str, payload: EventPatch, request: Request):
    principal = require_login(request)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    date_fields = {"registration_open", "registration_close", "submissions_open", "submissions_close", "judging_open", "judging_close"}
    for key in date_fields & updates.keys():
        updates[key] = time_value(updates[key]).isoformat() if updates[key] else None
    if "submissions_close" in updates and updates["submissions_close"] is None:
        raise HTTPException(status_code=422, detail="Submissions must have a deadline")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        event = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        require_event_role(db, principal, event_id, "organizer")
        if event["results_published_at"]:
            raise HTTPException(status_code=409, detail="Published events are locked")
        merged = dict(event) | updates
        for opening, closing_name in (("registration_open", "registration_close"),
                                      ("submissions_open", "submissions_close"),
                                      ("judging_open", "judging_close")):
            if merged[opening] and merged[closing_name] and time_value(merged[opening]) >= time_value(merged[closing_name]):
                raise HTTPException(status_code=422, detail=f"{closing_name} must be after {opening}")
        if "name" in updates:
            if updates["name"] is None or len(updates["name"].strip()) < 3:
                raise HTTPException(status_code=422, detail="Event name must have at least three characters")
            updates["name"] = updates["name"].strip()
        if "description" in updates:
            updates["description"] = (updates["description"] or "").strip()
        assignments = ",".join(f"{key}=?" for key in updates)
        db.execute(f"UPDATE events SET {assignments} WHERE id=?", (*updates.values(), event_id))
        audit(db, event_id, principal.user_id, "event.updated", "event", event_id,
              {"fields": sorted(updates)})
        db.commit()
    return {"id": event_id, "updated": sorted(updates)}


@router.post("/events/{event_id}/registration", status_code=201)
def join_event(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        event = db.execute("SELECT registration_open,registration_close FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        if event["registration_open"] and datetime.now(timezone.utc) < time_value(event["registration_open"]):
            raise HTTPException(status_code=409, detail="Registration is not open yet")
        require_before(event["registration_close"], "Registration is closed")
        db.execute("INSERT OR IGNORE INTO event_roles(event_id,user_id,role) VALUES(?,?,'participant')", (event_id, principal.user_id))
        audit(db, event_id, principal.user_id, "participant.registered", "event", event_id)
        db.commit()
    return {"event_id": event_id, "role": "participant"}


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


@router.post("/events/{event_id}/teams", status_code=201)
def create_team(event_id: str, payload: TeamCreate, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "participant")
        existing = db.execute("SELECT 1 FROM team_members m JOIN teams t ON t.id=m.team_id WHERE t.event_id=? AND m.user_id=?", (event_id, principal.user_id)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="You already belong to a team in this event")
        team_id = identifier("tm")
        now = utc_now()
        db.execute("INSERT INTO teams(id,event_id,name,created_by,created_at) VALUES(?,?,?,?,?)", (team_id, event_id, payload.name.strip(), principal.user_id, now))
        db.execute("INSERT INTO team_members(team_id,user_id,role,joined_at) VALUES(?,?,'captain',?)", (team_id, principal.user_id, now))
        audit(db, event_id, principal.user_id, "team.created", "team", team_id)
        db.commit()
    return {"id": team_id, "name": payload.name.strip()}


@router.get("/events/{event_id}/my-team")
def my_team(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        team = db.execute("SELECT t.id,t.name FROM teams t JOIN team_members m ON m.team_id=t.id WHERE t.event_id=? AND m.user_id=?", (event_id, principal.user_id)).fetchone()
        if team is None:
            return {"team": None}
        members = db.execute("SELECT u.id,u.name,m.role FROM team_members m JOIN users u ON u.id=m.user_id WHERE m.team_id=? ORDER BY m.joined_at", (team["id"],)).fetchall()
        projects = db.execute("SELECT id,title,status,track_id,summary,repo_url FROM projects WHERE team_id=? ORDER BY updated_at DESC", (team["id"],)).fetchall()
    return {"team": dict(team), "members": [dict(row) for row in members], "projects": [dict(row) for row in projects]}


@router.post("/teams/{team_id}/invites", status_code=201)
def create_invite(team_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        team = db.execute("SELECT event_id FROM teams WHERE id=?", (team_id,)).fetchone()
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        member = db.execute("SELECT role FROM team_members WHERE team_id=? AND user_id=?", (team_id, principal.user_id)).fetchone()
        if member is None or member["role"] != "captain":
            raise HTTPException(status_code=403, detail="Only the team captain can invite members")
        count = db.execute("SELECT COUNT(*) FROM team_members WHERE team_id=?", (team_id,)).fetchone()[0]
        if count >= 4:
            raise HTTPException(status_code=409, detail="Teams can have at most four members")
        token = secrets.token_urlsafe(24)
        expiry = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        db.execute("INSERT INTO team_invites(token_hash,team_id,created_by,expires_at) VALUES(?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), team_id, principal.user_id, expiry))
        audit(db, team["event_id"], principal.user_id, "team.invite_created", "team", team_id)
        db.commit()
    return {"invite_url": f"/join/{token}", "expires_at": expiry}


@router.post("/team-invites/{token}/join")
def accept_invite(token: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        invitation = db.execute("SELECT i.*,t.event_id FROM team_invites i JOIN teams t ON t.id=i.team_id WHERE i.token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if invitation is None or invitation["revoked_at"] or invitation["uses"] >= invitation["max_uses"] or time_value(invitation["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Invite link is invalid or expired")
        existing = db.execute("SELECT 1 FROM team_members m JOIN teams t ON t.id=m.team_id WHERE t.event_id=? AND m.user_id=?", (invitation["event_id"], principal.user_id)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="You already belong to a team in this event")
        count = db.execute("SELECT COUNT(*) FROM team_members WHERE team_id=?", (invitation["team_id"],)).fetchone()[0]
        if count >= 4:
            raise HTTPException(status_code=409, detail="This team is full")
        db.execute("INSERT OR IGNORE INTO event_roles(event_id,user_id,role) VALUES(?,?,'participant')", (invitation["event_id"], principal.user_id))
        db.execute("INSERT INTO team_members(team_id,user_id,role,joined_at) VALUES(?,?,'member',?)", (invitation["team_id"], principal.user_id, utc_now()))
        db.execute("UPDATE team_invites SET uses=uses+1 WHERE token_hash=?", (invitation["token_hash"],))
        audit(db, invitation["event_id"], principal.user_id, "team.member_joined", "team", invitation["team_id"])
        db.commit()
    return {"team_id": invitation["team_id"]}


class ProjectUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=800)
    description: str = Field(default="", max_length=5000)
    repo_url: str = Field(default="", max_length=1000)
    demo_url: str = Field(default="", max_length=1000)
    track_id: str
    status: str = "draft"


@router.put("/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate, request: Request):
    principal = require_login(request)
    if payload.status not in ("draft", "submitted"):
        raise HTTPException(status_code=422, detail="Status must be draft or submitted")
    repo_url = require_web_url(payload.repo_url)
    demo_url = require_web_url(payload.demo_url)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        project = db.execute("SELECT p.*,e.submissions_open,e.submissions_close FROM projects p JOIN events e ON e.id=p.event_id WHERE p.id=?", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        require_before(project["submissions_close"], "Submissions are closed")
        if project["submissions_open"] and datetime.now(timezone.utc) < time_value(project["submissions_open"]):
            raise HTTPException(status_code=409, detail="Submissions are not open yet")
        member = db.execute("SELECT 1 FROM team_members WHERE team_id=? AND user_id=?", (project["team_id"], principal.user_id)).fetchone()
        if member is None:
            raise HTTPException(status_code=403, detail="Only this team can edit the project")
        track = db.execute("SELECT 1 FROM tracks WHERE id=? AND event_id=?", (payload.track_id, project["event_id"])).fetchone()
        if track is None:
            raise HTTPException(status_code=422, detail="Track does not belong to this event")
        now = utc_now()
        duplicate = db.execute("SELECT id FROM projects WHERE event_id=? AND repo_url=? AND repo_url<>'' AND id<>? AND duplicate_of IS NULL ORDER BY submitted_at,id LIMIT 1",
                               (project["event_id"], repo_url, project_id)).fetchone() if repo_url else None
        db.execute(
            "UPDATE projects SET title=?,summary=?,description=?,repo_url=?,demo_url=?,track_id=?,status=?,submitted_at=?,updated_at=?,duplicate_of=? WHERE id=?",
            (payload.title.strip(), payload.summary.strip(), payload.description.strip(), repo_url,
             demo_url, payload.track_id, payload.status,
             project["submitted_at"] or now if payload.status == "submitted" else None, now,
             duplicate["id"] if duplicate else None, project_id),
        )
        audit(db, project["event_id"], principal.user_id, "project.updated", "project", project_id, {"status": payload.status})
        db.commit()
    return {"id": project_id, "status": payload.status}


@router.get("/admin/overview")
def admin_overview(request: Request):
    principal = require_login(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    with closing(connect()) as db:
        events = db.execute("SELECT e.id,e.name,e.created_at,COUNT(DISTINCT p.id) AS projects,"
                            " COUNT(DISTINCT j.id) AS judges FROM events e"
                            " LEFT JOIN projects p ON p.event_id=e.id"
                            " LEFT JOIN judge_profiles j ON j.event_id=e.id"
                            " GROUP BY e.id ORDER BY e.created_at DESC").fetchall()
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return {"user_count": users, "events": [dict(row) for row in events]}
