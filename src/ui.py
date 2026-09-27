"""Server-rendered role workspaces backed by the same API permissions."""

from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
import os
import shutil

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .auth import current_principal, require_event_role
from .core import time_value
from .db import connect, database_path
from .scoring import event_ranking, judging_insight
from .audit_view import event_activity
from .public import _eligible, _vote_summary, _window_open, ballot as load_ballot


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _event(db, event_id: str):
    event = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("/account", response_class=HTMLResponse)
def account(request: Request, next: str = ""):
    if current_principal(request):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "account.html", {"principal": None, "next_url": next if next.startswith("/") and not next.startswith("//") else ""})


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    principal = current_principal(request)
    if principal is None:
        return RedirectResponse("/account", status_code=303)
    with closing(connect()) as db:
        roles = db.execute("SELECT r.event_id,r.role,e.name,e.submissions_close FROM event_roles r"
                           " JOIN events e ON e.id=r.event_id WHERE r.user_id=? ORDER BY e.created_at DESC,r.role",
                           (principal.user_id,)).fetchall()
        events = db.execute("SELECT id,name,description,submissions_close FROM events ORDER BY created_at DESC LIMIT 20").fetchall()
    return templates.TemplateResponse(request, "dashboard.html", {
        "principal": principal, "roles": [dict(row) for row in roles], "events": [dict(row) for row in events],
    })


@router.get("/events", response_class=HTMLResponse)
def event_directory(request: Request, q: str = "", page: int = Query(default=1, ge=1)):
    query = q.strip()[:120]
    search = f"%{query}%"
    with closing(connect()) as db:
        total = db.execute(
            "SELECT COUNT(*) FROM events e WHERE e.name LIKE ? OR e.description LIKE ?",
            (search, search),
        ).fetchone()[0]
        page_size = 20
        last_page = max(1, (total + page_size - 1) // page_size)
        current_page = min(page, last_page)
        rows = db.execute(
            "SELECT e.id,e.name,e.description,e.submissions_open,e.submissions_close,"
            "e.results_published_at,"
            "(SELECT COUNT(*) FROM tracks t WHERE t.event_id=e.id) AS track_count,"
            "(SELECT COUNT(*) FROM projects p WHERE p.event_id=e.id AND p.status='submitted') AS project_count"
            " FROM events e WHERE e.name LIKE ? OR e.description LIKE ?"
            " ORDER BY e.created_at DESC,e.id DESC LIMIT ? OFFSET ?",
            (search, search, page_size, (current_page - 1) * page_size),
        ).fetchall()
    now = datetime.now(timezone.utc)
    events = []
    for row in rows:
        event = dict(row)
        event["phase"] = ("Results published" if event["results_published_at"] else
                          "Submissions closed" if now >= time_value(event["submissions_close"]) else
                          "Submissions upcoming" if event["submissions_open"] and now < time_value(event["submissions_open"]) else
                          "Open for submissions")
        events.append(event)
    return templates.TemplateResponse(request, "events.html", {
        "principal": current_principal(request), "events": events, "query": query,
        "total": total, "page": current_page, "last_page": last_page,
        "first_result": (current_page - 1) * page_size + 1 if total else 0,
        "last_result": min(current_page * page_size, total),
    })


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, check: bool = False):
    principal = current_principal(request)
    if principal is None:
        return RedirectResponse("/account", status_code=303)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    with closing(connect()) as db:
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        schema_version = db.execute("PRAGMA user_version").fetchone()[0]
        integrity = db.execute("PRAGMA quick_check(1)").fetchone()[0] if check else None
        events = db.execute("SELECT e.id,e.name,e.created_at,COUNT(DISTINCT p.id) AS projects,"
                            " COUNT(DISTINCT j.id) AS judges FROM events e"
                            " LEFT JOIN projects p ON p.event_id=e.id"
                            " LEFT JOIN judge_profiles j ON j.event_id=e.id"
                            " GROUP BY e.id ORDER BY e.created_at DESC").fetchall()
    path = database_path()
    database_bytes = path.stat().st_size if path.exists() else 0
    free_bytes = shutil.disk_usage(path.parent).free
    return templates.TemplateResponse(request, "admin.html", {
        "principal": principal, "user_count": users, "events": [dict(row) for row in events],
        "system": {"database_bytes": database_bytes, "free_bytes": free_bytes,
                   "schema_version": schema_version, "storage_writable": os.access(path.parent, os.W_OK),
                   "integrity": integrity},
    })


@router.get("/events/{event_id}", response_class=HTMLResponse)
def event_page(event_id: str, request: Request):
    principal = current_principal(request)
    with closing(connect()) as db:
        event = _event(db, event_id)
        tracks = db.execute("SELECT id,name FROM tracks WHERE event_id=? ORDER BY name", (event_id,)).fetchall()
        prizes = db.execute("SELECT id,name,description FROM prizes WHERE event_id=? ORDER BY name", (event_id,)).fetchall()
        projects = db.execute("SELECT p.id,p.title,p.summary,t.name AS track FROM projects p"
                              " JOIN tracks t ON t.id=p.track_id WHERE p.event_id=? AND p.status='submitted'"
                              " ORDER BY p.submitted_at DESC LIMIT 3", (event_id,)).fetchall()
        roles = [row["role"] for row in db.execute("SELECT role FROM event_roles WHERE event_id=? AND user_id=?", (event_id, principal.user_id)).fetchall()] if principal else []
        count = db.execute("SELECT COUNT(*) FROM projects WHERE event_id=? AND status='submitted'", (event_id,)).fetchone()[0]
        can_vote = bool(principal and _window_open(event) and _eligible(db, event, principal.user_id))
    now = datetime.now(timezone.utc)
    closed = now >= datetime.fromisoformat(event["submissions_close"].replace("Z", "+00:00"))
    if event["results_published_at"]:
        phase_index = 4
    elif closed:
        phase_index = 3
    elif event["submissions_open"] and now < datetime.fromisoformat(event["submissions_open"].replace("Z", "+00:00")):
        phase_index = 1
    else:
        phase_index = 2
    return templates.TemplateResponse(request, "event.html", {
        "principal": principal, "event": dict(event), "tracks": [dict(row) for row in tracks],
        "prizes": [dict(row) for row in prizes], "projects": [dict(row) for row in projects],
        "roles": roles, "project_count": count, "closed": closed, "phase_index": phase_index,
        "can_vote": can_vote, "voting_open": _window_open(event),
    })


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_page(project_id: str, request: Request):
    principal = current_principal(request)
    with closing(connect()) as db:
        project = db.execute("SELECT p.*,t.name AS team,tr.name AS track,e.name AS event_name,"
                             " e.voting_mode,e.voting_open,e.voting_close"
                             " FROM projects p JOIN teams t ON t.id=p.team_id"
                             " JOIN tracks tr ON tr.id=p.track_id JOIN events e ON e.id=p.event_id"
                             " WHERE p.id=? AND p.status='submitted'", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        comments = db.execute("SELECT c.id,c.body,c.created_at,u.name AS author"
                              " FROM comments c JOIN users u ON u.id=c.user_id"
                              " WHERE c.project_id=? AND c.hidden_at IS NULL ORDER BY c.created_at,c.id LIMIT 200",
                              (project_id,)).fetchall()
        is_organizer = bool(principal and db.execute("SELECT 1 FROM event_roles WHERE event_id=? AND user_id=? AND role='organizer'",
                                                      (project["event_id"], principal.user_id)).fetchone())
    return templates.TemplateResponse(request, "project.html", {
        "principal": principal, "project": dict(project), "comments": [dict(row) for row in comments],
        "comments_open": _window_open(project), "is_organizer": is_organizer,
    })


@router.get("/workspace/{event_id}", response_class=HTMLResponse)
def participant_workspace(event_id: str, request: Request):
    principal = current_principal(request)
    if principal is None:
        return RedirectResponse("/account", status_code=303)
    with closing(connect()) as db:
        event = _event(db, event_id)
        require_event_role(db, principal, event_id, "participant")
        tracks = db.execute("SELECT id,name FROM tracks WHERE event_id=? ORDER BY name", (event_id,)).fetchall()
        team = db.execute("SELECT t.id,t.name FROM teams t JOIN team_members m ON m.team_id=t.id"
                          " WHERE t.event_id=? AND m.user_id=?", (event_id, principal.user_id)).fetchone()
        members = db.execute("SELECT u.name,m.role FROM team_members m JOIN users u ON u.id=m.user_id WHERE m.team_id=? ORDER BY m.joined_at",
                             (team["id"],)).fetchall() if team else []
        project = db.execute("SELECT * FROM projects WHERE team_id=? ORDER BY updated_at DESC LIMIT 1", (team["id"],)).fetchone() if team else None
        certificates = db.execute(
            "SELECT c.id,c.kind,pr.name AS prize_name FROM certificates c"
            " LEFT JOIN prizes pr ON pr.id=c.prize_id WHERE c.event_id=? AND c.user_id=?"
            " ORDER BY c.kind,c.id", (event_id, principal.user_id),
        ).fetchall()
    now = datetime.now(timezone.utc)
    closed = bool(event["results_published_at"] or now >= time_value(event["submissions_close"]))
    not_open = bool(event["submissions_open"] and now < time_value(event["submissions_open"]))
    return templates.TemplateResponse(request, "participant.html", {
        "principal": principal, "event": dict(event), "tracks": [dict(row) for row in tracks],
        "team": dict(team) if team else None, "members": [dict(row) for row in members],
        "project": dict(project) if project else None, "can_edit": not closed and not not_open,
        "team_editable": not closed,
        "closed": closed, "not_open": not_open,
        "certificates": [dict(row) for row in certificates],
    })


@router.get("/judge/{event_id}", response_class=HTMLResponse)
def judge_workspace(event_id: str, request: Request):
    principal = current_principal(request)
    if principal is None:
        return RedirectResponse("/account", status_code=303)
    with closing(connect()) as db:
        event = _event(db, event_id)
        require_event_role(db, principal, event_id, "judge")
        judge = db.execute("SELECT id FROM judge_profiles WHERE event_id=? AND user_id=?", (event_id, principal.user_id)).fetchone()
        if judge is None:
            raise HTTPException(status_code=403, detail="Judge profile not found")
        rubric = db.execute("SELECT id,name,version FROM rubrics WHERE event_id=? AND is_active=1", (event_id,)).fetchone()
        criteria = db.execute("SELECT slug,name,weight,max_score FROM rubric_criteria WHERE rubric_id=? ORDER BY sort_order", (rubric["id"],)).fetchall() if rubric else []
        assignments = db.execute("SELECT a.id,p.id AS project_id,p.title,p.summary,p.description,p.repo_url,p.demo_url,t.name AS track,"
                                 " s.status,s.comment FROM judge_assignments a JOIN projects p ON p.id=a.project_id"
                                 " JOIN tracks t ON t.id=p.track_id LEFT JOIN scorecards s ON s.assignment_id=a.id"
                                 " WHERE a.judge_id=? ORDER BY CASE s.status WHEN 'submitted' THEN 2 WHEN 'draft' THEN 1 ELSE 0 END,p.title",
                                 (judge["id"],)).fetchall()
        items = []
        for row in assignments:
            item = dict(row)
            scores = db.execute("SELECT c.slug,cs.score FROM criterion_scores cs"
                                " JOIN rubric_criteria c ON c.id=cs.criterion_id"
                                " JOIN scorecards s ON s.id=cs.scorecard_id WHERE s.assignment_id=?", (row["id"],)).fetchall()
            item["scores"] = {score["slug"]: score["score"] for score in scores}
            items.append(item)
    now = datetime.now(timezone.utc)
    judging_editable = not event["results_published_at"] and now >= time_value(event["submissions_close"])
    if event["judging_open"]:
        judging_editable = judging_editable and now >= time_value(event["judging_open"])
    if event["judging_close"]:
        judging_editable = judging_editable and now < time_value(event["judging_close"])
    return templates.TemplateResponse(request, "judge.html", {
        "principal": principal, "event": dict(event), "rubric": dict(rubric) if rubric else None,
        "criteria": [dict(row) for row in criteria], "assignments": items, "judge_id": judge["id"],
        "submitted_count": sum(item["status"] == "submitted" for item in items),
        "judging_editable": judging_editable,
    })


@router.get("/organizer/{event_id}", response_class=HTMLResponse)
def organizer_workspace(event_id: str, request: Request, activity: str = "All"):
    principal = current_principal(request)
    if principal is None:
        return RedirectResponse("/account", status_code=303)
    with closing(connect()) as db:
        event = _event(db, event_id)
        require_event_role(db, principal, event_id, "organizer")
        tracks = db.execute("SELECT id,name FROM tracks WHERE event_id=? ORDER BY name", (event_id,)).fetchall()
        judges = db.execute("SELECT j.id,u.name,u.email,COUNT(a.id) AS assigned,"
                            " SUM(CASE WHEN s.status='submitted' THEN 1 ELSE 0 END) AS submitted"
                            " FROM judge_profiles j JOIN users u ON u.id=j.user_id"
                            " LEFT JOIN judge_assignments a ON a.judge_id=j.id"
                            " LEFT JOIN scorecards s ON s.assignment_id=a.id"
                            " WHERE j.event_id=? GROUP BY j.id ORDER BY u.name", (event_id,)).fetchall()
        judge_items = []
        for row in judges:
            item = dict(row)
            item["track_ids"] = {entry["track_id"] for entry in db.execute(
                "SELECT track_id FROM judge_tracks WHERE judge_id=?", (row["id"],))}
            judge_items.append(item)
        invite_rows = db.execute("SELECT email,expires_at,accepted_at FROM judge_invites"
                                 " WHERE event_id=? ORDER BY expires_at DESC", (event_id,)).fetchall()
        coverage = db.execute("SELECT p.id,p.title,p.duplicate_of,COUNT(a.id) AS assigned,"
                              " SUM(CASE WHEN s.status='submitted' THEN 1 ELSE 0 END) AS submitted"
                              " FROM projects p LEFT JOIN judge_assignments a ON a.project_id=p.id"
                              " LEFT JOIN scorecards s ON s.assignment_id=a.id"
                              " WHERE p.event_id=? AND p.status='submitted' GROUP BY p.id ORDER BY p.title", (event_id,)).fetchall()
        rubric = db.execute("SELECT id,name,version FROM rubrics WHERE event_id=? AND is_active=1", (event_id,)).fetchone()
        criteria = db.execute("SELECT slug,name,weight FROM rubric_criteria WHERE rubric_id=? ORDER BY sort_order", (rubric["id"],)).fetchall() if rubric else []
        ranking = event_ranking(db, event_id)
        insight = judging_insight(db, event_id, ranking)
        activity_filter = activity if activity in ("All", "Judging", "Voting", "Certificates", "Event and submissions") else "All"
        audit = event_activity(db, event_id, activity_filter)
        vote_summary = _vote_summary(db, event_id)
        prizes = db.execute(
            "SELECT pr.id,pr.name,a.project_id,p.title AS winner_title,"
            "(SELECT COUNT(*) FROM certificates c WHERE c.prize_id=pr.id) AS issued_count"
            " FROM prizes pr LEFT JOIN event_awards a ON a.prize_id=pr.id"
            " LEFT JOIN projects p ON p.id=a.project_id WHERE pr.event_id=? ORDER BY pr.id",
            (event_id,),
        ).fetchall()
        eligible_projects = db.execute(
            "SELECT id,title FROM projects WHERE event_id=? AND status='submitted'"
            " AND duplicate_of IS NULL ORDER BY title,id", (event_id,),
        ).fetchall()
        certificate_count = db.execute("SELECT COUNT(*) FROM certificates WHERE event_id=?", (event_id,)).fetchone()[0]
    now = datetime.now(timezone.utc)
    judge_invites = [{**dict(row), "status": ("Accepted" if row["accepted_at"] else
                     "Expired" if time_value(row["expires_at"]) <= now else "Pending")}
                     for row in invite_rows]
    pending_invites = sum(row["status"] == "Pending" for row in judge_invites)
    submissions_closed = now >= time_value(event["submissions_close"])
    unique_coverage = [row for row in coverage if row["duplicate_of"] is None]
    coverage_gaps = sum(row["assigned"] == 0 for row in unique_coverage)
    incomplete_reviews = sum(max(0, row["assigned"] - row["submitted"]) for row in unique_coverage)
    setup_checks = [
        {"label": "Event description", "ok": bool(event["description"].strip()), "href": "#event-settings"},
        {"label": "Submission deadline", "ok": bool(event["submissions_close"]), "href": "#event-settings"},
        {"label": "At least one track", "ok": bool(tracks), "href": "#event-settings"},
        {"label": "Judging rubric", "ok": rubric is not None, "href": "#rubric-and-assignments"},
        {"label": "At least one accepted judge", "ok": bool(judges), "href": "#judges"},
    ]
    if not rubric:
        next_action = {"label": "Configure rubric", "href": "#rubric-and-assignments",
                       "reason": "Judges need a scoring method before assignments begin."}
    elif not judges:
        next_action = {"label": "Invite judges", "href": "#judges",
                       "reason": "An accepted judge is needed before reviews can be assigned."}
    elif not submissions_closed:
        next_action = {"label": "Review submissions", "href": "#review-coverage",
                       "reason": "Assignments open after the submission deadline."}
    elif coverage_gaps:
        next_action = {"label": "Fix assignments", "href": "#rubric-and-assignments",
                       "reason": f"{coverage_gaps} submitted projects have no assigned judge."}
    elif incomplete_reviews:
        next_action = {"label": "View judging progress", "href": "#review-coverage",
                       "reason": f"{incomplete_reviews} assigned reviews remain unfinished."}
    elif not event["results_published_at"]:
        next_action = {"label": "Review final rankings", "href": "#private-rankings",
                       "reason": "Coverage is complete. Inspect the ranking before publication."}
    else:
        next_action = {"label": "Issue certificates", "href": "#certificates",
                       "reason": "Results are public. Record winners and issue certificates."}
    return templates.TemplateResponse(request, "organizer.html", {
        "principal": principal, "event": dict(event), "tracks": [dict(row) for row in tracks],
        "judges": judge_items, "coverage": [dict(row) for row in coverage],
        "rubric": dict(rubric) if rubric else None, "criteria": [dict(row) for row in criteria],
        "ranking": ranking, "insight": insight, "audit": audit,
        "activity_filter": activity_filter, "vote_summary": vote_summary,
        "submissions_closed": submissions_closed,
        "prizes": [dict(row) for row in prizes], "eligible_projects": [dict(row) for row in eligible_projects],
        "certificate_count": certificate_count,
        "setup_checks": setup_checks, "next_action": next_action,
        "pending_invites": pending_invites, "coverage_gaps": coverage_gaps,
        "incomplete_reviews": incomplete_reviews,
        "judge_invites": judge_invites[:30], "judge_invite_total": len(judge_invites),
    })


@router.get("/results/{event_id}", response_class=HTMLResponse)
def results_page(event_id: str, request: Request):
    with closing(connect()) as db:
        event = _event(db, event_id)
        if event["results_published_at"] is None:
            raise HTTPException(status_code=404, detail="Results are not published")
        ranking = event_ranking(db, event_id)
        vote_summary = _vote_summary(db, event_id) if event["voting_mode"] != "disabled" else None
    return templates.TemplateResponse(request, "results.html", {
        "principal": current_principal(request), "event": dict(event), "ranking": ranking,
        "vote_summary": vote_summary,
    })


@router.get("/vote/{event_id}", response_class=HTMLResponse)
def ballot_page(event_id: str, request: Request):
    principal = current_principal(request)
    if principal is None:
        return RedirectResponse(f"/account?next=/vote/{event_id}", status_code=303)
    ballot_data = load_ballot(event_id, request)
    with closing(connect()) as db:
        event = _event(db, event_id)
    return templates.TemplateResponse(request, "ballot.html", {
        "principal": principal, "event": dict(event), "ballot": ballot_data,
    })


@router.get("/join/{token}", response_class=HTMLResponse)
def team_invite_page(token: str, request: Request):
    with closing(connect()) as db:
        invitation = db.execute("SELECT t.name AS team,e.name AS event,e.submissions_close,"
                                "i.expires_at,i.revoked_at,i.uses,i.max_uses FROM team_invites i"
                                " JOIN teams t ON t.id=i.team_id JOIN events e ON e.id=t.event_id"
                                " WHERE i.token_hash=?", (sha256(token.encode()).hexdigest(),)).fetchone()
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    now = datetime.now(timezone.utc)
    available = (not invitation["revoked_at"] and invitation["uses"] < invitation["max_uses"]
                 and now < time_value(invitation["expires_at"])
                 and now < time_value(invitation["submissions_close"]))
    return templates.TemplateResponse(request, "invite.html", {
        "principal": current_principal(request), "kind": "team", "token": token,
        "title": invitation["team"], "event_name": invitation["event"],
        "available": available,
    })


@router.get("/judge-invite/{token}", response_class=HTMLResponse)
def judge_invite_page(token: str, request: Request):
    with closing(connect()) as db:
        invitation = db.execute("SELECT i.email,e.name AS event FROM judge_invites i"
                                " JOIN events e ON e.id=i.event_id WHERE i.token_hash=?",
                                (sha256(token.encode()).hexdigest(),)).fetchone()
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    return templates.TemplateResponse(request, "invite.html", {
        "principal": current_principal(request), "kind": "judge", "token": token,
        "title": invitation["email"], "event_name": invitation["event"],
    })


@router.get("/vote-invite/{token}", response_class=HTMLResponse)
def voter_invite_page(token: str, request: Request):
    with closing(connect()) as db:
        invitation = db.execute("SELECT i.email,e.name AS event FROM voter_invites i"
                                " JOIN events e ON e.id=i.event_id WHERE i.token_hash=?",
                                (sha256(token.encode()).hexdigest(),)).fetchone()
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    return templates.TemplateResponse(request, "invite.html", {
        "principal": current_principal(request), "kind": "voter", "token": token,
        "title": invitation["email"], "event_name": invitation["event"],
    })
