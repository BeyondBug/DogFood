"""Optional, signed webhook delivery from a durable local audit outbox."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import require_event_role, require_login
from .db import connect, utc_now


router = APIRouter(prefix="/api")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def enqueue_audit(db, event_id: str, audit_id: int, actor: str, action: str,
                  entity: str, entity_id: str, details: dict, created_at: str) -> None:
    """Queue alongside the audited write, in the same SQLite transaction."""
    subscriptions = db.execute("SELECT id FROM webhook_subscriptions WHERE event_id=? AND active=1",
                               (event_id,)).fetchall()
    if not subscriptions:
        return
    payload = json.dumps({"id": audit_id, "event_id": event_id, "actor_user_id": actor,
                          "action": action, "entity_type": entity, "entity_id": entity_id,
                          "details": details, "created_at": created_at},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    for subscription in subscriptions:
        db.execute("INSERT INTO webhook_deliveries(id,subscription_id,event_id,audit_id,payload_json,next_attempt_at)"
                   " VALUES(?,?,?,?,?,?)",
                   ("whd_" + uuid4().hex, subscription["id"], event_id, audit_id, payload, created_at))


def _validate_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.username or parsed.password or not parsed.hostname or parsed.fragment:
        raise HTTPException(status_code=422, detail="Webhook URL must be a host URL without credentials or a fragment")
    if parsed.scheme == "https":
        return value.strip()
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return value.strip()
    raise HTTPException(status_code=422, detail="Webhooks require HTTPS or a loopback HTTP URL")


class WebhookInput(BaseModel):
    url: str = Field(min_length=10, max_length=1000)


@router.post("/events/{event_id}/webhooks", status_code=201)
def create_webhook(event_id: str, payload: WebhookInput, request: Request):
    principal = require_login(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Site administrator access required for outbound webhooks")
    url = _validate_url(payload.url)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        count = db.execute("SELECT COUNT(*) FROM webhook_subscriptions WHERE event_id=? AND active=1",
                           (event_id,)).fetchone()[0]
        if count >= 5:
            raise HTTPException(status_code=409, detail="This event already has five active webhooks")
        subscription_id = "wh_" + uuid4().hex
        secret_hex = secrets.token_hex(32)
        db.execute("INSERT INTO webhook_subscriptions(id,event_id,url,secret_hex,created_by,created_at)"
                   " VALUES(?,?,?,?,?,?)", (subscription_id, event_id, url, secret_hex, principal.user_id, utc_now()))
        from .core import audit
        audit(db, event_id, principal.user_id, "webhook.created", "webhook", subscription_id,
              {"url": url})
        db.commit()
    return {"id": subscription_id, "url": url, "secret_hex": secret_hex,
            "signature_header": "X-BeyondBug-Signature: sha256=<hex HMAC of exact request body>"}


@router.get("/events/{event_id}/webhooks")
def list_webhooks(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        rows = db.execute("SELECT id,url,active,created_at FROM webhook_subscriptions WHERE event_id=? ORDER BY created_at",
                          (event_id,)).fetchall()
    return {"webhooks": [dict(row) for row in rows]}


@router.delete("/events/{event_id}/webhooks/{subscription_id}")
def disable_webhook(event_id: str, subscription_id: str, request: Request):
    principal = require_login(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Site administrator access required for outbound webhooks")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        result = db.execute("UPDATE webhook_subscriptions SET active=0 WHERE id=? AND event_id=? AND active=1",
                            (subscription_id, event_id))
        if not result.rowcount:
            raise HTTPException(status_code=404, detail="Active webhook not found")
        db.execute("UPDATE webhook_deliveries SET status='failed',last_error='Subscription disabled'"
                   " WHERE subscription_id=? AND status='pending'", (subscription_id,))
        from .core import audit
        audit(db, event_id, principal.user_id, "webhook.disabled", "webhook", subscription_id)
        db.commit()
    return {"disabled": True}


@router.get("/events/{event_id}/webhooks/deliveries")
def webhook_deliveries(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        rows = db.execute("SELECT d.id,d.subscription_id,d.audit_id,d.status,d.attempts,"
                          "d.next_attempt_at,d.delivered_at,d.last_error"
                          " FROM webhook_deliveries d WHERE d.event_id=? ORDER BY d.next_attempt_at DESC LIMIT 100",
                          (event_id,)).fetchall()
    return {"deliveries": [dict(row) for row in rows]}


def deliver_due(limit: int = 20) -> int:
    """Deliver outside a database transaction; stable IDs make retries deduplicable."""
    with closing(connect()) as db:
        rows = db.execute("SELECT d.id,d.payload_json,d.attempts,s.url,s.secret_hex,d.event_id"
                          " FROM webhook_deliveries d JOIN webhook_subscriptions s ON s.id=d.subscription_id"
                          " WHERE d.status='pending' AND d.next_attempt_at<=? AND s.active=1"
                          " ORDER BY d.next_attempt_at,d.id LIMIT ?", (utc_now(), limit)).fetchall()
    delivered = 0
    for row in rows:
        body = row["payload_json"].encode("utf-8")
        signature = hmac.new(bytes.fromhex(row["secret_hex"]), body, hashlib.sha256).hexdigest()
        request = urllib.request.Request(row["url"], data=body, method="POST", headers={
            "Content-Type": "application/json", "X-BeyondBug-Event": row["event_id"],
            "X-BeyondBug-Delivery": row["id"], "X-BeyondBug-Signature": "sha256=" + signature,
        })
        error = ""
        try:
            with _opener.open(request, timeout=5) as response:
                if response.status < 200 or response.status >= 300:
                    error = f"HTTP {response.status}"
        except (urllib.error.URLError, TimeoutError, OSError) as failure:
            error = str(failure)[:300]
        attempts = row["attempts"] + 1
        status = "delivered" if not error else "failed" if attempts >= 8 else "pending"
        next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=min(3600, 10 * 2 ** (attempts - 1)))).isoformat()
        with closing(connect()) as db:
            db.execute("UPDATE webhook_deliveries SET status=?,attempts=?,next_attempt_at=?,delivered_at=?,last_error=? WHERE id=? AND status='pending'",
                       (status, attempts, next_attempt, utc_now() if not error else None, error, row["id"]))
            db.commit()
        delivered += not bool(error)
    return delivered


async def delivery_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(deliver_due)
        except Exception:
            # A failed delivery cycle must not stop the portal. Pending rows
            # remain in SQLite and are retried on the next cycle/restart.
            pass
        await asyncio.sleep(10)
