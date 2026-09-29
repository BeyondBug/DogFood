"""Idempotent import of the organizer's published fixture data."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .db import connect, utc_now
from .auth import hash_password, verify_password


DEMO_TOKENS = {
    "organizer": "bb_demo_organizer_2026_local_only",
    "judge_a": "bb_demo_judge_a_2026_local_only",
    "judge_b": "bb_demo_judge_b_2026_local_only",
    "participant": "bb_demo_participant_2026_local_only",
}
DEMO_ADMIN_ID = "usr_demo_admin"
DEMO_ADMIN_EMAIL = "demo-admin@beyondbug.local"


def user_id(email: str) -> str:
    return "usr_" + hashlib.sha256(email.casefold().encode()).hexdigest()[:20]


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def load_fixture() -> dict:
    path = Path(os.getenv("DOGFOOD_FIXTURES_PATH", "fixtures.json"))
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _bootstrap_admin() -> None:
    email = os.getenv("DOGFOOD_BOOTSTRAP_EMAIL", "").strip().casefold()
    password = os.getenv("DOGFOOD_BOOTSTRAP_PASSWORD", "")
    if not email and not password:
        return
    if not email or len(password) < 12:
        raise RuntimeError("Set both DOGFOOD_BOOTSTRAP_EMAIL and a password of at least 12 characters")
    password_digest = hash_password(password)
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT OR IGNORE INTO users(id,email,name,password_hash,is_admin,created_at)"
                   " VALUES(?,?,?,?,1,?)",
                   (user_id(email), email, "Local administrator", password_digest, utc_now()))
        db.execute("UPDATE users SET is_admin=1,password_hash=COALESCE(password_hash,?)"
                   " WHERE email=? COLLATE NOCASE", (password_digest, email))
        db.commit()


def _print_demo_access() -> None:
    if os.getenv("DOGFOOD_DEMO_MODE", "0") == "1":
        print("DOGFOOD fixture ready. Checker auth headers:", flush=True)
        for role, token in DEMO_TOKENS.items():
            print(f"  {role}: Authorization: Bearer {token}", flush=True)
        print("Demo account password: BeyondBugDemo2026!", flush=True)


def _ensure_demo_access(fixture: dict) -> None:
    if os.getenv("DOGFOOD_DEMO_MODE", "0") != "1":
        return
    accounts = {
        "organizer": "org_demo",
        "judge_a": user_id(fixture["judges"][0]["email"]),
        "judge_b": user_id(fixture["judges"][1]["email"]),
        "participant": user_id(fixture["teams"][0]["members"][0]),
    }
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        # The imported fixture is closed. A distinct demo administrator lets
        # the one-command walkthrough create an event without broadening the
        # fixture organizer's event-scoped role.
        db.execute("INSERT OR IGNORE INTO users(id,email,name,created_at) VALUES(?,?,?,?)",
                   (DEMO_ADMIN_ID, DEMO_ADMIN_EMAIL, "Demo administrator", utc_now()))
        db.execute("UPDATE users SET is_admin=1 WHERE id=?", (DEMO_ADMIN_ID,))
        admin = db.execute("SELECT password_hash FROM users WHERE id=?", (DEMO_ADMIN_ID,)).fetchone()
        if admin["password_hash"] is None:
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (hash_password("BeyondBugDemo2026!"), DEMO_ADMIN_ID))
        for role, token in DEMO_TOKENS.items():
            db.execute("INSERT OR IGNORE INTO sessions(token_hash,user_id,created_at,expires_at)"
                       " VALUES(?,?,?,?)",
                       (token_hash(token), accounts[role], utc_now(),
                        datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()))
        for uid in set(accounts.values()):
            row = db.execute("SELECT password_hash FROM users WHERE id=?", (uid,)).fetchone()
            if row and row["password_hash"] is None:
                db.execute("UPDATE users SET password_hash=? WHERE id=?",
                           (hash_password("BeyondBugDemo2026!"), uid))
        db.commit()


def _remove_demo_access(fixture: dict) -> None:
    if os.getenv("DOGFOOD_DEMO_MODE", "0") == "1":
        return
    accounts = ["org_demo", user_id(fixture["judges"][0]["email"]),
                user_id(fixture["judges"][1]["email"]),
                user_id(fixture["teams"][0]["members"][0])]
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE users SET is_admin=0 WHERE id=?", (DEMO_ADMIN_ID,))
        for token in DEMO_TOKENS.values():
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
        for uid in set(accounts):
            row = db.execute("SELECT password_hash FROM users WHERE id=?", (uid,)).fetchone()
            if row and verify_password("BeyondBugDemo2026!", row["password_hash"]):
                db.execute("UPDATE users SET password_hash=NULL WHERE id=?", (uid,))
        admin = db.execute("SELECT password_hash FROM users WHERE id=?", (DEMO_ADMIN_ID,)).fetchone()
        if admin and verify_password("BeyondBugDemo2026!", admin["password_hash"]):
            db.execute("UPDATE users SET password_hash=NULL WHERE id=?", (DEMO_ADMIN_ID,))
        db.commit()


def seed() -> None:
    fixture = load_fixture()
    event = fixture["event"]
    with closing(connect()) as db:
        already_loaded = db.execute("SELECT 1 FROM events WHERE id=?", (event["id"],)).fetchone() is not None
    if already_loaded:
        _remove_demo_access(fixture)
        _ensure_demo_access(fixture)
        _bootstrap_admin()
        _print_demo_access()
        return
    now = utc_now()
    with closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        organizer_id = "org_demo"
        db.execute(
            "INSERT OR IGNORE INTO users(id,email,name,created_at) VALUES(?,?,?,?)",
            (organizer_id, "organizer@beyondbug.local", "Demo organizer", now),
        )
        db.execute(
            """INSERT OR IGNORE INTO events
            (id,name,description,submissions_close,created_by,created_at)
            VALUES(?,?,?,?,?,?)""",
            (event["id"], event["name"], "Published DOGFOOD fixture event",
             event["submissions_close"], organizer_id, now),
        )
        db.execute(
            "INSERT OR IGNORE INTO event_roles(event_id,user_id,role) VALUES(?,?,?)",
            (event["id"], organizer_id, "organizer"),
        )

        for track in fixture["tracks"]:
            db.execute(
                "INSERT OR IGNORE INTO tracks(id,event_id,name) VALUES(?,?,?)",
                (track["id"], event["id"], track["name"]),
            )

        for judge in fixture["judges"]:
            uid = user_id(judge["email"])
            db.execute(
                "INSERT OR IGNORE INTO users(id,email,name,created_at) VALUES(?,?,?,?)",
                (uid, judge["email"], judge["name"], now),
            )
            db.execute(
                "INSERT OR IGNORE INTO event_roles(event_id,user_id,role) VALUES(?,?,?)",
                (event["id"], uid, "judge"),
            )
            db.execute(
                """INSERT OR IGNORE INTO judge_profiles(id,event_id,user_id,status)
                VALUES(?,?,?,'accepted')""",
                (judge["id"], event["id"], uid),
            )
            for track_id in judge["tracks"]:
                db.execute(
                    "INSERT OR IGNORE INTO judge_tracks(judge_id,track_id) VALUES(?,?)",
                    (judge["id"], track_id),
                )

        for team in fixture["teams"]:
            emails = team["members"]
            captain = user_id(emails[0]) if emails else None
            for email in emails:
                uid = user_id(email)
                db.execute(
                    "INSERT OR IGNORE INTO users(id,email,name,created_at) VALUES(?,?,?,?)",
                    (uid, email, email.split("@", 1)[0], now),
                )
                db.execute(
                    "INSERT OR IGNORE INTO event_roles(event_id,user_id,role) VALUES(?,?,?)",
                    (event["id"], uid, "participant"),
                )
            db.execute(
                "INSERT OR IGNORE INTO teams(id,event_id,name,created_by,created_at) VALUES(?,?,?,?,?)",
                (team["id"], event["id"], team["name"], captain, now),
            )
            for index, email in enumerate(emails):
                db.execute(
                    "INSERT OR IGNORE INTO team_members(team_id,user_id,role,joined_at) VALUES(?,?,?,?)",
                    (team["id"], user_id(email), "captain" if index == 0 else "member", now),
                )

        seen_repos: dict[tuple[str, str], str] = {}
        for project in fixture["projects"]:
            duplicate_key = (project["team"], project.get("repo_url", ""))
            duplicate_of = seen_repos.get(duplicate_key)
            seen_repos.setdefault(duplicate_key, project["id"])
            db.execute(
                """INSERT OR IGNORE INTO projects
                (id,event_id,team_id,track_id,title,summary,repo_url,status,
                 submitted_at,updated_at,duplicate_of)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (project["id"], event["id"], project["team"], project["track"],
                 project["title"], project.get("summary", ""), project.get("repo_url", ""),
                 "submitted", project["submitted_at"], project["submitted_at"], duplicate_of),
            )

        rubric_id = f"rubric_{event['id']}_v1"
        db.execute(
            "INSERT OR IGNORE INTO rubrics(id,event_id,version,name,created_at) VALUES(?,?,1,?,?)",
            (rubric_id, event["id"], "Fixture rubric", now),
        )
        criteria_names = sorted({name for score in fixture["scores"] for name in score["criteria"]})
        for index, name in enumerate(criteria_names):
            db.execute(
                """INSERT OR IGNORE INTO rubric_criteria
                (id,rubric_id,slug,name,weight,max_score,sort_order)
                VALUES(?,?,?,?,1,5,?)""",
                (f"{rubric_id}_{name}", rubric_id, name, name.title(), index),
            )

        for score in fixture["scores"]:
            assignment_id = f"asg_{score['judge']}_{score['project']}"
            scorecard_id = f"sc_{score['judge']}_{score['project']}"
            db.execute(
                """INSERT OR IGNORE INTO judge_assignments
                (id,event_id,project_id,judge_id,assigned_at,reason)
                VALUES(?,?,?,?,?,?)""",
                (assignment_id, event["id"], score["project"], score["judge"], now,
                 "Imported historical fixture review"),
            )
            db.execute(
                """INSERT OR IGNORE INTO scorecards
                (id,assignment_id,rubric_id,status,comment,updated_at,submitted_at)
                VALUES(?,?,?,'submitted',?,?,?)""",
                (scorecard_id, assignment_id, rubric_id, score.get("comment", ""), now, now),
            )
            for criterion, value in score["criteria"].items():
                db.execute(
                    """INSERT OR IGNORE INTO criterion_scores
                    (scorecard_id,criterion_id,score) VALUES(?,?,?)""",
                    (scorecard_id, f"{rubric_id}_{criterion}", value),
                )

        db.commit()

    _remove_demo_access(fixture)
    _ensure_demo_access(fixture)
    _bootstrap_admin()
    _print_demo_access()
