"""Plain-language organizer presentation of immutable event audit entries."""

from __future__ import annotations

import json


LABELS = {
    "event.created": "Created event", "event.updated": "Updated event details",
    "participant.registered": "Joined event", "team.created": "Created team",
    "team.invite_created": "Created team invite", "team.member_joined": "Joined team",
    "project.updated": "Saved project", "judge.invited": "Invited judge",
    "judge.invite_accepted": "Accepted judge invite",
    "judge.tracks_changed": "Changed judge tracks",
    "judge.conflict_declared": "Reported judging conflict",
    "rubric.configured": "Configured rubric",
    "assignments.batch_created": "Assigned judges",
    "scorecard.draft": "Saved review draft",
    "scorecard.submitted": "Submitted review",
    "results.published": "Published results",
    "voting.configured": "Configured voting",
    "voter.invited": "Invited voter",
    "voter.invite_accepted": "Accepted voter invite",
    "vote.cast": "Cast vote", "comment.created": "Added comment",
    "comment.hidden": "Hid comment",
    "prize.winner_selected": "Selected prize winner",
    "certificates.issued": "Issued certificates",
}


def _category(action: str) -> str:
    if action.startswith(("judge.", "rubric.", "assignments.", "scorecard.", "results.")):
        return "Judging"
    if action.startswith(("voting.", "voter.", "vote.", "comment.")):
        return "Voting"
    if action.startswith(("prize.", "certificates.")):
        return "Certificates"
    return "Event and submissions"


def event_activity(db, event_id: str, category: str = "All", limit: int = 100) -> list[dict]:
    projects = {row["id"]: row["title"] for row in db.execute(
        "SELECT id,title FROM projects WHERE event_id=?", (event_id,),
    )}
    teams = {row["id"]: row["name"] for row in db.execute(
        "SELECT id,name FROM teams WHERE event_id=?", (event_id,),
    )}
    prizes = {row["id"]: row["name"] for row in db.execute(
        "SELECT id,name FROM prizes WHERE event_id=?", (event_id,),
    )}
    score_projects = {row["id"]: projects.get(row["project_id"], row["project_id"])
                      for row in db.execute(
                          "SELECT s.id,a.project_id FROM scorecards s"
                          " JOIN judge_assignments a ON a.id=s.assignment_id WHERE a.event_id=?",
                          (event_id,),
                      )}
    comments = {row["id"]: projects.get(row["project_id"], row["project_id"])
                for row in db.execute("SELECT id,project_id FROM comments WHERE event_id=?", (event_id,))}
    rows = db.execute(
        "SELECT a.action,a.entity_type,a.entity_id,a.details_json,a.created_at,"
        "u.name AS actor FROM audit_entries a JOIN users u ON u.id=a.actor_user_id"
        " WHERE a.event_id=? ORDER BY a.id DESC LIMIT 500", (event_id,),
    ).fetchall()
    activity = []
    for row in rows:
        action = row["action"]
        item_category = _category(action)
        if category != "All" and category != item_category:
            continue
        entity_id = row["entity_id"]
        target = {
            "project": projects.get(entity_id), "team": teams.get(entity_id),
            "prize": prizes.get(entity_id), "scorecard": score_projects.get(entity_id),
            "comment": comments.get(entity_id),
        }.get(row["entity_type"])
        if target is None:
            target = entity_id if row["entity_type"].endswith("invite") else ""
        try:
            details = json.loads(row["details_json"] or "{}")
        except json.JSONDecodeError:
            details = {}
        if action == "assignments.batch_created":
            target = f"{details.get('created', 0)} assignments; {details.get('shortages', 0)} coverage gaps"
        elif action == "certificates.issued":
            target = f"{details.get('participant', 0)} participant, {details.get('winner', 0)} winner"
        elif action == "prize.winner_selected":
            project_title = projects.get(details.get("project_id"), details.get("project_id", ""))
            target = f"{target}: {project_title}"
        activity.append({"actor": row["actor"], "label": LABELS.get(action, action.replace(".", " ").replace("_", " ").capitalize()),
                         "target": target, "category": item_category, "created_at": row["created_at"]})
        if len(activity) >= limit:
            break
    return activity
