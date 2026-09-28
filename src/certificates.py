"""Organizer-issued, database-verifiable participant and winner records."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Literal
from uuid import uuid4
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .auth import current_principal, require_event_role, require_login
from .core import audit
from .db import connect, utc_now


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class WinnerSelection(BaseModel):
    project_id: str


class DesignInput(BaseModel):
    layout: Literal["classic", "modern", "bold"]
    palette: Literal["teal", "blue", "coral", "gold", "violet"]
    issuer_line: str = Field(min_length=2, max_length=48)


DEFAULT_DESIGNS = {
    "participant": {"layout": "classic", "palette": "teal", "issuer_line": "BEYONDBUG"},
    "winner": {"layout": "classic", "palette": "gold", "issuer_line": "BEYONDBUG"},
}


def _admin(request: Request):
    principal = require_login(request)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return principal


def _design(db, event_id: str, kind: str) -> dict:
    row = db.execute(
        "SELECT layout,palette,issuer_line FROM certificate_designs WHERE event_id=? AND kind=?",
        (event_id, kind),
    ).fetchone()
    return dict(row) if row else DEFAULT_DESIGNS[kind].copy()


def _record(db, certificate_id: str):
    record = db.execute(
        "SELECT c.id,c.event_id,c.user_id,c.project_id,c.kind,c.prize_id,c.issued_at,c.design_json,"
        "u.name AS recipient_name,e.name AS event_name,p.title AS project_title,"
        "t.name AS team_name,pr.name AS prize_name"
        " FROM certificates c JOIN users u ON u.id=c.user_id"
        " JOIN events e ON e.id=c.event_id JOIN projects p ON p.id=c.project_id"
        " JOIN teams t ON t.id=p.team_id LEFT JOIN prizes pr ON pr.id=c.prize_id"
        " WHERE c.id=?",
        (certificate_id,),
    ).fetchone()
    if record is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    result = dict(record)
    result["design"] = json.loads(result.pop("design_json")) or DEFAULT_DESIGNS[result["kind"]].copy()
    return result


@router.get("/admin/certificates", response_class=HTMLResponse)
def certificate_studio(request: Request, event_id: str = ""):
    principal = current_principal(request)
    if principal is None:
        return RedirectResponse("/account", status_code=303)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    with closing(connect()) as db:
        events = db.execute("SELECT id,name FROM events ORDER BY created_at DESC,id").fetchall()
        selected = event_id or (events[0]["id"] if events else "")
        if selected and not any(row["id"] == selected for row in events):
            raise HTTPException(status_code=404, detail="Event not found")
        designs = {kind: _design(db, selected, kind) for kind in DEFAULT_DESIGNS} if selected else {}
    return templates.TemplateResponse(request, "certificate_studio.html", {
        "principal": principal, "events": [dict(row) for row in events],
        "event_id": selected, "designs": designs,
    }, headers={"Cache-Control": "no-store"})


@router.put("/api/admin/events/{event_id}/certificate-designs/{kind}")
def save_certificate_design(event_id: str, kind: str, payload: DesignInput, request: Request):
    principal = _admin(request)
    if kind not in DEFAULT_DESIGNS:
        raise HTTPException(status_code=404, detail="Certificate template not found")
    issuer = payload.issuer_line.strip()
    if len(issuer) < 2:
        raise HTTPException(status_code=422, detail="Enter an issuer name")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Event not found")
        design = {"layout": payload.layout, "palette": payload.palette, "issuer_line": issuer}
        db.execute(
            "INSERT INTO certificate_designs(event_id,kind,layout,palette,issuer_line,updated_by,updated_at)"
            " VALUES(?,?,?,?,?,?,?) ON CONFLICT(event_id,kind) DO UPDATE SET"
            " layout=excluded.layout,palette=excluded.palette,issuer_line=excluded.issuer_line,"
            " updated_by=excluded.updated_by,updated_at=excluded.updated_at",
            (event_id, kind, payload.layout, payload.palette, issuer, principal.user_id, utc_now()),
        )
        audit(db, event_id, principal.user_id, "certificate.design_updated", "certificate_design", kind, design)
        db.commit()
    return {"kind": kind, "design": design}


@router.put("/api/events/{event_id}/prizes/{prize_id}/winner")
def select_winner(event_id: str, prize_id: str, payload: WinnerSelection, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        event = db.execute("SELECT results_published_at FROM events WHERE id=?", (event_id,)).fetchone()
        if not event["results_published_at"]:
            raise HTTPException(status_code=409, detail="Publish results before assigning prizes")
        prize = db.execute("SELECT id FROM prizes WHERE id=? AND event_id=?", (prize_id, event_id)).fetchone()
        project = db.execute(
            "SELECT id FROM projects WHERE id=? AND event_id=? AND status='submitted' AND duplicate_of IS NULL",
            (payload.project_id, event_id),
        ).fetchone()
        if prize is None or project is None:
            raise HTTPException(status_code=404, detail="Prize or eligible project not found")
        existing = db.execute("SELECT project_id FROM event_awards WHERE prize_id=?", (prize_id,)).fetchone()
        issued = db.execute("SELECT 1 FROM certificates WHERE event_id=? AND prize_id=? LIMIT 1",
                            (event_id, prize_id)).fetchone()
        if issued and existing and existing["project_id"] != payload.project_id:
            raise HTTPException(status_code=409, detail="This prize already has issued certificates")
        if not existing or existing["project_id"] != payload.project_id:
            now = utc_now()
            db.execute(
                "INSERT INTO event_awards(prize_id,event_id,project_id,assigned_by,assigned_at)"
                " VALUES(?,?,?,?,?) ON CONFLICT(prize_id) DO UPDATE SET"
                " project_id=excluded.project_id,assigned_by=excluded.assigned_by,assigned_at=excluded.assigned_at",
                (prize_id, event_id, payload.project_id, principal.user_id, now),
            )
            audit(db, event_id, principal.user_id, "prize.winner_selected", "prize", prize_id,
                  {"project_id": payload.project_id})
            db.commit()
    return {"prize_id": prize_id, "project_id": payload.project_id}


@router.post("/api/events/{event_id}/certificates/issue")
def issue_certificates(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        event = db.execute("SELECT results_published_at FROM events WHERE id=?", (event_id,)).fetchone()
        if not event["results_published_at"]:
            raise HTTPException(status_code=409, detail="Publish results before issuing certificates")
        participants = db.execute(
            "SELECT m.user_id,p.id AS project_id FROM projects p"
            " JOIN team_members m ON m.team_id=p.team_id"
            " WHERE p.event_id=? AND p.status='submitted' ORDER BY p.id,m.user_id",
            (event_id,),
        ).fetchall()
        winners = db.execute(
            "SELECT m.user_id,a.project_id,a.prize_id FROM event_awards a"
            " JOIN projects p ON p.id=a.project_id JOIN team_members m ON m.team_id=p.team_id"
            " WHERE a.event_id=? ORDER BY a.prize_id,m.user_id",
            (event_id,),
        ).fetchall()
        created = {"participant": 0, "winner": 0}
        designs = {kind: json.dumps(_design(db, event_id, kind), sort_keys=True)
                   for kind in ("participant", "winner")}
        now = utc_now()
        for kind, rows in (("participant", participants), ("winner", winners)):
            for row in rows:
                cursor = db.execute(
                    "INSERT OR IGNORE INTO certificates(id,event_id,user_id,project_id,kind,prize_id,issued_at,design_json)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    ("cert_" + uuid4().hex, event_id, row["user_id"], row["project_id"],
                     kind, row["prize_id"] if kind == "winner" else None, now, designs[kind]),
                )
                created[kind] += cursor.rowcount
        audit(db, event_id, principal.user_id, "certificates.issued", "event", event_id, created)
        db.commit()
    return {"created": created, "total_created": sum(created.values())}


@router.get("/api/events/{event_id}/certificates")
def event_certificates(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        rows = db.execute(
            "SELECT c.id,c.kind,c.issued_at,u.name AS recipient_name,p.title AS project_title,"
            "pr.name AS prize_name FROM certificates c JOIN users u ON u.id=c.user_id"
            " JOIN projects p ON p.id=c.project_id LEFT JOIN prizes pr ON pr.id=c.prize_id"
            " WHERE c.event_id=? ORDER BY c.kind,c.issued_at,c.id", (event_id,),
        ).fetchall()
    return {"certificates": [dict(row) for row in rows]}


@router.get("/api/me/certificates")
def own_certificates(request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        rows = db.execute(
            "SELECT c.id,c.kind,c.issued_at,e.name AS event_name,p.title AS project_title,"
            "pr.name AS prize_name FROM certificates c JOIN events e ON e.id=c.event_id"
            " JOIN projects p ON p.id=c.project_id LEFT JOIN prizes pr ON pr.id=c.prize_id"
            " WHERE c.user_id=? ORDER BY c.issued_at DESC,c.id", (principal.user_id,),
        ).fetchall()
    return {"certificates": [dict(row) for row in rows]}


@router.get("/my/certificates", response_class=HTMLResponse)
def own_certificate_page(request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        rows = db.execute(
            "SELECT c.id,c.kind,c.issued_at,e.name AS event_name,p.title AS project_title,"
            "pr.name AS prize_name FROM certificates c JOIN events e ON e.id=c.event_id"
            " JOIN projects p ON p.id=c.project_id LEFT JOIN prizes pr ON pr.id=c.prize_id"
            " WHERE c.user_id=? ORDER BY c.issued_at DESC,c.id", (principal.user_id,),
        ).fetchall()
    return templates.TemplateResponse(request, "my_certificates.html", {
        "principal": principal, "certificates": [dict(row) for row in rows],
    })


def _certificate_svg(record: dict, *, preview: bool = False) -> str:
    winner = record["kind"] == "winner"
    design = record.get("design") or DEFAULT_DESIGNS[record["kind"]]
    layout = design.get("layout", "classic")
    palette = design.get("palette", DEFAULT_DESIGNS[record["kind"]]["palette"])
    colors = ({"teal": "#72ded0", "blue": "#a9bcff", "coral": "#ff9b8b", "gold": "#e7c77a", "violet": "#c3a5ff"}
              if winner else
              {"teal": "#167d78", "blue": "#304db8", "coral": "#b93e39", "gold": "#876300", "violet": "#6944a8"})
    paper, ink, muted = (("#102535", "#f8f7ef", "#aec1c8") if winner
                         else ("#f7faf7", "#102b38", "#547077"))
    accent = colors.get(palette, colors[DEFAULT_DESIGNS[record["kind"]]["palette"]])
    title = "Certificate of distinction" if winner else "Certificate of participation"
    lead = "AWARD RECIPIENT" if winner else "EVENT PARTICIPANT"
    detail = (record["prize_name"] or "Award winner") if winner else "For building and submitting"
    recipient = escape(record["recipient_name"])
    event_name = escape(record["event_name"])
    project = escape(record["project_title"])
    team = escape(record["team_name"])
    detail = escape(detail)
    issued = escape(record["issued_at"][:10])
    code = escape(record["id"])
    issuer = escape(design.get("issuer_line", "BEYONDBUG")[:48])
    record_label = f"{issuer} / TEMPLATE PREVIEW" if preview else f"{issuer} / OFFICIAL RECORD"
    issued_line = "SAMPLE · NOT ISSUED" if preview else f"ISSUED {issued} UTC"
    verify_line = "NO VERIFICATION CODE" if preview else f"VERIFY /certificates/{code}"
    preview_mark = ('<rect x="325" y="768" width="550" height="34" fill="' + accent +
                    '"/><text x="600" y="792" fill="' + paper +
                    '" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" font-weight="700" letter-spacing="2">SAMPLE TEMPLATE · NOT A CERTIFICATE</text>') if preview else ""
    side = "#183b4c" if winner else "#e3f0ec"
    if layout == "modern":
        decoration = (f'<rect x="28" y="28" width="1144" height="22" fill="{accent}"/>'
                      f'<rect x="28" y="800" width="1144" height="22" fill="{accent}"/>'
                      f'<rect x="28" y="50" width="1144" height="750" fill="none" stroke="{accent}" stroke-width="1"/>')
    elif layout == "bold":
        decoration = (f'<rect x="28" y="28" width="1144" height="794" fill="none" stroke="{accent}" stroke-width="7"/>'
                      f'<rect x="45" y="45" width="24" height="760" fill="{accent}"/>'
                      f'<path d="M965 45h190v190zM925 805h230V575z" fill="{side}"/>')
    else:
        decoration = (f'<rect x="28" y="28" width="1144" height="794" fill="none" stroke="{accent}" stroke-width="2"/>'
                      f'<rect x="48" y="48" width="14" height="754" fill="{accent}"/>'
                      f'<path d="M 1000 48 L 1152 48 L 1152 200 Z" fill="{side}"/>')
    recipient_size = 65 if len(record["recipient_name"]) < 25 else 48 if len(record["recipient_name"]) < 36 else 36
    project_size = 31 if len(record["project_title"]) < 42 else 24
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="850" viewBox="0 0 1200 850" role="img" aria-labelledby="title description">
<title id="title">{title} for {recipient}</title><desc id="description">{'Sample template for ' + event_name if preview else 'Issued by ' + event_name + ' for ' + project + '. Verification code ' + code}.</desc>
<rect width="1200" height="850" fill="{paper}"/>{decoration}
<circle cx="1062" cy="126" r="50" fill="none" stroke="{accent}" stroke-width="2"/><path d="M1042 126h40M1062 106v40" stroke="{accent}" stroke-width="3"/>
<text x="102" y="112" fill="{accent}" font-family="Arial, sans-serif" font-size="20" font-weight="700" letter-spacing="3">{record_label}</text>
<line x1="102" y1="143" x2="930" y2="143" stroke="{accent}" stroke-width="2"/>
<text x="102" y="225" fill="{muted}" font-family="Arial, sans-serif" font-size="18" font-weight="700" letter-spacing="3">{lead}</text>
<text x="102" y="288" fill="{ink}" font-family="Arial, sans-serif" font-size="45" font-weight="700">{title}</text>
<text x="102" y="388" fill="{accent}" font-family="Arial, sans-serif" font-size="20">Presented to</text>
<text x="102" y="465" fill="{ink}" font-family="Arial, sans-serif" font-size="{recipient_size}" font-weight="700">{recipient}</text>
<line x1="102" y1="493" x2="1096" y2="493" stroke="{accent}" stroke-width="1"/>
<text x="102" y="549" fill="{muted}" font-family="Arial, sans-serif" font-size="20">{detail}</text>
<text x="102" y="601" fill="{ink}" font-family="Arial, sans-serif" font-size="{project_size}" font-weight="700">{project}</text>
<text x="102" y="645" fill="{muted}" font-family="Arial, sans-serif" font-size="21">Team {team} · {event_name}</text>
<line x1="102" y1="701" x2="1096" y2="701" stroke="{accent}" stroke-width="1"/>
<text x="102" y="745" fill="{muted}" font-family="Arial, sans-serif" font-size="17">{issued_line}</text>
<text x="1096" y="745" fill="{muted}" text-anchor="end" font-family="Arial, sans-serif" font-size="17">{verify_line}</text>
{preview_mark}
</svg>'''


@router.get("/events/{event_id}/certificates/preview/{kind}.svg")
def preview_certificate(
    event_id: str, kind: str, request: Request,
    layout: Literal["classic", "modern", "bold"] | None = None,
    palette: Literal["teal", "blue", "coral", "gold", "violet"] | None = None,
    issuer_line: str | None = Query(default=None, min_length=2, max_length=48),
):
    """Render an admin-only sample without issuing any record."""
    _admin(request)
    if kind not in ("participant", "winner"):
        raise HTTPException(status_code=404, detail="Certificate template not found")
    with closing(connect()) as db:
        event = db.execute("SELECT name FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        design = _design(db, event_id, kind)
        project = db.execute(
            "SELECT p.title,t.name AS team_name,u.name AS member_name FROM projects p"
            " JOIN teams t ON t.id=p.team_id LEFT JOIN team_members m ON m.team_id=t.id"
            " LEFT JOIN users u ON u.id=m.user_id"
            " WHERE p.event_id=? AND p.status='submitted' ORDER BY p.id,u.name LIMIT 1",
            (event_id,),
        ).fetchone()
        prize = db.execute("SELECT name FROM prizes WHERE event_id=? ORDER BY id LIMIT 1", (event_id,)).fetchone()
    if layout is not None:
        design["layout"] = layout
    if palette is not None:
        design["palette"] = palette
    if issuer_line is not None:
        issuer = issuer_line.strip()
        if len(issuer) < 2:
            raise HTTPException(status_code=422, detail="Enter an issuer name")
        design["issuer_line"] = issuer
    sample = {
        "id": "PREVIEW-NOT-VALID", "kind": kind, "event_name": event["name"],
        "recipient_name": project["member_name"] if project and project["member_name"] else "Sample Recipient",
        "project_title": project["title"] if project else "Sample project",
        "team_name": project["team_name"] if project else "Sample team",
        "prize_name": prize["name"] if prize else "Award winner",
        "issued_at": utc_now(),
        "design": design,
    }
    return Response(_certificate_svg(sample, preview=True), media_type="image/svg+xml", headers={
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        "Cache-Control": "no-store",
    })


@router.get("/certificates/{certificate_id}.svg")
def download_certificate(certificate_id: str):
    with closing(connect()) as db:
        record = _record(db, certificate_id)
    return Response(_certificate_svg(record), media_type="image/svg+xml", headers={
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    })


@router.get("/certificates/{certificate_id}", response_class=HTMLResponse)
def certificate_page(certificate_id: str, request: Request):
    with closing(connect()) as db:
        record = _record(db, certificate_id)
    return templates.TemplateResponse(request, "certificate.html", {
        "principal": current_principal(request), "certificate": record,
    })


@router.get("/api/certificates/{certificate_id}/verify")
def verify_certificate(certificate_id: str):
    with closing(connect()) as db:
        record = _record(db, certificate_id)
    return {"verified": True, "id": record["id"], "kind": record["kind"],
            "recipient": record["recipient_name"], "event": record["event_name"],
            "project": record["project_title"], "prize": record["prize_name"],
            "issued_at": record["issued_at"]}
