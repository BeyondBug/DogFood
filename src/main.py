"""BeyondBug's local hackathon portal."""

from __future__ import annotations

import csv
import io
import json
import uuid
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .auth import current_principal, has_event_role, require_event_role, require_login
from .core import audit, csv_safe, reconcile_submitted_duplicates, require_web_url, router as core_router
from .judging import router as judging_router
from .public import router as public_router
from .certificates import router as certificate_router
from .stretch import router as stretch_router
from .submission_questions import router as submission_questions_router, validate_answers, save_answers
from .portable_bundle import router as portable_bundle_router
from .ui import router as ui_router
from .db import connect, initialize, utc_now
from .seed import seed


ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    seed()
    yield


app = FastAPI(title="BeyondBug", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
app.include_router(core_router)
app.include_router(ui_router)
app.include_router(submission_questions_router)
app.include_router(portable_bundle_router)


@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin and origin != expected:
            return JSONResponse({"detail": "Cross-origin writes are not allowed"}, status_code=403)
    return await call_next(request)


class ProjectInput(BaseModel):
    team_id: str | None = None
    track_id: str | None = None
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=800)
    description: str = Field(default="", max_length=5000)
    repo_url: str = Field(default="", max_length=1000)
    demo_url: str = Field(default="", max_length=1000)
    thumbnail_url: str = Field(default="", max_length=1000)
    image_urls: str = Field(default="", max_length=5000)
    video_url: str = Field(default="", max_length=1000)
    live_url: str = Field(default="", max_length=1000)
    tech_tags: str = Field(default="", max_length=500)
    status: str = "draft"
    answers: dict[str, str] | None = None


def _deadline_passed(value: str) -> bool:
    return datetime.now(timezone.utc) >= datetime.fromisoformat(value.replace("Z", "+00:00"))


@app.get("/health")
def health():
    with closing(connect()) as db:
        db.execute("SELECT 1").fetchone()
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    principal = current_principal(request)
    with closing(connect()) as db:
        event = db.execute("SELECT * FROM events ORDER BY created_at LIMIT 1").fetchone()
        tracks = db.execute("SELECT * FROM tracks WHERE event_id=? ORDER BY name", (event["id"],)).fetchall()
        count = db.execute("SELECT COUNT(*) FROM projects WHERE event_id=? AND status='submitted'", (event["id"],)).fetchone()[0]
    closed = _deadline_passed(event["submissions_close"])
    return templates.TemplateResponse(request, "home.html", {
        "event": dict(event), "tracks": [dict(row) for row in tracks], "project_count": count,
        "principal": principal, "closed": closed,
        "phase_index": 4 if event["results_published_at"] else 3 if closed else 2,
    })


def _gallery_filters(event_id: str, query: str, track: str, tag: str) -> tuple[list[str], list[str]]:
    where = ["p.event_id=?", "p.status='submitted'"]
    args = [event_id]
    if query:
        where.append("(p.title LIKE ? OR p.summary LIKE ? OR p.description LIKE ?"
                     " OR p.tech_tags LIKE ? OR t.name LIKE ? OR m.name LIKE ?)")
        args.extend([f"%{query}%"] * 6)
    if track:
        where.append("p.track_id=?")
        args.append(track)
    if tag:
        where.append("(',' || lower(replace(p.tech_tags,' ','')) || ',') LIKE ?")
        args.append(f"%,{tag.casefold().replace(' ', '')},%")
    return where, args


@app.get("/projects", response_class=HTMLResponse)
def gallery(request: Request, q: str = "", track: str = "", tag: str = "", event: str = "",
            page: int = Query(default=1, ge=1)):
    query = q.strip()[:120]
    with closing(connect()) as db:
        selected = (db.execute("SELECT * FROM events WHERE id=?", (event,)).fetchone() if event
                    else db.execute("SELECT * FROM events ORDER BY created_at LIMIT 1").fetchone())
        if selected is None:
            raise HTTPException(status_code=404, detail="Event not found")
        tracks = db.execute("SELECT id,name FROM tracks WHERE event_id=? ORDER BY name", (selected["id"],)).fetchall()
        tags = sorted({value.strip() for row in db.execute(
            "SELECT tech_tags FROM projects WHERE event_id=? AND status='submitted' AND tech_tags<>''",
            (selected["id"],),
        ) for value in row["tech_tags"].split(",") if value.strip()}, key=str.casefold)
        selected_tag = tag.strip()[:80]
        where, args = _gallery_filters(selected["id"], query, track, selected_tag)
        filtered_total = db.execute(
            "SELECT COUNT(*) FROM projects p JOIN tracks t ON t.id=p.track_id"
            " JOIN teams m ON m.id=p.team_id WHERE " + " AND ".join(where),
            args,
        ).fetchone()[0]
        page_size = 48
        last_page = max(1, (filtered_total + page_size - 1) // page_size)
        current_page = min(page, last_page)
        projects = db.execute(
            "SELECT p.id,p.title,p.summary,p.repo_url,p.submitted_at,p.duplicate_of,"
            " t.name AS track_name,t.id AS track_id,m.name AS team_name"
            " FROM projects p JOIN tracks t ON t.id=p.track_id"
            " JOIN teams m ON m.id=p.team_id WHERE " + " AND ".join(where)
            + " ORDER BY p.submitted_at DESC,p.id DESC LIMIT ? OFFSET ?",
            [*args, page_size, (current_page - 1) * page_size],
        ).fetchall()
        total = db.execute(
            "SELECT COUNT(*) FROM projects WHERE event_id=? AND status='submitted'", (selected["id"],)
        ).fetchone()[0]
    return templates.TemplateResponse(request, "gallery.html", {
        "event": dict(selected), "projects": [dict(row) for row in projects],
        "tracks": [dict(row) for row in tracks], "tags": tags,
        "total": total, "q": query, "track": track, "tag": selected_tag,
        "event_param": event, "principal": current_principal(request),
        "filtered_total": filtered_total, "page": current_page, "last_page": last_page,
        "first_result": (current_page - 1) * page_size + 1 if filtered_total else 0,
        "last_result": min(current_page * page_size, filtered_total),
    })


@app.get("/api/events/{event_id}/projects")
def public_project_list(event_id: str, q: str = "", track: str = "", tag: str = "",
                        page: int = Query(default=1, ge=1), page_size: int = Query(default=48, ge=1, le=100)):
    """List submitted projects without exposing drafts."""
    query, selected_tag = q.strip()[:120], tag.strip()[:80]
    with closing(connect()) as db:
        if db.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Event not found")
        where, args = _gallery_filters(event_id, query, track, selected_tag)
        joins = " FROM projects p JOIN tracks t ON t.id=p.track_id JOIN teams m ON m.id=p.team_id"
        total = db.execute("SELECT COUNT(*)" + joins + " WHERE " + " AND ".join(where), args).fetchone()[0]
        rows = db.execute(
            "SELECT p.id,p.title,p.summary,p.description,p.repo_url,p.demo_url,p.thumbnail_url,"
            "p.image_urls,p.video_url,p.live_url,p.tech_tags,p.submitted_at,p.duplicate_of,"
            "t.id AS track_id,t.name AS track_name,m.id AS team_id,m.name AS team_name" + joins
            + " WHERE " + " AND ".join(where)
            + " ORDER BY p.submitted_at DESC,p.id DESC LIMIT ? OFFSET ?",
            [*args, page_size, (page - 1) * page_size],
        ).fetchall()
    return {"event_id": event_id, "page": page, "page_size": page_size, "total": total,
            "projects": [dict(row) for row in rows]}


@app.get("/api/projects/{project_id}")
def public_project(project_id: str):
    """Return public detail for a submitted project."""
    with closing(connect()) as db:
        row = db.execute(
            "SELECT p.id,p.event_id,p.title,p.summary,p.description,p.repo_url,p.demo_url,p.thumbnail_url,"
            "p.image_urls,p.video_url,p.live_url,p.tech_tags,p.submitted_at,p.duplicate_of,"
            "t.id AS track_id,t.name AS track_name,m.id AS team_id,m.name AS team_name "
            "FROM projects p JOIN tracks t ON t.id=p.track_id JOIN teams m ON m.id=p.team_id "
            "WHERE p.id=? AND p.status='submitted'", (project_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Submitted project not found")
    return dict(row)


@app.get("/widgets/events/{event_id}/gallery", response_class=HTMLResponse)
def gallery_widget(request: Request, event_id: str, page: int = Query(default=1, ge=1)):
    """A small, public gallery suitable for embedding as an iframe."""
    with closing(connect()) as db:
        event = db.execute("SELECT id,name FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        total = db.execute(
            "SELECT COUNT(*) FROM projects WHERE event_id=? AND status='submitted'",
            (event_id,),
        ).fetchone()[0]
        page_size = 12
        last_page = max(1, (total + page_size - 1) // page_size)
        current_page = min(page, last_page)
        projects = db.execute(
            "SELECT p.id,p.title,p.summary,t.name AS track_name,m.name AS team_name"
            " FROM projects p JOIN tracks t ON t.id=p.track_id"
            " JOIN teams m ON m.id=p.team_id"
            " WHERE p.event_id=? AND p.status='submitted'"
            " ORDER BY p.submitted_at DESC,p.id DESC LIMIT ? OFFSET ?",
            (event_id, page_size, (current_page - 1) * page_size),
        ).fetchall()
    return templates.TemplateResponse(request, "gallery_widget.html", {
        "event": dict(event), "projects": [dict(row) for row in projects],
        "page": current_page, "last_page": last_page, "total": total,
    })


@app.post("/api/events/{event_id}/projects", status_code=201)
def create_project(event_id: str, payload: ProjectInput, request: Request):
    principal = require_login(request)
    repo_url = require_web_url(payload.repo_url)
    demo_url = require_web_url(payload.demo_url)
    thumbnail_url = require_web_url(payload.thumbnail_url)
    video_url = require_web_url(payload.video_url)
    live_url = require_web_url(payload.live_url)
    image_urls = [require_web_url(value.strip()) for value in payload.image_urls.splitlines() if value.strip()]
    if len(image_urls) > 5:
        raise HTTPException(status_code=422, detail="Add at most five gallery images")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        event = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        require_event_role(db, principal, event_id, "participant")
        if event["results_published_at"]:
            raise HTTPException(status_code=409, detail="Results are published; projects are locked")
        if _deadline_passed(event["submissions_close"]):
            raise HTTPException(status_code=409, detail="Submissions are closed")
        if event["submissions_open"] and not _deadline_passed(event["submissions_open"]):
            raise HTTPException(status_code=409, detail="Submissions are not open yet")
        if payload.status not in ("draft", "submitted"):
            raise HTTPException(status_code=422, detail="Status must be draft or submitted")
        if not payload.team_id or not payload.track_id:
            raise HTTPException(status_code=422, detail="Team and track are required")
        member = db.execute(
            "SELECT 1 FROM team_members m JOIN teams t ON t.id=m.team_id"
            " WHERE m.team_id=? AND m.user_id=? AND t.event_id=?",
            (payload.team_id, principal.user_id, event_id),
        ).fetchone()
        if member is None:
            raise HTTPException(status_code=403, detail="You must belong to this team")
        track = db.execute("SELECT 1 FROM tracks WHERE id=? AND event_id=?", (payload.track_id, event_id)).fetchone()
        if track is None:
            raise HTTPException(status_code=422, detail="Track does not belong to this event")
        existing = db.execute("SELECT 1 FROM projects WHERE team_id=?", (payload.team_id,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="This team already has a project")
        answers = validate_answers(db, event_id, None, payload.answers, payload.status)
        project_id = "prj_" + uuid.uuid4().hex[:16]
        now = utc_now()
        db.execute(
            "INSERT INTO projects(id,event_id,team_id,track_id,title,summary,description,repo_url,demo_url,thumbnail_url,image_urls,video_url,live_url,tech_tags,status,submitted_at,updated_at,duplicate_of)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, event_id, payload.team_id, payload.track_id, payload.title, payload.summary,
             payload.description, repo_url, demo_url, thumbnail_url, "\n".join(image_urls), video_url,
             live_url, payload.tech_tags.strip(), payload.status,
             now if payload.status == "submitted" else None, now, None),
        )
        save_answers(db, project_id, answers)
        reconcile_submitted_duplicates(db, event_id)
        audit(db, event_id, principal.user_id, "project.created", "project", project_id,
              {"status": payload.status})
        db.commit()
    return {"id": project_id, "status": payload.status}


@app.get("/api/judge/scores")
def judge_scores(request: Request, judge: str | None = Query(default=None)):
    principal = require_login(request)
    with closing(connect()) as db:
        if judge is not None:
            target = db.execute("SELECT id,event_id FROM judge_profiles WHERE id=?", (judge,)).fetchone()
            if target is not None and has_event_role(db, principal, target["event_id"], "organizer"):
                return {"judge_id": judge, "scores": _judge_score_rows(db, judge)}
        profiles = db.execute(
            "SELECT j.id,j.event_id FROM judge_profiles j JOIN event_roles r"
            " ON r.event_id=j.event_id AND r.user_id=j.user_id AND r.role='judge'"
            " WHERE j.user_id=? ORDER BY j.event_id",
            (principal.user_id,),
        ).fetchall()
        if not profiles:
            raise HTTPException(status_code=403, detail="Judge access required")
        if judge is not None and judge not in {row["id"] for row in profiles}:
            raise HTTPException(status_code=403, detail="You cannot read another judge's scores")
        profile = next((row for row in profiles if row["id"] == judge), profiles[0])
        scores = _judge_score_rows(db, profile["id"])
    return {"judge_id": profile["id"], "scores": scores}


def _judge_score_rows(db, judge_id: str) -> list[dict]:
    rows = db.execute(
        "SELECT a.id AS assignment_id,p.id AS project_id,p.title,"
        " s.id AS scorecard_id,s.status,s.comment,s.submitted_at"
        " FROM judge_assignments a JOIN projects p ON p.id=a.project_id"
        " LEFT JOIN scorecards s ON s.assignment_id=a.id"
        " WHERE a.judge_id=? ORDER BY p.title,p.id",
        (judge_id,),
    ).fetchall()
    scores = []
    for row in rows:
        item = dict(row)
        criteria = db.execute(
            "SELECT c.slug,cs.score FROM criterion_scores cs"
            " JOIN rubric_criteria c ON c.id=cs.criterion_id WHERE cs.scorecard_id=?",
            (row["scorecard_id"],),
        ).fetchall() if row["scorecard_id"] else []
        item["criteria"] = {entry["slug"]: entry["score"] for entry in criteria}
        scores.append(item)
    return scores


@app.get("/api/events/{event_id}/judges/{judge_id}/scores")
def organizer_judge_scores(event_id: str, judge_id: str, request: Request):
    """Event-scoped organizer view of a judge's submitted and draft scorecards."""
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        target = db.execute(
            "SELECT 1 FROM judge_profiles WHERE id=? AND event_id=?", (judge_id, event_id)
        ).fetchone()
        if target is None:
            raise HTTPException(status_code=404, detail="Judge not found")
        scores = _judge_score_rows(db, judge_id)
    return {"event_id": event_id, "judge_id": judge_id, "scores": scores}


@app.get("/api/events/{event_id}/exports/projects.csv")
def export_projects(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        rows = db.execute(
            "SELECT p.id,p.title,p.status,p.summary,p.repo_url,p.demo_url,p.live_url,p.video_url,"
            " p.thumbnail_url,p.image_urls,p.tech_tags,p.submitted_at,"
            " t.name AS team,tr.name AS track FROM projects p"
            " JOIN teams t ON t.id=p.team_id JOIN tracks tr ON tr.id=p.track_id"
            " WHERE p.event_id=? ORDER BY p.id",
            (event_id,),
        ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    columns = ("id", "title", "status", "summary", "repo_url", "demo_url", "live_url", "video_url",
               "thumbnail_url", "image_urls", "tech_tags", "submitted_at", "team", "track", "answers_json")
    writer.writerow(columns)
    with closing(connect()) as db:
        for row in rows:
            answers = {answer["label"]: answer["answer"] for answer in db.execute(
                "SELECT q.label,a.answer FROM project_answers a JOIN submission_questions q ON q.id=a.question_id"
                " WHERE a.project_id=? ORDER BY q.sort_order", (row["id"],))}
            writer.writerow(tuple(csv_safe(row[column]) for column in columns[:-1]) +
                            (csv_safe(json.dumps(answers, ensure_ascii=False)),))
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{event_id}-projects.csv"',
    })


# Keep the parameterized workflow CSV route after the exact project CSV route.
app.include_router(judging_router)
app.include_router(public_router)
app.include_router(certificate_router)
app.include_router(stretch_router)
