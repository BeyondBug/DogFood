"""Offline Ed25519 participation records for completed judge reviews."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from .auth import require_event_role, require_login
from .core import audit
from .db import connect, database_path, utc_now


router = APIRouter(prefix="/api")


def _key_path() -> Path:
    return database_path().parent / "judge-record-ed25519.pem"


def _ensure_key() -> Path:
    key = _key_path()
    if key.exists():
        return key
    key.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="judge-key-", dir=key.parent)
    os.close(descriptor)
    try:
        result = subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", temporary],
                                capture_output=True, check=False, timeout=10)
        if result.returncode:
            raise RuntimeError("Could not generate judge record signing key")
        os.chmod(temporary, 0o600)
        os.replace(temporary, key)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return key


def _public_key(key: Path) -> str:
    result = subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout"],
                            capture_output=True, check=True, timeout=10)
    return result.stdout.decode("ascii")


def _sign(payload: bytes, key: Path) -> str:
    with tempfile.NamedTemporaryFile() as source:
        source.write(payload)
        source.flush()
        result = subprocess.run(["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(key),
                                 "-in", source.name], capture_output=True, check=True, timeout=10)
    return base64.b64encode(result.stdout).decode("ascii")


def verify_signature(payload: str, signature_b64: str, public_key_pem: str) -> bool:
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        if len(signature) != 64:
            return False
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "payload.json").write_bytes(payload.encode("utf-8"))
            (root / "signature.bin").write_bytes(signature)
            (root / "public.pem").write_text(public_key_pem, encoding="ascii")
            result = subprocess.run(["openssl", "pkeyutl", "-verify", "-rawin", "-pubin",
                                     "-inkey", str(root / "public.pem"), "-in", str(root / "payload.json"),
                                     "-sigfile", str(root / "signature.bin")], capture_output=True,
                                    check=False, timeout=10)
            return result.returncode == 0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


@router.post("/events/{event_id}/judge-records/issue")
def issue_judge_records(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        event = db.execute("SELECT id,name,results_published_at FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        if not event["results_published_at"]:
            raise HTTPException(status_code=409, detail="Publish results before issuing judge records")
        judges = db.execute(
            "SELECT j.id AS judge_id,j.user_id,u.name AS judge_name,COUNT(s.id) AS completed_reviews"
            " FROM judge_profiles j JOIN users u ON u.id=j.user_id"
            " JOIN judge_assignments a ON a.judge_id=j.id"
            " JOIN scorecards s ON s.assignment_id=a.id AND s.status='submitted'"
            " WHERE j.event_id=? GROUP BY j.id HAVING COUNT(s.id)>0 ORDER BY j.id", (event_id,),
        ).fetchall()
        if not judges:
            raise HTTPException(status_code=409, detail="No completed judge reviews")
        key = _ensure_key()
        public_key = _public_key(key)
        issued = []
        for judge in judges:
            prior = db.execute("SELECT id FROM judge_records WHERE event_id=? AND judge_id=?",
                               (event_id, judge["judge_id"])).fetchone()
            if prior:
                continue
            issued_at = utc_now()
            payload = {"schema": "beyondbug-judge-participation-v1", "record_id": "jr_" + uuid4().hex,
                       "event_id": event_id, "event_name": event["name"],
                       "judge_id": judge["judge_id"], "judge_name": judge["judge_name"],
                       "completed_reviews": judge["completed_reviews"], "issued_at": issued_at}
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            signature = _sign(canonical.encode("utf-8"), key)
            db.execute("INSERT INTO judge_records(id,event_id,judge_id,user_id,payload_json,signature_b64,public_key_pem,issued_at)"
                       " VALUES(?,?,?,?,?,?,?,?)",
                       (payload["record_id"], event_id, judge["judge_id"], judge["user_id"], canonical,
                        signature, public_key, issued_at))
            issued.append(payload["record_id"])
        audit(db, event_id, principal.user_id, "judge_records.issued", "event", event_id,
              {"count": len(issued)})
        db.commit()
    return {"issued": issued, "count": len(issued)}


@router.get("/me/judge-records")
def my_judge_records(request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        rows = db.execute("SELECT id,event_id,payload_json FROM judge_records WHERE user_id=? ORDER BY issued_at DESC",
                          (principal.user_id,)).fetchall()
    return {"records": [{"id": row["id"], "event_id": row["event_id"],
                         "payload": json.loads(row["payload_json"])} for row in rows]}


@router.get("/judge-records/{record_id}/verify")
def verify_judge_record(record_id: str):
    with closing(connect()) as db:
        row = db.execute("SELECT payload_json,signature_b64,public_key_pem FROM judge_records WHERE id=?",
                         (record_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Judge record not found")
    return {"verified": verify_signature(row["payload_json"], row["signature_b64"], row["public_key_pem"]),
            "payload": json.loads(row["payload_json"]), "payload_json": row["payload_json"],
            "signature_b64": row["signature_b64"], "public_key_pem": row["public_key_pem"],
            "algorithm": "Ed25519"}
