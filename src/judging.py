"""Judge invitations, assignments, rubric scoring, progress and results."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .auth import has_event_role, require_event_role, require_login
from .core import audit, csv_safe, identifier, time_value
from .db import connect, utc_now
from .scoring import event_ranking, judging_insight, scorecard_detail
from .ml_insight import organizer_ml_insight


router = APIRouter(prefix="/api")


def _judge_profile(db, user_id: str, event_id: str):
    row = db.execute("SELECT id,status FROM judge_profiles WHERE user_id=? AND event_id=?", (user_id, event_id)).fetchone()
    if row is None or row["status"] != "accepted":
        raise HTTPException(status_code=403, detail="Judge access required")
    return row


class JudgeInvite(BaseModel):
    email: str = Field(min_length=3, max_length=254)


@router.post("/events/{event_id}/judges/invites", status_code=201)
def invite_judge(event_id: str, payload: JudgeInvite, request: Request):
    principal = require_login(request)
    email = payload.email.strip().casefold()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        token = secrets.token_urlsafe(24)
        expiry = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        db.execute("INSERT INTO judge_invites(token_hash,event_id,email,created_by,expires_at) VALUES(?,?,?,?,?)",
                   (hashlib.sha256(token.encode()).hexdigest(), event_id, email, principal.user_id, expiry))
        audit(db, event_id, principal.user_id, "judge.invited", "judge_invite", email)
        db.commit()
    return {"invite_url": f"/judge-invite/{token}", "email": email, "expires_at": expiry}


@router.post("/judge-invites/{token}/accept")
def accept_judge_invite(token: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        invitation = db.execute("SELECT * FROM judge_invites WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if invitation is None or invitation["accepted_at"] or time_value(invitation["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Invite link is invalid or expired")
        if invitation["email"] != principal.email.casefold():
            raise HTTPException(status_code=403, detail="This invite belongs to another email address")
        judge_id = identifier("jdg")
        db.execute("INSERT INTO judge_profiles(id,event_id,user_id,status) VALUES(?,?,?,'accepted')",
                   (judge_id, invitation["event_id"], principal.user_id))
        db.execute("INSERT OR IGNORE INTO event_roles(event_id,user_id,role) VALUES(?,?,'judge')", (invitation["event_id"], principal.user_id))
        db.execute("UPDATE judge_invites SET accepted_at=? WHERE token_hash=?", (utc_now(), invitation["token_hash"]))
        audit(db, invitation["event_id"], principal.user_id, "judge.invite_accepted", "judge", judge_id)
        db.commit()
    return {"judge_id": judge_id, "event_id": invitation["event_id"]}


class JudgeTracks(BaseModel):
    tracks: list[str]


@router.put("/events/{event_id}/judges/{judge_id}/tracks")
def set_judge_tracks(event_id: str, judge_id: str, payload: JudgeTracks, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        judge = db.execute("SELECT 1 FROM judge_profiles WHERE id=? AND event_id=?", (judge_id, event_id)).fetchone()
        if judge is None:
            raise HTTPException(status_code=404, detail="Judge not found")
        valid = {row["id"] for row in db.execute("SELECT id FROM tracks WHERE event_id=?", (event_id,))}
        if not set(payload.tracks).issubset(valid):
            raise HTTPException(status_code=422, detail="A track does not belong to this event")
        assigned_tracks = {row["track_id"] for row in db.execute(
            "SELECT DISTINCT p.track_id FROM judge_assignments a JOIN projects p ON p.id=a.project_id WHERE a.judge_id=?",
            (judge_id,),
        )}
        if not assigned_tracks.issubset(payload.tracks):
            raise HTTPException(status_code=409, detail="A judge's assigned tracks cannot be removed")
        db.execute("DELETE FROM judge_tracks WHERE judge_id=?", (judge_id,))
        db.executemany("INSERT INTO judge_tracks(judge_id,track_id) VALUES(?,?)", [(judge_id, track) for track in set(payload.tracks)])
        audit(db, event_id, principal.user_id, "judge.tracks_changed", "judge", judge_id, {"tracks": payload.tracks})
        db.commit()
    return {"judge_id": judge_id, "tracks": payload.tracks}


class CriterionInput(BaseModel):
    slug: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    name: str = Field(min_length=2, max_length=100)
    weight: float = Field(gt=0, le=1000)


class RubricInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    criteria: list[CriterionInput] = Field(min_length=1)


@router.get("/events/{event_id}/rubric")
def get_rubric(event_id: str):
    with closing(connect()) as db:
        rubric = db.execute("SELECT id,name,version FROM rubrics WHERE event_id=? AND is_active=1 ORDER BY version DESC LIMIT 1", (event_id,)).fetchone()
        if rubric is None:
            raise HTTPException(status_code=404, detail="Rubric not found")
        criteria = db.execute("SELECT id,slug,name,weight,max_score FROM rubric_criteria WHERE rubric_id=? ORDER BY sort_order", (rubric["id"],)).fetchall()
    return {"rubric": dict(rubric), "criteria": [dict(row) for row in criteria]}


@router.put("/events/{event_id}/rubric")
def configure_rubric(event_id: str, payload: RubricInput, request: Request):
    principal = require_login(request)
    if len({item.slug for item in payload.criteria}) != len(payload.criteria):
        raise HTTPException(status_code=422, detail="Criterion slugs must be unique")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        existing = db.execute("SELECT 1 FROM judge_assignments WHERE event_id=? LIMIT 1", (event_id,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Change the rubric before assigning judges")
        prior = db.execute("SELECT COALESCE(MAX(version),0) FROM rubrics WHERE event_id=?", (event_id,)).fetchone()[0]
        rubric_id = identifier("rubric")
        db.execute("UPDATE rubrics SET is_active=0 WHERE event_id=?", (event_id,))
        db.execute("INSERT INTO rubrics(id,event_id,version,name,created_at) VALUES(?,?,?,?,?)",
                   (rubric_id, event_id, prior + 1, payload.name.strip(), utc_now()))
        for position, item in enumerate(payload.criteria):
            db.execute("INSERT INTO rubric_criteria(id,rubric_id,slug,name,weight,max_score,sort_order)"
                       " VALUES(?,?,?,?,?,5,?)",
                       (identifier("crit"), rubric_id, item.slug, item.name.strip(), item.weight, position))
        audit(db, event_id, principal.user_id, "rubric.configured", "rubric", rubric_id)
        db.commit()
    return {"id": rubric_id, "version": prior + 1}


class ConflictInput(BaseModel):
    reason: str = Field(min_length=3, max_length=400)


@router.put("/events/{event_id}/judges/{judge_id}/conflicts/{project_id}")
def declare_conflict(event_id: str, judge_id: str, project_id: str, payload: ConflictInput, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        pair = db.execute("SELECT j.user_id FROM judge_profiles j JOIN projects p ON p.event_id=j.event_id WHERE j.id=? AND p.id=? AND j.event_id=?", (judge_id, project_id, event_id)).fetchone()
        if pair is None:
            raise HTTPException(status_code=404, detail="Judge or project not found")
        organizer = has_event_role(db, principal, event_id, "organizer")
        if not organizer and pair["user_id"] != principal.user_id:
            raise HTTPException(status_code=403, detail="Only the assigned judge or organizer can report this conflict")
        assignment = db.execute("SELECT a.id,s.status FROM judge_assignments a LEFT JOIN scorecards s ON s.assignment_id=a.id"
                                " WHERE a.judge_id=? AND a.project_id=?", (judge_id, project_id)).fetchone()
        if not organizer and assignment is None:
            raise HTTPException(status_code=403, detail="Judges can report conflicts only on their assignments")
        if assignment and assignment["status"] == "submitted":
            raise HTTPException(status_code=409, detail="A submitted review must be resolved before declaring a conflict")
        if assignment:
            db.execute("DELETE FROM judge_assignments WHERE id=?", (assignment["id"],))
        db.execute("INSERT OR REPLACE INTO judge_conflicts(judge_id,project_id,reason,created_at) VALUES(?,?,?,?)",
                   (judge_id, project_id, payload.reason, utc_now()))
        audit(db, event_id, principal.user_id, "judge.conflict_declared", "project", project_id,
              {"judge_id": judge_id, "revoked_assignment": bool(assignment), "reported_by": "organizer" if organizer else "judge"})
        db.commit()
    return {"judge_id": judge_id, "project_id": project_id}


class BatchInput(BaseModel):
    reviews_per_project: int = Field(default=3, ge=1, le=10)


@router.post("/events/{event_id}/assignments/batch")
def batch_assign(event_id: str, payload: BatchInput, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        event = db.execute("SELECT submissions_close,results_published_at FROM events WHERE id=?", (event_id,)).fetchone()
        if event["results_published_at"]:
            raise HTTPException(status_code=409, detail="Results are published; assignments are locked")
        if datetime.now(timezone.utc) < time_value(event["submissions_close"]):
            raise HTTPException(status_code=409, detail="Submissions must close before assigning judges")
        rubric = db.execute("SELECT id FROM rubrics WHERE event_id=? AND is_active=1", (event_id,)).fetchone()
        if rubric is None:
            raise HTTPException(status_code=409, detail="Configure a rubric first")
        projects = db.execute("SELECT id,team_id,track_id FROM projects WHERE event_id=? AND status='submitted' AND duplicate_of IS NULL ORDER BY id", (event_id,)).fetchall()
        judges = db.execute("SELECT id,user_id FROM judge_profiles WHERE event_id=? AND status='accepted' ORDER BY id", (event_id,)).fetchall()
        loads = {judge["id"]: db.execute("SELECT COUNT(*) FROM judge_assignments WHERE judge_id=?", (judge["id"],)).fetchone()[0] for judge in judges}
        created = []
        shortages = []
        for project in projects:
            current = {row["judge_id"] for row in db.execute("SELECT judge_id FROM judge_assignments WHERE project_id=?", (project["id"],))}
            needed = max(0, payload.reviews_per_project - len(current))
            candidates = []
            for judge in judges:
                if judge["id"] in current:
                    continue
                if db.execute("SELECT 1 FROM judge_tracks WHERE judge_id=? AND track_id=?", (judge["id"], project["track_id"])).fetchone() is None:
                    continue
                if db.execute("SELECT 1 FROM team_members WHERE team_id=? AND user_id=?", (project["team_id"], judge["user_id"])).fetchone():
                    continue
                if db.execute("SELECT 1 FROM judge_conflicts WHERE judge_id=? AND project_id=?", (judge["id"], project["id"])).fetchone():
                    continue
                candidates.append(judge["id"])
            for judge_id in sorted(candidates, key=lambda item: (loads[item], item))[:needed]:
                assignment_id = identifier("asg")
                db.execute("INSERT INTO judge_assignments(id,event_id,project_id,judge_id,assigned_at,reason) VALUES(?,?,?,?,?,?)",
                           (assignment_id, event_id, project["id"], judge_id, utc_now(), "Balanced track-matched batch"))
                loads[judge_id] += 1
                created.append({"assignment_id": assignment_id, "project_id": project["id"], "judge_id": judge_id})
            if len(candidates) < needed:
                shortages.append({"project_id": project["id"], "missing": needed - len(candidates)})
        audit(db, event_id, principal.user_id, "assignments.batch_created", "event", event_id,
              {"created": len(created), "shortages": len(shortages)})
        db.commit()
    return {"created": created, "shortages": shortages}


@router.get("/judge/assignments")
def own_assignments(request: Request, event_id: str):
    principal = require_login(request)
    with closing(connect()) as db:
        judge = _judge_profile(db, principal.user_id, event_id)
        rows = db.execute("SELECT a.id,p.id AS project_id,p.title,p.summary,p.repo_url,t.name AS track,"
                          "s.status AS score_status FROM judge_assignments a JOIN projects p ON p.id=a.project_id"
                          " JOIN tracks t ON t.id=p.track_id LEFT JOIN scorecards s ON s.assignment_id=a.id"
                          " WHERE a.judge_id=? ORDER BY s.status,p.title", (judge["id"],)).fetchall()
    return {"judge_id": judge["id"], "assignments": [dict(row) for row in rows]}


class ScorecardInput(BaseModel):
    criteria: dict[str, float]
    comment: str = Field(default="", max_length=4000)
    status: str = "draft"


@router.put("/judge/assignments/{assignment_id}/scorecard")
def save_scorecard(assignment_id: str, payload: ScorecardInput, request: Request):
    principal = require_login(request)
    if payload.status not in ("draft", "submitted"):
        raise HTTPException(status_code=422, detail="Status must be draft or submitted")
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        assignment = db.execute("SELECT a.*,j.user_id,e.submissions_close,e.judging_open,e.judging_close,e.results_published_at"
                                " FROM judge_assignments a JOIN judge_profiles j ON j.id=a.judge_id"
                                " JOIN events e ON e.id=a.event_id WHERE a.id=?", (assignment_id,)).fetchone()
        if assignment is None:
            raise HTTPException(status_code=404, detail="Assignment not found")
        if assignment["user_id"] != principal.user_id:
            raise HTTPException(status_code=403, detail="You can score only your own assignments")
        if db.execute("SELECT 1 FROM judge_conflicts WHERE judge_id=? AND project_id=?",
                      (assignment["judge_id"], assignment["project_id"])).fetchone():
            raise HTTPException(status_code=409, detail="This assignment has a declared conflict")
        if assignment["results_published_at"]:
            raise HTTPException(status_code=409, detail="Results are published; scores are locked")
        if datetime.now(timezone.utc) < time_value(assignment["submissions_close"]):
            raise HTTPException(status_code=409, detail="Submissions must close before judging")
        if assignment["judging_open"] and datetime.now(timezone.utc) < time_value(assignment["judging_open"]):
            raise HTTPException(status_code=409, detail="Judging has not opened")
        if assignment["judging_close"] and datetime.now(timezone.utc) >= time_value(assignment["judging_close"]):
            raise HTTPException(status_code=409, detail="Judging is closed")
        rubric = db.execute("SELECT id FROM rubrics WHERE event_id=? AND is_active=1", (assignment["event_id"],)).fetchone()
        criteria = db.execute("SELECT id,slug,max_score FROM rubric_criteria WHERE rubric_id=?", (rubric["id"],)).fetchall()
        by_slug = {row["slug"]: row for row in criteria}
        if not set(payload.criteria).issubset(by_slug):
            raise HTTPException(status_code=422, detail="Unknown rubric criterion")
        if payload.status == "submitted" and set(payload.criteria) != set(by_slug):
            raise HTTPException(status_code=422, detail="Score every criterion before submitting")
        for slug, value in payload.criteria.items():
            if not math.isfinite(value) or value < 0 or value > by_slug[slug]["max_score"]:
                raise HTTPException(status_code=422, detail=f"{slug} must be a finite score between 0 and 5")
        existing = db.execute("SELECT id,rubric_id FROM scorecards WHERE assignment_id=?", (assignment_id,)).fetchone()
        if existing and existing["rubric_id"] != rubric["id"]:
            raise HTTPException(status_code=409, detail="Assignment uses a different rubric version")
        scorecard_id = existing["id"] if existing else identifier("sc")
        now = utc_now()
        if existing:
            db.execute("UPDATE scorecards SET status=?,comment=?,updated_at=?,submitted_at=? WHERE id=?",
                       (payload.status, payload.comment, now, now if payload.status == "submitted" else None, scorecard_id))
            db.execute("DELETE FROM criterion_scores WHERE scorecard_id=?", (scorecard_id,))
        else:
            db.execute("INSERT INTO scorecards(id,assignment_id,rubric_id,status,comment,updated_at,submitted_at)"
                       " VALUES(?,?,?,?,?,?,?)",
                       (scorecard_id, assignment_id, rubric["id"], payload.status, payload.comment, now,
                        now if payload.status == "submitted" else None))
        for slug, value in payload.criteria.items():
            db.execute("INSERT INTO criterion_scores(scorecard_id,criterion_id,score) VALUES(?,?,?)",
                       (scorecard_id, by_slug[slug]["id"], value))
        audit(db, assignment["event_id"], principal.user_id, "scorecard." + payload.status,
              "scorecard", scorecard_id, {"assignment_id": assignment_id})
        db.commit()
    return {"id": scorecard_id, "status": payload.status}


@router.get("/events/{event_id}/progress")
def judge_progress(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        judges = db.execute("SELECT j.id,u.name,u.email,COUNT(a.id) AS assigned,"
                            " SUM(CASE WHEN s.status='draft' THEN 1 ELSE 0 END) AS started,"
                            " SUM(CASE WHEN s.status='submitted' THEN 1 ELSE 0 END) AS submitted"
                            " FROM judge_profiles j JOIN users u ON u.id=j.user_id"
                            " LEFT JOIN judge_assignments a ON a.judge_id=j.id"
                            " LEFT JOIN scorecards s ON s.assignment_id=a.id"
                            " WHERE j.event_id=? GROUP BY j.id ORDER BY u.name", (event_id,)).fetchall()
        projects = db.execute("SELECT p.id,p.title,p.duplicate_of,COUNT(a.id) AS assigned,"
                              " SUM(CASE WHEN s.status='submitted' THEN 1 ELSE 0 END) AS submitted"
                              " FROM projects p LEFT JOIN judge_assignments a ON a.project_id=p.id"
                              " LEFT JOIN scorecards s ON s.assignment_id=a.id"
                              " WHERE p.event_id=? AND p.status='submitted' GROUP BY p.id ORDER BY p.title", (event_id,)).fetchall()
    return {"judges": [dict(row) for row in judges], "projects": [dict(row) for row in projects]}


@router.get("/events/{event_id}/rankings")
def private_rankings(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        return event_ranking(db, event_id)


@router.get("/events/{event_id}/judging-insight")
def private_judging_insight(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        return judging_insight(db, event_id)


@router.get("/events/{event_id}/ml-review-signals")
def private_ml_review_signals(event_id: str, request: Request):
    """Advisory, organizer-only signals; never used to alter ranking."""
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        return organizer_ml_insight(db, event_id)


@router.get("/events/{event_id}/scorecards/{scorecard_id}")
def organizer_scorecard(event_id: str, scorecard_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        detail = scorecard_detail(db, event_id, scorecard_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Submitted scorecard not found")
        return detail


@router.post("/events/{event_id}/results/publish")
def publish_results(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        require_event_role(db, principal, event_id, "organizer")
        event = db.execute("SELECT results_published_at,submissions_close FROM events WHERE id=?", (event_id,)).fetchone()
        if event["results_published_at"]:
            raise HTTPException(status_code=409, detail="Results are already published")
        if datetime.now(timezone.utc) < time_value(event["submissions_close"]):
            raise HTTPException(status_code=409, detail="Submissions must close before results are published")
        voting = db.execute("SELECT voting_mode,voting_close FROM events WHERE id=?", (event_id,)).fetchone()
        if voting["voting_mode"] != "disabled" and voting["voting_close"] and time_value(voting["voting_close"]) > datetime.now(timezone.utc):
            raise HTTPException(status_code=409, detail="Voting must close before results are published")
        ranking = event_ranking(db, event_id)
        missing = [row["id"] for row in ranking["projects"] if row["duplicate_of"] is None and row["review_count"] == 0]
        if missing:
            raise HTTPException(status_code=409, detail=f"Unreviewed projects: {', '.join(missing[:5])}")
        now = utc_now()
        db.execute("UPDATE events SET results_published_at=? WHERE id=?", (now, event_id))
        audit(db, event_id, principal.user_id, "results.published", "event", event_id,
              {"ranked_projects": sum(row["rank"] is not None for row in ranking["projects"])})
        db.commit()
    return {"published_at": now, "ranked_projects": sum(row["rank"] is not None for row in ranking["projects"])}


@router.get("/events/{event_id}/results")
def public_results(event_id: str):
    with closing(connect()) as db:
        event = db.execute("SELECT results_published_at FROM events WHERE id=?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")
        if event["results_published_at"] is None:
            raise HTTPException(status_code=404, detail="Results are not published")
        ranking = event_ranking(db, event_id)
    return {"published_at": event["results_published_at"], "projects": ranking["projects"]}


@router.get("/events/{event_id}/audit")
def audit_log(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        rows = db.execute("SELECT id,actor_user_id,action,entity_type,entity_id,details_json,created_at"
                          " FROM audit_entries WHERE event_id=? ORDER BY id DESC LIMIT 500", (event_id,)).fetchall()
    return {"entries": [dict(row) for row in rows]}


@router.get("/events/{event_id}/exports/scores.csv")
def export_scores(event_id: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        rows = db.execute("SELECT p.id AS project_id,p.title,j.id AS judge_id,u.name AS judge,"
                          " s.status,s.comment,s.submitted_at,c.slug,cs.score"
                          " FROM judge_assignments a JOIN projects p ON p.id=a.project_id"
                          " JOIN judge_profiles j ON j.id=a.judge_id JOIN users u ON u.id=j.user_id"
                          " LEFT JOIN scorecards s ON s.assignment_id=a.id"
                          " LEFT JOIN criterion_scores cs ON cs.scorecard_id=s.id"
                          " LEFT JOIN rubric_criteria c ON c.id=cs.criterion_id"
                          " WHERE a.event_id=? ORDER BY p.id,j.id,c.sort_order", (event_id,)).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    columns = ("project_id", "title", "judge_id", "judge", "status", "comment", "submitted_at", "slug", "score")
    writer.writerow(columns)
    writer.writerows(tuple(csv_safe(row[column]) for column in columns) for row in rows)
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8")


@router.get("/events/{event_id}/exports/{kind}.csv")
def export_workflow(event_id: str, kind: str, request: Request):
    principal = require_login(request)
    with closing(connect()) as db:
        require_event_role(db, principal, event_id, "organizer")
        if kind == "teams":
            columns = ("team_id", "team", "member", "email", "role")
            rows = db.execute("SELECT t.id AS team_id,t.name AS team,u.name AS member,u.email,m.role"
                              " FROM teams t JOIN team_members m ON m.team_id=t.id JOIN users u ON u.id=m.user_id"
                              " WHERE t.event_id=? ORDER BY t.id,u.email", (event_id,)).fetchall()
            data = [tuple(row[column] for column in columns) for row in rows]
        elif kind == "assignments":
            columns = ("assignment_id", "project_id", "project", "judge_id", "judge", "track", "status", "assigned_at")
            rows = db.execute("SELECT a.id AS assignment_id,p.id AS project_id,p.title AS project,"
                              " j.id AS judge_id,u.name AS judge,t.name AS track,s.status,a.assigned_at"
                              " FROM judge_assignments a JOIN projects p ON p.id=a.project_id"
                              " JOIN tracks t ON t.id=p.track_id JOIN judge_profiles j ON j.id=a.judge_id"
                              " JOIN users u ON u.id=j.user_id LEFT JOIN scorecards s ON s.assignment_id=a.id"
                              " WHERE a.event_id=? ORDER BY p.id,j.id", (event_id,)).fetchall()
            data = [tuple(row[column] for column in columns) for row in rows]
        elif kind == "rankings":
            columns = ("rank", "project_id", "title", "team", "track", "review_count", "raw_score", "adjusted_score", "duplicate_of")
            ranking = event_ranking(db, event_id)
            data = [tuple(row.get("id") if column == "project_id" else row.get(column) for column in columns)
                    for row in ranking["projects"]]
        else:
            raise HTTPException(status_code=404, detail="Export not found")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(tuple(csv_safe(value) for value in row) for row in data)
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{event_id}-{kind}.csv"'})
