"""Isolated DOGFOOD stretch features: pairwise judging, bulk IO, embeds and signed records."""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import html
import io
import json
import secrets
import subprocess
import tempfile
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from .auth import hash_password, require_event_role, require_login
from .core import audit, identifier, time_value
from .db import connect, utc_now


router = APIRouter()


class PairwiseBatchInput(BaseModel):
    comparisons_per_project: int = Field(default=3, ge=1, le=20)


class PairwiseVoteInput(BaseModel):
    winner_id: str


def _pairwise_ranking(db, event_id: str) -> dict:
    projects = [dict(row) for row in db.execute(
        "SELECT id,title FROM projects WHERE event_id=? AND status='submitted' AND duplicate_of IS NULL ORDER BY id",
        (event_id,),
    )]
    ids = {row["id"] for row in projects}
    wins = {project_id: 0.0 for project_id in ids}
    games = {project_id: 0 for project_id in ids}
    comparisons = db.execute(
        "SELECT project_a_id,project_b_id,winner_id FROM pairwise_assignments "
        "WHERE event_id=? AND submitted_at IS NOT NULL", (event_id,),
    ).fetchall()
    for row in comparisons:
        if row["project_a_id"] in ids and row["project_b_id"] in ids and row["winner_id"] in ids:
            wins[row["winner_id"]] += 1.0
            games[row["project_a_id"]] += 1
            games[row["project_b_id"]] += 1
    strengths = {project_id: 1.0 for project_id in ids}
    for _ in range(500):
        updated = {}
        for project_id in ids:
            denominator = 0.0
            for row in comparisons:
                if project_id not in (row["project_a_id"], row["project_b_id"]):
                    continue
                other = row["project_b_id"] if row["project_a_id"] == project_id else row["project_a_id"]
                if other in ids:
                    denominator += 1.0 / max(strengths[project_id] + strengths[other], 1e-12)
            updated[project_id] = (wins[project_id] + 0.5) / (denominator + 0.5) if denominator else 1.0
        scale = sum(updated.values()) / max(len(updated), 1)
        updated = {key: value / scale for key, value in updated.items()}
        if max((abs(updated[key] - strengths[key]) for key in ids), default=0.0) < 1e-10:
            strengths = updated
            break
        strengths = updated
    rows = [{**project, "strength": strengths[project["id"]], "wins": wins[project["id"]],
             "comparisons": games[project["id"]]} for project in projects]
    rows.sort(key=lambda row: (-row["strength"], -row["comparisons"], row["id"]))
    for index, row in enumerate(rows, 1):
        row["rank"] = index if row["comparisons"] else None
    return {"method": "Bradley-Terry MM with 0.5 pseudo-wins", "completed": len(comparisons), "projects": rows}


@router.post("/api/events/{event_id}/pairwise/assignments/batch")
def create_pairwise_assignments(event_id: str, payload: PairwiseBatchInput, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        event = db.execute("SELECT submissions_close,results_published_at FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        if event["results_published_at"]:
            raise HTTPException(status_code=409, detail="Results are published")
        if datetime.now(timezone.utc) < time_value(event["submissions_close"]):
            raise HTTPException(status_code=409, detail="Submissions must close before pairwise assignment")
        projects = db.execute(
            "SELECT id,track_id FROM projects WHERE event_id=? AND status='submitted' AND duplicate_of IS NULL ORDER BY id",
            (event_id,),
        ).fetchall()
        judges = db.execute("SELECT id,user_id FROM judge_profiles WHERE event_id=? AND status='accepted' ORDER BY id", (event_id,)).fetchall()
        if len(projects) < 2 or not judges:
            raise HTTPException(status_code=409, detail="Pairwise mode needs two projects and an accepted judge")
        created = []
        project_rows = list(projects)
        candidates = [(project_rows[i], project_rows[j]) for i in range(len(project_rows)) for j in range(i + 1, len(project_rows))]
        target = max(1, (len(project_rows) * payload.comparisons_per_project + 1) // 2)
        coverage = {row["id"]: 0 for row in project_rows}
        pairs = []
        while candidates and len(pairs) < target:
            candidates.sort(key=lambda pair: (max(coverage[pair[0]["id"]], coverage[pair[1]["id"]]),
                                               coverage[pair[0]["id"]] + coverage[pair[1]["id"]],
                                               pair[0]["id"], pair[1]["id"]))
            pair = candidates.pop(0); pairs.append(pair)
            coverage[pair[0]["id"]] += 1; coverage[pair[1]["id"]] += 1
        judge_load = {judge["id"]: db.execute(
            "SELECT COUNT(*) FROM pairwise_assignments WHERE judge_id=?", (judge["id"],)
        ).fetchone()[0] for judge in judges}
        shortages = []
        for left, right in pairs:
            needed_tracks = len({left["track_id"], right["track_id"]})
            eligible = [judge for judge in judges if db.execute(
                "SELECT COUNT(DISTINCT track_id) FROM judge_tracks WHERE judge_id=? AND track_id IN (?,?)",
                (judge["id"], left["track_id"], right["track_id"]),
            ).fetchone()[0] == needed_tracks and not db.execute(
                "SELECT 1 FROM team_members m JOIN projects p ON p.team_id=m.team_id "
                "WHERE m.user_id=? AND p.id IN (?,?)", (judge["user_id"], left["id"], right["id"]),
            ).fetchone() and not db.execute(
                "SELECT 1 FROM judge_conflicts WHERE judge_id=? AND project_id IN (?,?)",
                (judge["id"], left["id"], right["id"]),
            ).fetchone()]
            if not eligible:
                shortages.append([left["id"], right["id"]])
                continue
            judge = min(eligible, key=lambda item: (judge_load[item["id"]], item["id"]))
            pair_id = identifier("pair")
            cursor = db.execute(
                "INSERT OR IGNORE INTO pairwise_assignments(id,event_id,judge_id,project_a_id,project_b_id,assigned_at) "
                "VALUES(?,?,?,?,?,?)", (pair_id, event_id, judge["id"], left["id"], right["id"], utc_now()),
            )
            if cursor.rowcount:
                created.append(pair_id)
                judge_load[judge["id"]] += 1
        audit(db, event_id, principal.user_id, "pairwise.batch_created", "event", event_id,
              {"created": len(created), "comparisons_per_project": payload.comparisons_per_project})
        db.commit()
    return {"created": created, "requested_pairs": min(target, len(pairs)), "shortages": shortages,
            "coverage": coverage}


@router.get("/api/events/{event_id}/pairwise/my-assignments")
def pairwise_assignments(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "judge")
        rows = db.execute(
            "SELECT a.id,a.winner_id,a.submitted_at,p1.id AS project_a_id,p1.title AS project_a,"
            "p2.id AS project_b_id,p2.title AS project_b FROM pairwise_assignments a "
            "JOIN judge_profiles j ON j.id=a.judge_id JOIN projects p1 ON p1.id=a.project_a_id "
            "JOIN projects p2 ON p2.id=a.project_b_id WHERE a.event_id=? AND j.user_id=? ORDER BY a.id",
            (event_id, principal.user_id),
        ).fetchall()
    return {"assignments": [dict(row) for row in rows]}


@router.put("/api/pairwise/assignments/{assignment_id}")
def submit_pairwise(assignment_id: str, payload: PairwiseVoteInput, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT a.*,j.user_id,e.results_published_at FROM pairwise_assignments a "
            "JOIN judge_profiles j ON j.id=a.judge_id JOIN events e ON e.id=a.event_id WHERE a.id=?",
            (assignment_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Pairwise assignment not found")
        if row["user_id"] != principal.user_id:
            raise HTTPException(status_code=403, detail="You can submit only your own comparison")
        if row["results_published_at"]:
            raise HTTPException(status_code=409, detail="Results are published")
        if payload.winner_id not in (row["project_a_id"], row["project_b_id"]):
            raise HTTPException(status_code=422, detail="Winner must be one of the assigned projects")
        now = utc_now()
        db.execute("UPDATE pairwise_assignments SET winner_id=?,submitted_at=? WHERE id=?",
                   (payload.winner_id, now, assignment_id))
        audit(db, row["event_id"], principal.user_id, "pairwise.submitted", "pairwise_assignment", assignment_id)
        db.commit()
    return {"id": assignment_id, "winner_id": payload.winner_id, "submitted_at": now}


@router.get("/api/events/{event_id}/pairwise/rankings")
def pairwise_rankings(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        return _pairwise_ranking(db, event_id)


@router.get("/embed/{event_id}", response_class=HTMLResponse)
def embedded_gallery(event_id: str):
    with closing(connect()) as db:
        event = db.execute("SELECT name FROM events WHERE id=?", (event_id,)).fetchone()
        projects = db.execute(
            "SELECT p.id,p.title,p.summary,t.name AS track FROM projects p JOIN tracks t ON t.id=p.track_id "
            "WHERE p.event_id=? AND p.status='submitted' ORDER BY p.submitted_at DESC,p.id LIMIT 100", (event_id,),
        ).fetchall()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    cards = "".join(f'<article><small>{html.escape(row["track"])}</small><h2><a target="_blank" rel="noopener" href="/projects/{row["id"]}">{html.escape(row["title"])}</a></h2><p>{html.escape(row["summary"])}</p></article>' for row in projects)
    body = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{html.escape(event["name"])}</title><style>body{{font:15px system-ui;margin:0;color:#102b38}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;padding:12px}}article{{border:1px solid #c7d5d4;padding:18px;background:#fff}}h2{{font-size:19px;margin:8px 0}}a{{color:inherit}}small{{color:#167d78;font-weight:700}}p{{color:#547077}}</style></head><body><main>{cards}</main></body></html>'''
    return HTMLResponse(body, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors *"})


class BulkCsvInput(BaseModel):
    csv_text: str = Field(min_length=1, max_length=2_000_000)


@router.post("/api/admin/events/{event_id}/bulk/{kind}")
def bulk_import(event_id: str, kind: str, payload: BulkCsvInput, request: Request):
    principal = require_login(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    if kind not in ("participants", "judges"):
        raise HTTPException(status_code=404, detail="Bulk import type not found")
    try:
        rows = list(csv.DictReader(io.StringIO(payload.csv_text)))
    except csv.Error as error:
        raise HTTPException(status_code=422, detail="Invalid CSV") from error
    if len(rows) > 5000:
        raise HTTPException(status_code=422, detail="Import at most 5,000 rows")
    created, existing, errors, credentials = 0, 0, [], []
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Event not found")
        tracks = {row["name"].casefold(): row["id"] for row in db.execute("SELECT id,name FROM tracks WHERE event_id=?", (event_id,))}
        for number, row in enumerate(rows, 2):
            email, name = row.get("email", "").strip().casefold(), row.get("name", "").strip()
            if not name or "@" not in email:
                errors.append({"row": number, "error": "name and valid email are required"}); continue
            user = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if user:
                user_id, was_existing = user["id"], True
            else:
                user_id, was_existing = identifier("usr"), False
                password = row.get("password", "").strip() or secrets.token_urlsafe(18)
                if len(password) < 12:
                    errors.append({"row": number, "error": "password must contain at least 12 characters"}); continue
                db.execute("INSERT INTO users(id,email,name,password_hash,is_admin,created_at) VALUES(?,?,?,?,0,?)",
                           (user_id, email, name, hash_password(password), utc_now()))
                credentials.append({"email": email, "temporary_password": password})
            if kind == "participants":
                cursor = db.execute("INSERT OR IGNORE INTO event_roles(event_id,user_id,role) VALUES(?,?,'participant')", (event_id, user_id))
            else:
                judge_id = identifier("jdg")
                cursor = db.execute("INSERT OR IGNORE INTO judge_profiles(id,event_id,user_id,status) VALUES(?,?,?,'accepted')", (judge_id, event_id, user_id))
                if cursor.rowcount:
                    db.execute("INSERT OR IGNORE INTO event_roles(event_id,user_id,role) VALUES(?,?,'judge')", (event_id, user_id))
                    requested = [value.strip().casefold() for value in row.get("tracks", "").split(";") if value.strip()]
                    selected = [tracks[value] for value in requested if value in tracks] or list(tracks.values())
                    db.executemany("INSERT INTO judge_tracks(judge_id,track_id) VALUES(?,?)", [(judge_id, track) for track in selected])
            created += bool(cursor.rowcount)
            existing += was_existing or not cursor.rowcount
        audit(db, event_id, principal.user_id, f"bulk.{kind}_imported", "event", event_id,
              {"created": created, "existing": existing, "errors": len(errors)})
        db.commit()
    return {"created": created, "existing": existing, "errors": errors,
            "new_account_credentials": credentials,
            "note": "Temporary credentials are returned once; share them privately."}


@router.get("/api/events/{event_id}/export.json")
def event_archive(event_id: str, request: Request):
    """Portable event archive without password hashes, sessions, invite tokens or webhook secrets."""
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        event = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        queries = {
            "tracks": ("SELECT id,name FROM tracks WHERE event_id=? ORDER BY id",),
            "prizes": ("SELECT id,name,description FROM prizes WHERE event_id=? ORDER BY id",),
            "participants": ("SELECT u.id,u.name,u.email FROM event_roles r JOIN users u ON u.id=r.user_id "
                             "WHERE r.event_id=? AND r.role='participant' ORDER BY u.id",),
            "teams": ("SELECT id,name,created_by,created_at FROM teams WHERE event_id=? ORDER BY id",),
            "team_members": ("SELECT m.team_id,m.user_id,m.role,m.joined_at FROM team_members m JOIN teams t ON t.id=m.team_id "
                             "WHERE t.event_id=? ORDER BY m.team_id,m.user_id",),
            "projects": ("SELECT * FROM projects WHERE event_id=? ORDER BY id",),
            "judges": ("SELECT j.id,j.user_id,j.status,u.name,u.email FROM judge_profiles j JOIN users u ON u.id=j.user_id "
                       "WHERE j.event_id=? ORDER BY j.id",),
            "assignments": ("SELECT id,project_id,judge_id,assigned_at,reason FROM judge_assignments WHERE event_id=? ORDER BY id",),
            "scorecards": ("SELECT s.id,s.assignment_id,s.rubric_id,s.status,s.comment,s.updated_at,s.submitted_at "
                           "FROM scorecards s JOIN judge_assignments a ON a.id=s.assignment_id WHERE a.event_id=? ORDER BY s.id",),
            "pairwise_assignments": ("SELECT id,judge_id,project_a_id,project_b_id,winner_id,assigned_at,submitted_at "
                                     "FROM pairwise_assignments WHERE event_id=? ORDER BY id",),
            "votes": ("SELECT id,voter_user_id,project_id,cast_at FROM ballots WHERE event_id=? ORDER BY id",),
            "comments": ("SELECT id,project_id,user_id,body,created_at,hidden_at,hidden_by FROM comments WHERE event_id=? ORDER BY id",),
            "audit": ("SELECT id,actor_user_id,action,entity_type,entity_id,details_json,created_at "
                      "FROM audit_entries WHERE event_id=? ORDER BY id",),
        }
        archive = {name: [dict(row) for row in db.execute(parts[0], (event_id,)).fetchall()]
                   for name, parts in queries.items()}
    result = {"format": "beyondbug-event-archive-v1", "exported_at": utc_now(), "event": dict(event), **archive}
    return Response(json.dumps(result, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{event_id}-archive.json"'})


def _signing_keys(db) -> tuple[str, str]:
    private = db.execute("SELECT value FROM app_keys WHERE name='judge_record_private_key'").fetchone()
    public = db.execute("SELECT value FROM app_keys WHERE name='judge_record_public_key'").fetchone()
    if private and public:
        return private["value"], public["value"]
    with tempfile.TemporaryDirectory() as directory:
        private_path, public_path = Path(directory) / "private.pem", Path(directory) / "public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_path)],
                       check=True, capture_output=True, timeout=10)
        subprocess.run(["openssl", "pkey", "-in", str(private_path), "-pubout", "-out", str(public_path)],
                       check=True, capture_output=True, timeout=10)
        private_pem, public_pem = private_path.read_text(), public_path.read_text()
    db.execute("INSERT INTO app_keys(name,value) VALUES('judge_record_private_key',?)", (private_pem,))
    db.execute("INSERT INTO app_keys(name,value) VALUES('judge_record_public_key',?)", (public_pem,))
    return private_pem, public_pem


def _ed25519_sign(private_pem: str, payload: bytes) -> str:
    with tempfile.TemporaryDirectory() as directory:
        key, message, signature = (Path(directory) / name for name in ("key.pem", "message.json", "signature.bin"))
        key.write_text(private_pem); message.write_bytes(payload)
        subprocess.run(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(key),
                        "-in", str(message), "-out", str(signature)],
                       check=True, capture_output=True, timeout=10)
        return base64.b64encode(signature.read_bytes()).decode()


@router.post("/api/events/{event_id}/judge-records/issue")
def issue_judge_records(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        event = db.execute("SELECT name,results_published_at FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None or not event["results_published_at"]:
            raise HTTPException(status_code=409, detail="Publish results before issuing judge records")
        judges = db.execute(
            "SELECT j.id,u.name,COUNT(s.id) AS reviews FROM judge_profiles j JOIN users u ON u.id=j.user_id "
            "JOIN judge_assignments a ON a.judge_id=j.id JOIN scorecards s ON s.assignment_id=a.id AND s.status='submitted' "
            "WHERE j.event_id=? GROUP BY j.id HAVING COUNT(s.id)>0 ORDER BY j.id", (event_id,),
        ).fetchall()
        private_pem, public_pem = _signing_keys(db)
        issued, now = [], utc_now()
        for judge in judges:
            record_id = "jrec_" + secrets.token_hex(16)
            payload = json.dumps({"record_id": record_id, "event_id": event_id, "event": event["name"],
                                  "judge_id": judge["id"], "judge": judge["name"],
                                  "submitted_reviews": judge["reviews"], "issued_at": now},
                                 sort_keys=True, separators=(",", ":"))
            signature = _ed25519_sign(private_pem, payload.encode())
            cursor = db.execute(
                "INSERT OR IGNORE INTO judge_participation_records"
                "(id,event_id,judge_id,payload_json,signature_b64,public_key_pem,issued_at) VALUES(?,?,?,?,?,?,?)",
                (record_id, event_id, judge["id"], payload, signature, public_pem, now),
            )
            if cursor.rowcount:
                issued.append(record_id)
        audit(db, event_id, principal.user_id, "judge_records.issued", "event", event_id, {"created": len(issued)})
        db.commit()
    return {"created": issued, "algorithm": "Ed25519"}


@router.get("/api/judge-records/{record_id}")
def public_judge_record(record_id: str):
    with closing(connect()) as db:
        row = db.execute("SELECT payload_json,signature_b64,public_key_pem FROM judge_participation_records WHERE id=?",
                         (record_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Judge participation record not found")
    return {"algorithm": "Ed25519", "payload": json.loads(row["payload_json"]),
            "canonical_payload": row["payload_json"], "signature_base64": row["signature_b64"],
            "public_key_pem": row["public_key_pem"],
            "verification": "Verify the UTF-8 canonical_payload and decoded signature with the supplied Ed25519 public key."}


class WebhookInput(BaseModel):
    url: str = Field(min_length=8, max_length=1000)


def _webhook_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="Webhook URL must be an http(s) URL without credentials")
    return value.strip()


@router.post("/api/events/{event_id}/webhooks", status_code=201)
def create_webhook(event_id: str, payload: WebhookInput, request: Request):
    principal = require_login(request); url = _webhook_url(payload.url)
    webhook_id, secret, now = identifier("wh"), secrets.token_urlsafe(32), utc_now()
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE"); require_event_role(db, principal, event_id, "organizer")
        if db.execute("SELECT COUNT(*) FROM webhooks WHERE event_id=?", (event_id,)).fetchone()[0] >= 10:
            raise HTTPException(status_code=409, detail="An event can configure at most ten webhooks")
        db.execute("INSERT INTO webhooks(id,event_id,url,secret,created_by,created_at) VALUES(?,?,?,?,?,?)",
                   (webhook_id, event_id, url, secret, principal.user_id, now))
        audit(db, event_id, principal.user_id, "webhook.created", "webhook", webhook_id, {"url": url})
        db.commit()
    return {"id": webhook_id, "url": url, "secret": secret,
            "note": "The signing secret is shown once. Store it securely."}


@router.get("/api/events/{event_id}/webhooks")
def list_webhooks(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        rows = db.execute("SELECT id,url,active,created_at FROM webhooks WHERE event_id=? ORDER BY created_at", (event_id,)).fetchall()
    return {"webhooks": [dict(row) for row in rows]}


def emit_webhook_event(event_id: str, event_type: str, data: dict) -> None:
    envelope = {"id": identifier("evtmsg"), "type": event_type, "event_id": event_id,
                "created_at": utc_now(), "data": data}
    payload = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    with closing(connect()) as db:
        hooks = db.execute("SELECT id,url,secret FROM webhooks WHERE event_id=? AND active=1", (event_id,)).fetchall()
        deliveries = []
        for hook in hooks:
            delivery_id = identifier("whd")
            db.execute("INSERT INTO webhook_deliveries(id,webhook_id,event_type,payload_json,status,created_at)"
                       " VALUES(?,?,?,?, 'pending',?)", (delivery_id, hook["id"], event_type, payload, utc_now()))
            deliveries.append((delivery_id, dict(hook)))
        db.commit()
    for delivery_id, hook in deliveries:
        signature = hmac.new(hook["secret"].encode(), payload.encode(), hashlib.sha256).hexdigest()
        request = urllib.request.Request(hook["url"], data=payload.encode(), method="POST",
                                         headers={"Content-Type": "application/json", "X-BeyondBug-Signature": "sha256=" + signature})
        status, error = None, None
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                status = response.status
        except (urllib.error.URLError, TimeoutError, OSError) as failure:
            error = str(failure)[:500]
        with closing(connect()) as db:
            db.execute("UPDATE webhook_deliveries SET status=?,response_code=?,error=?,attempted_at=? WHERE id=?",
                       ("delivered" if status and 200 <= status < 300 else "failed", status, error, utc_now(), delivery_id))
            db.commit()


@router.post("/api/events/{event_id}/webhooks/{webhook_id}/test")
def test_webhook(event_id: str, webhook_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        if db.execute("SELECT 1 FROM webhooks WHERE id=? AND event_id=?", (webhook_id, event_id)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Webhook not found")
    emit_webhook_event(event_id, "webhook.test", {"webhook_id": webhook_id})
    return {"queued_and_attempted": True}


@router.get("/api/events/{event_id}/webhooks/deliveries")
def webhook_deliveries(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        rows = db.execute("SELECT d.id,d.webhook_id,d.event_type,d.status,d.response_code,d.error,d.created_at,d.attempted_at "
                          "FROM webhook_deliveries d JOIN webhooks w ON w.id=d.webhook_id WHERE w.event_id=? "
                          "ORDER BY d.created_at DESC LIMIT 200", (event_id,)).fetchall()
    return {"deliveries": [dict(row) for row in rows]}
