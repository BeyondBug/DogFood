"""Local bearer and cookie sessions with event-scoped role checks."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import hashlib
import secrets
from sqlite3 import Connection

from fastapi import HTTPException, Request

from .db import connect


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    name: str
    is_admin: bool


def _session_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get("session")


def current_principal(request: Request) -> Principal | None:
    token = _session_token(request)
    if not token:
        return None
    with closing(connect()) as db:
        row = db.execute(
            """SELECT u.id,u.email,u.name,u.is_admin,s.expires_at
            FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=?""",
            (sha256(token.encode()).hexdigest(),),
        ).fetchone()
    if row is None:
        return None
    expiry = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    if expiry <= datetime.now(timezone.utc):
        return None
    return Principal(row["id"], row["email"], row["name"], bool(row["is_admin"]))


def require_login(request: Request) -> Principal:
    principal = current_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return principal


def can_create_event(db: Connection, principal: Principal) -> bool:
    """Only installation administrators may create events."""
    return principal.is_admin


def has_event_role(db: Connection, principal: Principal, event_id: str, *roles: str) -> bool:
    if principal.is_admin:
        return True
    placeholders = ",".join("?" for _ in roles)
    row = db.execute(
        f"SELECT 1 FROM event_roles WHERE event_id=? AND user_id=? AND role IN ({placeholders})",
        (event_id, principal.user_id, *roles),
    ).fetchone()
    return row is not None


def require_event_role(db: Connection, principal: Principal, event_id: str, *roles: str) -> None:
    if not has_event_role(db, principal, event_id, *roles):
        raise HTTPException(status_code=403, detail="You do not have access to this event action")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return f"pbkdf2_sha256$260000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algorithm, rounds, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return secrets.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False
