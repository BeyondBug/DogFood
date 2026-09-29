"""Complete, secret-conscious event archive export and cross-install import."""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import closing

from fastapi import APIRouter, HTTPException, Request

from .auth import hash_password, require_event_role, require_login
from .core import identifier
from .db import connect, utc_now

router = APIRouter(prefix="/api")
FORMAT = "beyondbug-event-archive-v1"

DIRECT = (
    "event_roles", "tracks", "prizes", "teams", "projects", "judge_profiles", "judge_invites",
    "rubrics", "judge_assignments", "audit_entries", "voter_invites", "ballots", "vote_attempts",
    "comments", "event_awards", "certificate_designs", "certificates", "duplicate_decisions",
    "pairwise_assignments", "judge_participation_records", "webhooks", "submission_questions",
    "open_voters", "open_ballots", "open_vote_attempts",
)
DEPENDENT = {
    "team_members": ("teams", "team_id"), "team_invites": ("teams", "team_id"),
    "judge_tracks": ("judge_profiles", "judge_id"), "judge_conflicts": ("judge_profiles", "judge_id"),
    "rubric_criteria": ("rubrics", "rubric_id"), "scorecards": ("judge_assignments", "assignment_id"),
    "criterion_scores": ("scorecards", "scorecard_id"), "project_answers": ("projects", "project_id"),
    "webhook_deliveries": ("webhooks", "webhook_id"),
}
AUTO_IDS = {"audit_entries", "vote_attempts", "open_vote_attempts"}
INSERT_ORDER = (
    "event_roles", "tracks", "prizes", "teams", "team_members", "team_invites", "projects",
    "duplicate_decisions", "judge_profiles", "judge_tracks", "judge_invites", "judge_conflicts",
    "rubrics", "rubric_criteria", "judge_assignments", "scorecards", "criterion_scores",
    "submission_questions", "project_answers", "voter_invites", "ballots", "vote_attempts", "comments",
    "open_voters", "open_ballots", "open_vote_attempts", "event_awards", "certificate_designs",
    "certificates", "pairwise_assignments", "judge_participation_records", "webhooks",
    "webhook_deliveries", "audit_entries",
)
USER_COLUMNS = {
    "event_roles": ("user_id",), "teams": ("created_by",), "team_members": ("user_id",),
    "team_invites": ("created_by",), "judge_profiles": ("user_id",), "judge_invites": ("created_by",),
    "audit_entries": ("actor_user_id",), "voter_invites": ("created_by", "voter_user_id"),
    "ballots": ("voter_user_id",), "vote_attempts": ("voter_user_id",),
    "comments": ("user_id", "hidden_by"), "event_awards": ("assigned_by",),
    "certificate_designs": ("updated_by",), "certificates": ("user_id",),
    "duplicate_decisions": ("decided_by",), "webhooks": ("created_by",),
}


def _rows(db, table: str, where: str, values: tuple) -> list[dict]:
    return [dict(row) for row in db.execute(f"SELECT * FROM {table} WHERE {where}", values)]


@router.get("/events/{event_id}/exports/archive.json")
def export_event_archive(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        event = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        tables = {table: _rows(db, table, "event_id=?", (event_id,)) for table in DIRECT}
        for table, (parent, column) in DEPENDENT.items():
            ids = [row["id"] for row in tables[parent]]
            tables[table] = [] if not ids else _rows(db, table, f"{column} IN ({','.join('?' for _ in ids)})", tuple(ids))
        user_ids = {event["created_by"]} if event["created_by"] else set()
        for table, columns in USER_COLUMNS.items():
            for row in tables[table]:
                user_ids.update(row.get(column) for column in columns if row.get(column))
        users = [] if not user_ids else [dict(row) for row in db.execute(
            f"SELECT id,email,name,created_at FROM users WHERE id IN ({','.join('?' for _ in user_ids)})",
            tuple(sorted(user_ids)))]
    public_event = dict(event)
    public_event["open_vote_token"] = None  # rotate share secrets on import
    for row in tables["webhooks"]:
        row["secret"] = None
        row["active"] = 0  # imported callbacks require an explicit operator decision
    return {"format": FORMAT, "exported_at": utc_now(), "event": public_event,
            "users": users, "tables": tables}


def _validate_archive(payload: dict) -> tuple[dict, list[dict], dict[str, list[dict]]]:
    if payload.get("format") != FORMAT or not isinstance(payload.get("event"), dict):
        raise HTTPException(status_code=422, detail="Unsupported event archive format")
    users, tables = payload.get("users"), payload.get("tables")
    if not isinstance(users, list) or not isinstance(tables, dict) or set(tables) != set(INSERT_ORDER):
        raise HTTPException(status_code=422, detail="Event archive table set is invalid")
    if not payload["event"].get("id") or len(users) > 5000:
        raise HTTPException(status_code=422, detail="Event archive identity or account count is invalid")
    total = 0
    event_id = payload["event"]["id"]
    for table in INSERT_ORDER:
        if not isinstance(tables[table], list):
            raise HTTPException(status_code=422, detail=f"Archive table {table} is invalid")
        if table in DIRECT and any(row.get("event_id") != event_id for row in tables[table]):
            raise HTTPException(status_code=422, detail=f"Archive table {table} contains another event")
        total += len(tables[table])
    if total > 250_000:
        raise HTTPException(status_code=413, detail="Event archive is too large")
    return payload["event"], users, tables


@router.post("/admin/imports/archive.json", status_code=201)
def import_event_archive(payload: dict, request: Request):
    principal = require_login(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    event, users, tables = _validate_archive(payload)
    event_id = event["id"]
    credentials = []
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone():
            raise HTTPException(status_code=409, detail="An event with this archive ID already exists")
        user_map: dict[str, str] = {}
        for user in users:
            source_id, email = user.get("id"), str(user.get("email", "")).strip().casefold()
            if not source_id or email.count("@") != 1 or not str(user.get("name", "")).strip():
                raise HTTPException(status_code=422, detail="Archive contains an invalid account")
            existing = db.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
            if existing:
                user_map[source_id] = existing["id"]
            else:
                if db.execute("SELECT 1 FROM users WHERE id=?", (source_id,)).fetchone():
                    raise HTTPException(status_code=409, detail="Archive account ID collides with this installation")
                password = secrets.token_urlsafe(18)
                db.execute("INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)",
                           (source_id, email, str(user["name"]).strip(), hash_password(password), user.get("created_at") or utc_now()))
                user_map[source_id] = source_id
                credentials.append({"email": email, "temporary_password": password})
        restored_event = dict(event)
        restored_event["created_by"] = user_map.get(restored_event.get("created_by"), principal.user_id)
        restored_event["open_vote_token"] = secrets.token_urlsafe(32) if restored_event.get("open_link_enabled") else None
        event_columns = [row["name"] for row in db.execute("PRAGMA table_info(events)")]
        unknown = set(restored_event) - set(event_columns)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Archive event has unknown fields: {sorted(unknown)}")
        columns = list(restored_event)
        db.execute(f"INSERT INTO events({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                   tuple(restored_event[column] for column in columns))
        try:
            duplicate_links = []
            for table in INSERT_ORDER:
                valid_columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                for original in tables[table]:
                    row = dict(original)
                    if set(row) - valid_columns:
                        raise HTTPException(status_code=422, detail=f"Archive table {table} has unknown fields")
                    for column in USER_COLUMNS.get(table, ()):
                        if row.get(column):
                            row[column] = user_map.get(row[column], row[column])
                    if table in AUTO_IDS:
                        row.pop("id", None)
                    if table == "projects":
                        duplicate = row.pop("duplicate_of", None)
                    else:
                        duplicate = None
                    if table == "webhooks":
                        row["secret"] = secrets.token_urlsafe(32)
                        row["active"] = 0
                    columns = list(row)
                    db.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                               tuple(row[column] for column in columns))
                    if duplicate:
                        duplicate_links.append((duplicate, row["id"]))
            for duplicate, project_id in duplicate_links:
                db.execute("UPDATE projects SET duplicate_of=? WHERE id=?", (duplicate, project_id))
        except sqlite3.IntegrityError as failure:
            raise HTTPException(status_code=422, detail=f"Archive relationship check failed: {failure}") from failure
        db.commit()
    return {"imported": True, "event_id": event_id,
            "records": sum(len(rows) for rows in tables.values()),
            "new_account_credentials": credentials,
            "open_vote_url": (f"/open-vote/{restored_event['open_vote_token']}"
                              if restored_event.get("open_link_enabled") else None)}
