"""Optional community ballot and moderated project discussion."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import require_event_role, require_login
from .core import audit, identifier, time_value
from .db import connect, utc_now


router = APIRouter(prefix="/api")


class VotingConfig(BaseModel):
    mode: str
    opens_at: str
    closes_at: str


def _voting_event(db, event_id: str):
    event = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def _window_open(event) -> bool:
    now = datetime.now(timezone.utc)
    return (event["voting_mode"] != "disabled" and event["voting_open"] is not None
            and event["voting_close"] is not None
            and time_value(event["voting_open"]) <= now < time_value(event["voting_close"]))


def _eligible(db, event, user_id: str) -> bool:
    if event["voting_mode"] == "invite_only":
        return db.execute("SELECT 1 FROM voter_invites WHERE event_id=? AND voter_user_id=? AND accepted_at IS NOT NULL",
                          (event["id"], user_id)).fetchone() is not None
    if event["voting_mode"] == "participants":
        row = db.execute("SELECT u.created_at FROM event_roles r JOIN users u ON u.id=r.user_id"
                         " WHERE r.event_id=? AND r.user_id=? AND r.role='participant'",
                         (event["id"], user_id)).fetchone()
        return row is not None and time_value(row["created_at"]) <= time_value(event["voting_open"])
    return False


def order_ballot(projects: list[dict], seed: str, user_id: str) -> list[dict]:
    """Stable private order per voter, independent of project insertion order."""
    key = bytes.fromhex(seed)
    return sorted(projects, key=lambda row: hmac.new(
        key, f"{user_id}:{row['id']}".encode(), hashlib.sha256,
    ).digest())


@router.put("/events/{event_id}/voting")
def configure_voting(event_id: str, payload: VotingConfig, request: Request):
    principal = require_login(request)
    if payload.mode not in ("disabled", "invite_only", "participants"):
        raise HTTPException(status_code=422, detail="Mode must be disabled, invite_only, or participants")
    opening = time_value(payload.opens_at)
    closing_time = time_value(payload.closes_at)
    if opening is None or closing_time is None or closing_time <= opening:
        raise HTTPException(status_code=422, detail="Voting close must be after voting open")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        event = _voting_event(db, event_id)
        require_event_role(db, principal, event_id, "organizer")
        if event["results_published_at"] or db.execute("SELECT 1 FROM ballots WHERE event_id=? LIMIT 1", (event_id,)).fetchone():
            raise HTTPException(status_code=409, detail="Voting cannot be changed after ballots or published results")
        if opening < time_value(event["submissions_close"]):
            raise HTTPException(status_code=422, detail="Voting must open after submissions close")
        seed = event["ballot_seed"] or secrets.token_hex(32)
        db.execute("UPDATE events SET voting_mode=?,voting_open=?,voting_close=?,ballot_seed=? WHERE id=?",
                   (payload.mode, opening.isoformat(), closing_time.isoformat(), seed, event_id))
        audit(db, event_id, principal.user_id, "voting.configured", "event", event_id,
              {"mode": payload.mode, "opens_at": opening.isoformat(), "closes_at": closing_time.isoformat()})
        db.commit()
    return {"mode": payload.mode, "opens_at": opening.isoformat(), "closes_at": closing_time.isoformat()}


@router.get("/events/{event_id}/voting")
def voting_status(event_id: str):
    with closing(connect()) as db:
        event = _voting_event(db, event_id)
    return {"mode": event["voting_mode"], "opens_at": event["voting_open"],
            "closes_at": event["voting_close"], "open_now": _window_open(event)}


class VoterInviteInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)


@router.post("/events/{event_id}/voter-invites", status_code=201)
def invite_voter(event_id: str, payload: VoterInviteInput, request: Request):
    principal = require_login(request)
    email = payload.email.strip().casefold()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        event = _voting_event(db, event_id)
        require_event_role(db, principal, event_id, "organizer")
        if event["voting_mode"] != "invite_only":
            raise HTTPException(status_code=409, detail="Invite-only voting is not configured")
        existing = db.execute("SELECT accepted_at FROM voter_invites WHERE event_id=? AND email=? COLLATE NOCASE",
                              (event_id, email)).fetchone()
        if existing and existing["accepted_at"]:
            raise HTTPException(status_code=409, detail="This voter already accepted an invitation")
        token = secrets.token_urlsafe(24)
        token_digest = hashlib.sha256(token.encode()).hexdigest()
        expiry = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        db.execute("INSERT INTO voter_invites(token_hash,event_id,email,created_by,expires_at) VALUES(?,?,?,?,?)"
                   " ON CONFLICT(event_id,email) DO UPDATE SET token_hash=excluded.token_hash,"
                   " created_by=excluded.created_by,expires_at=excluded.expires_at",
                   (token_digest, event_id, email, principal.user_id, expiry))
        audit(db, event_id, principal.user_id, "voter.invited", "voter_invite", email)
        db.commit()
    return {"invite_url": f"/vote-invite/{token}", "email": email, "expires_at": expiry}


@router.post("/voter-invites/{token}/accept")
def accept_voter_invite(token: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        invite = db.execute("SELECT * FROM voter_invites WHERE token_hash=?",
                            (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if invite is None or invite["accepted_at"] or time_value(invite["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Voter invite is invalid or expired")
        if invite["email"] != principal.email.casefold():
            raise HTTPException(status_code=403, detail="This invite belongs to another email address")
        db.execute("UPDATE voter_invites SET accepted_at=?,voter_user_id=? WHERE token_hash=?",
                   (utc_now(), principal.user_id, invite["token_hash"]))
        audit(db, invite["event_id"], principal.user_id, "voter.invite_accepted", "event", invite["event_id"])
        db.commit()
    return {"event_id": invite["event_id"]}


@router.get("/events/{event_id}/ballot")
def ballot(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        event = _voting_event(db, event_id)
        if not _window_open(event):
            raise HTTPException(status_code=409, detail="Voting is not open")
        if not _eligible(db, event, principal.user_id):
            raise HTTPException(status_code=403, detail="You are not eligible to vote in this event")
        existing = db.execute("SELECT 1 FROM ballots WHERE event_id=? AND voter_user_id=?",
                              (event_id, principal.user_id)).fetchone()
        projects = db.execute("SELECT p.id,p.title,p.summary,t.name AS track,tm.name AS team"
                              " FROM projects p JOIN tracks t ON t.id=p.track_id"
                              " JOIN teams tm ON tm.id=p.team_id"
                              " WHERE p.event_id=? AND p.status='submitted' AND p.duplicate_of IS NULL",
                              (event_id,)).fetchall()
        own = {row["project_id"] for row in db.execute(
            "SELECT p.id AS project_id FROM projects p JOIN team_members m ON m.team_id=p.team_id"
            " WHERE p.event_id=? AND m.user_id=?", (event_id, principal.user_id))}
    choices = [dict(row) for row in projects if row["id"] not in own]
    choices = order_ballot(choices, event["ballot_seed"], principal.user_id)
    return {"event_id": event_id, "closes_at": event["voting_close"],
            "has_voted": existing is not None, "projects": choices}


class VoteInput(BaseModel):
    project_id: str


@router.post("/events/{event_id}/votes", status_code=201)
def cast_vote(event_id: str, payload: VoteInput, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        event = _voting_event(db, event_id)
        ip = request.client.host if request.client else "unknown"
        ip_hash = hmac.new(bytes.fromhex(event["ballot_seed"] or "00"), ip.encode(), hashlib.sha256).hexdigest()
        now = utc_now()

        def deny(status: int, detail: str, outcome: str):
            db.execute("INSERT INTO vote_attempts(event_id,voter_user_id,ip_hash,outcome,created_at)"
                       " VALUES(?,?,?,?,?)", (event_id, principal.user_id, ip_hash, outcome, now))
            db.commit()
            raise HTTPException(status_code=status, detail=detail)

        if not _window_open(event):
            deny(409, "Voting is not open", "closed")
        window_start = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
        user_attempts = db.execute("SELECT COUNT(*) FROM vote_attempts WHERE event_id=? AND voter_user_id=? AND created_at>=?",
                                   (event_id, principal.user_id, window_start)).fetchone()[0]
        ip_attempts = db.execute("SELECT COUNT(*) FROM vote_attempts WHERE event_id=? AND ip_hash=? AND created_at>=?",
                                 (event_id, ip_hash, window_start)).fetchone()[0]
        if user_attempts >= 5 or ip_attempts >= 30:
            deny(429, "Too many vote attempts; try again later", "rate_limited")
        if not _eligible(db, event, principal.user_id):
            deny(403, "You are not eligible to vote in this event", "ineligible")
        if db.execute("SELECT 1 FROM ballots WHERE event_id=? AND voter_user_id=?", (event_id, principal.user_id)).fetchone():
            deny(409, "Your vote is already recorded", "duplicate")
        project = db.execute("SELECT id,team_id FROM projects WHERE id=? AND event_id=?"
                             " AND status='submitted' AND duplicate_of IS NULL", (payload.project_id, event_id)).fetchone()
        if project is None:
            deny(422, "Choose a submitted project on this ballot", "invalid_project")
        if db.execute("SELECT 1 FROM team_members WHERE team_id=? AND user_id=?",
                      (project["team_id"], principal.user_id)).fetchone():
            deny(403, "You cannot vote for your own team", "self_vote")
        ballot_id = identifier("ballot")
        db.execute("INSERT INTO ballots(id,event_id,voter_user_id,project_id,cast_at) VALUES(?,?,?,?,?)",
                   (ballot_id, event_id, principal.user_id, project["id"], now))
        db.execute("INSERT INTO vote_attempts(event_id,voter_user_id,ip_hash,outcome,created_at)"
                   " VALUES(?,?,?,?,?)", (event_id, principal.user_id, ip_hash, "accepted", now))
        audit(db, event_id, principal.user_id, "vote.cast", "event", event_id)
        db.commit()
    return {"recorded": True, "ballot_id": ballot_id}


def _vote_summary(db, event_id: str) -> dict:
    totals = db.execute("SELECT p.id,p.title,COUNT(b.id) AS votes FROM projects p"
                        " LEFT JOIN ballots b ON b.project_id=p.id"
                        " WHERE p.event_id=? AND p.status='submitted' AND p.duplicate_of IS NULL"
                        " GROUP BY p.id ORDER BY votes DESC,p.title", (event_id,)).fetchall()
    attempts = db.execute("SELECT outcome,COUNT(*) AS count FROM vote_attempts WHERE event_id=? GROUP BY outcome",
                          (event_id,)).fetchall()
    return {"total_votes": sum(row["votes"] for row in totals),
            "projects": [dict(row) for row in totals],
            "attempts": {row["outcome"]: row["count"] for row in attempts}}


@router.get("/events/{event_id}/votes/summary")
def private_vote_summary(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        return _vote_summary(db, event_id)


@router.get("/events/{event_id}/votes/results")
def public_vote_results(event_id: str):
    with closing(connect()) as db:
        event = _voting_event(db, event_id)
        if not event["results_published_at"]:
            raise HTTPException(status_code=404, detail="Voting results are not published")
        summary = _vote_summary(db, event_id)
    return {"total_votes": summary["total_votes"], "projects": summary["projects"]}


class CommentInput(BaseModel):
    body: str = Field(min_length=3, max_length=2000)


@router.get("/projects/{project_id}/comments")
def list_comments(project_id: str):
    with closing(connect()) as db:
        project = db.execute("SELECT id FROM projects WHERE id=? AND status='submitted'", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        comments = db.execute("SELECT c.id,c.body,c.created_at,u.name AS author"
                              " FROM comments c JOIN users u ON u.id=c.user_id"
                              " WHERE c.project_id=? AND c.hidden_at IS NULL ORDER BY c.created_at,c.id LIMIT 200",
                              (project_id,)).fetchall()
    return {"comments": [dict(row) for row in comments]}


@router.post("/projects/{project_id}/comments", status_code=201)
def add_comment(project_id: str, payload: CommentInput, request: Request):
    principal = require_login(request)
    body = payload.body.strip()
    if len(body) < 3:
        raise HTTPException(status_code=422, detail="Write at least three characters")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        project = db.execute("SELECT p.id,p.event_id,e.* FROM projects p JOIN events e ON e.id=p.event_id"
                             " WHERE p.id=? AND p.status='submitted'", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if not _window_open(project):
            raise HTTPException(status_code=409, detail="Comments are open only during voting")
        hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        count = db.execute("SELECT COUNT(*) FROM comments WHERE event_id=? AND user_id=? AND created_at>=?",
                           (project["event_id"], principal.user_id, hour_ago)).fetchone()[0]
        if count >= 5:
            raise HTTPException(status_code=429, detail="Comment limit reached; try later")
        duplicate = db.execute("SELECT 1 FROM comments WHERE project_id=? AND user_id=? AND body=? AND created_at>=?",
                               (project_id, principal.user_id, body, hour_ago)).fetchone()
        if duplicate:
            raise HTTPException(status_code=409, detail="You already posted this comment")
        comment_id = identifier("comment")
        now = utc_now()
        db.execute("INSERT INTO comments(id,event_id,project_id,user_id,body,created_at) VALUES(?,?,?,?,?,?)",
                   (comment_id, project["event_id"], project_id, principal.user_id, body, now))
        audit(db, project["event_id"], principal.user_id, "comment.created", "comment", comment_id)
        db.commit()
    return {"id": comment_id, "body": body}


@router.delete("/comments/{comment_id}")
def hide_comment(comment_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        comment = db.execute("SELECT event_id,hidden_at FROM comments WHERE id=?", (comment_id,)).fetchone()
        if comment is None:
            raise HTTPException(status_code=404, detail="Comment not found")
        require_event_role(db, principal, comment["event_id"], "organizer")
        if comment["hidden_at"]:
            raise HTTPException(status_code=409, detail="Comment is already hidden")
        db.execute("UPDATE comments SET hidden_at=?,hidden_by=? WHERE id=?", (utc_now(), principal.user_id, comment_id))
        audit(db, comment["event_id"], principal.user_id, "comment.hidden", "comment", comment_id)
        db.commit()
    return {"hidden": True}
