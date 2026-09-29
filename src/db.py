"""SQLite connections and the first version of the local schema."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def database_path() -> Path:
    return Path(os.getenv("DOGFOOD_DB_PATH", "/data/portal.sqlite3"))


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(database_path(), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 10000")
    return db


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    password_hash TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    registration_open TEXT,
    registration_close TEXT,
    submissions_open TEXT,
    submissions_close TEXT NOT NULL,
    judging_open TEXT,
    judging_close TEXT,
    results_published_at TEXT,
    created_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_roles (
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('participant','judge','organizer')),
    PRIMARY KEY(event_id, user_id, role)
);
CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    UNIQUE(event_id, name)
);
CREATE TABLE IF NOT EXISTS prizes (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_members (
    team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('captain','member')),
    joined_at TEXT NOT NULL,
    PRIMARY KEY(team_id, user_id)
);
CREATE TABLE IF NOT EXISTS team_invites (
    token_hash TEXT PRIMARY KEY,
    team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    created_by TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    max_uses INTEGER NOT NULL DEFAULT 1,
    uses INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    team_id TEXT NOT NULL REFERENCES teams(id),
    track_id TEXT NOT NULL REFERENCES tracks(id),
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    repo_url TEXT NOT NULL DEFAULT '',
    demo_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('draft','submitted')),
    submitted_at TEXT,
    updated_at TEXT NOT NULL,
    duplicate_of TEXT REFERENCES projects(id)
);
CREATE INDEX IF NOT EXISTS ix_projects_event_status ON projects(event_id, status);
CREATE INDEX IF NOT EXISTS ix_projects_team ON projects(team_id);
CREATE TABLE IF NOT EXISTS judge_profiles (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'accepted',
    UNIQUE(event_id, user_id)
);
CREATE TABLE IF NOT EXISTS judge_tracks (
    judge_id TEXT NOT NULL REFERENCES judge_profiles(id) ON DELETE CASCADE,
    track_id TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    PRIMARY KEY(judge_id, track_id)
);
CREATE TABLE IF NOT EXISTS rubrics (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(event_id, version)
);
CREATE TABLE IF NOT EXISTS rubric_criteria (
    id TEXT PRIMARY KEY,
    rubric_id TEXT NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    weight REAL NOT NULL CHECK(weight > 0),
    max_score REAL NOT NULL CHECK(max_score > 0),
    sort_order INTEGER NOT NULL,
    UNIQUE(rubric_id, slug)
);
CREATE TABLE IF NOT EXISTS judge_assignments (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    judge_id TEXT NOT NULL REFERENCES judge_profiles(id) ON DELETE CASCADE,
    assigned_at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    UNIQUE(project_id, judge_id)
);
CREATE TABLE IF NOT EXISTS scorecards (
    id TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL UNIQUE REFERENCES judge_assignments(id) ON DELETE CASCADE,
    rubric_id TEXT NOT NULL REFERENCES rubrics(id),
    status TEXT NOT NULL CHECK(status IN ('draft','submitted')),
    comment TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    submitted_at TEXT
);
CREATE TABLE IF NOT EXISTS criterion_scores (
    scorecard_id TEXT NOT NULL REFERENCES scorecards(id) ON DELETE CASCADE,
    criterion_id TEXT NOT NULL REFERENCES rubric_criteria(id),
    score REAL NOT NULL,
    PRIMARY KEY(scorecard_id, criterion_id)
);
CREATE TABLE IF NOT EXISTS audit_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT REFERENCES events(id),
    actor_user_id TEXT REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS judge_invites (
    token_hash TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    email TEXT NOT NULL COLLATE NOCASE,
    created_by TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    accepted_at TEXT
);
CREATE TABLE IF NOT EXISTS judge_conflicts (
    judge_id TEXT NOT NULL REFERENCES judge_profiles(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(judge_id, project_id)
);
"""

SCHEMA_V3 = """
ALTER TABLE events ADD COLUMN voting_open TEXT;
ALTER TABLE events ADD COLUMN voting_close TEXT;
ALTER TABLE events ADD COLUMN voting_mode TEXT NOT NULL DEFAULT 'disabled'
    CHECK(voting_mode IN ('disabled','invite_only','participants'));
ALTER TABLE events ADD COLUMN ballot_seed TEXT;
CREATE TABLE voter_invites (
    token_hash TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    email TEXT NOT NULL COLLATE NOCASE,
    created_by TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    accepted_at TEXT,
    voter_user_id TEXT REFERENCES users(id),
    UNIQUE(event_id,email)
);
CREATE TABLE ballots (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    voter_user_id TEXT NOT NULL REFERENCES users(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    cast_at TEXT NOT NULL,
    UNIQUE(event_id,voter_user_id)
);
CREATE TABLE vote_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    voter_user_id TEXT NOT NULL REFERENCES users(id),
    ip_hash TEXT NOT NULL,
    outcome TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX ix_vote_attempts_user_time ON vote_attempts(event_id,voter_user_id,created_at);
CREATE INDEX ix_vote_attempts_ip_time ON vote_attempts(event_id,ip_hash,created_at);
CREATE TABLE comments (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    hidden_at TEXT,
    hidden_by TEXT REFERENCES users(id)
);
CREATE INDEX ix_comments_project_time ON comments(project_id,created_at);
"""

SCHEMA_V4 = """
CREATE TABLE event_awards (
    prize_id TEXT PRIMARY KEY REFERENCES prizes(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id),
    assigned_by TEXT NOT NULL REFERENCES users(id),
    assigned_at TEXT NOT NULL
);
CREATE INDEX ix_event_awards_event ON event_awards(event_id);
CREATE TABLE certificates (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    kind TEXT NOT NULL CHECK(kind IN ('participant','winner')),
    prize_id TEXT REFERENCES prizes(id),
    issued_at TEXT NOT NULL,
    CHECK((kind='participant' AND prize_id IS NULL) OR
          (kind='winner' AND prize_id IS NOT NULL))
);
CREATE UNIQUE INDEX ix_certificates_participant ON certificates(event_id,user_id)
    WHERE kind='participant';
CREATE UNIQUE INDEX ix_certificates_winner ON certificates(event_id,user_id,prize_id)
    WHERE kind='winner';
CREATE INDEX ix_certificates_user ON certificates(user_id,event_id);
"""

SCHEMA_V5 = """
CREATE TABLE app_keys (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO app_keys(name,value) VALUES('auth_rate_secret',lower(hex(randomblob(32))));
CREATE TABLE login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_digest TEXT NOT NULL,
    ip_digest TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('failed','rate_limited')),
    created_at TEXT NOT NULL
);
CREATE INDEX ix_login_attempts_account_time ON login_attempts(account_digest,created_at);
CREATE INDEX ix_login_attempts_ip_time ON login_attempts(ip_digest,created_at);
"""

SCHEMA_V6 = """
CREATE TABLE IF NOT EXISTS certificate_designs (
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('participant','winner')),
    layout TEXT NOT NULL CHECK(layout IN ('classic','modern','bold')),
    palette TEXT NOT NULL CHECK(palette IN ('teal','blue','coral','gold','violet')),
    issuer_line TEXT NOT NULL,
    updated_by TEXT NOT NULL REFERENCES users(id),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(event_id,kind)
);
"""

SCHEMA_V7 = """
ALTER TABLE projects ADD COLUMN thumbnail_url TEXT NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN image_urls TEXT NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN video_url TEXT NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN live_url TEXT NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN tech_tags TEXT NOT NULL DEFAULT '';
"""

SCHEMA_V8 = """
CREATE TABLE IF NOT EXISTS duplicate_decisions (
    project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    canonical_project_id TEXT REFERENCES projects(id),
    decision TEXT NOT NULL CHECK(decision IN ('confirmed','cleared')),
    reason TEXT NOT NULL,
    decided_by TEXT NOT NULL REFERENCES users(id),
    decided_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_duplicate_decisions_event ON duplicate_decisions(event_id,decision);
"""

SCHEMA_V9 = """
CREATE TABLE pairwise_assignments (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    judge_id TEXT NOT NULL REFERENCES judge_profiles(id) ON DELETE CASCADE,
    project_a_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_b_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    winner_id TEXT REFERENCES projects(id),
    assigned_at TEXT NOT NULL,
    submitted_at TEXT,
    CHECK(project_a_id < project_b_id),
    CHECK(winner_id IS NULL OR winner_id=project_a_id OR winner_id=project_b_id),
    UNIQUE(event_id,judge_id,project_a_id,project_b_id)
);
CREATE INDEX ix_pairwise_event ON pairwise_assignments(event_id,submitted_at);
CREATE TABLE judge_participation_records (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    judge_id TEXT NOT NULL REFERENCES judge_profiles(id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL,
    signature_b64 TEXT NOT NULL,
    public_key_pem TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    UNIQUE(event_id,judge_id)
);
CREATE TABLE webhooks (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE webhook_deliveries (
    id TEXT PRIMARY KEY,
    webhook_id TEXT NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','delivered','failed')),
    response_code INTEGER,
    error TEXT,
    created_at TEXT NOT NULL,
    attempted_at TEXT
);
CREATE INDEX ix_webhook_deliveries_webhook ON webhook_deliveries(webhook_id,created_at);
"""

SCHEMA_V10 = """
CREATE TABLE IF NOT EXISTS submission_questions (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    required INTEGER NOT NULL CHECK(required IN (0,1)),
    sort_order INTEGER NOT NULL,
    UNIQUE(event_id,sort_order)
);
CREATE TABLE IF NOT EXISTS project_answers (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES submission_questions(id) ON DELETE CASCADE,
    answer TEXT NOT NULL,
    PRIMARY KEY(project_id,question_id)
);
"""

SCHEMA_V11 = """
ALTER TABLE events ADD COLUMN open_link_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE events ADD COLUMN open_vote_token TEXT;
CREATE TABLE open_voters (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    browser_digest TEXT NOT NULL,
    first_ip_digest TEXT NOT NULL,
    user_agent_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(event_id,browser_digest)
);
CREATE TABLE open_ballots (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    open_voter_id TEXT NOT NULL REFERENCES open_voters(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id),
    cast_at TEXT NOT NULL,
    risk_signal TEXT NOT NULL DEFAULT '',
    UNIQUE(event_id,open_voter_id)
);
CREATE TABLE open_vote_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    open_voter_id TEXT REFERENCES open_voters(id) ON DELETE SET NULL,
    ip_digest TEXT NOT NULL,
    user_agent_digest TEXT NOT NULL,
    outcome TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX ix_open_vote_attempts_voter_time ON open_vote_attempts(event_id,open_voter_id,created_at);
CREATE INDEX ix_open_vote_attempts_ip_time ON open_vote_attempts(event_id,ip_digest,created_at);
"""


def initialize() -> None:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as db:
        db.execute("PRAGMA journal_mode = WAL")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 11:
            raise RuntimeError(f"Database schema version {version} is newer than this app")
        if version == 0:
            db.executescript(SCHEMA_V1)
            db.execute("PRAGMA user_version = 1")
            version = 1
        if version == 1:
            db.executescript(SCHEMA_V2)
            db.execute("PRAGMA user_version = 2")
            version = 2
        if version == 2:
            db.executescript(SCHEMA_V3)
            db.execute("PRAGMA user_version = 3")
            version = 3
        if version == 3:
            db.executescript(SCHEMA_V4)
            db.execute("PRAGMA user_version = 4")
            version = 4
        if version == 4:
            db.executescript(SCHEMA_V5)
            db.execute("PRAGMA user_version = 5")
            version = 5
        if version == 5:
            db.executescript(SCHEMA_V6)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(certificates)")}
            if "design_json" not in columns:
                db.execute("ALTER TABLE certificates ADD COLUMN design_json TEXT NOT NULL DEFAULT '{}'")
            db.execute("PRAGMA user_version = 6")
            version = 6
        if version == 6:
            db.executescript(SCHEMA_V7)
            db.execute("PRAGMA user_version = 7")
            version = 7
        if version == 7:
            db.executescript(SCHEMA_V8)
            db.execute("PRAGMA user_version = 8")
            version = 8
        if version == 8:
            db.executescript(SCHEMA_V9)
            db.execute("PRAGMA user_version = 9")
            version = 9
        if version == 9:
            db.executescript(SCHEMA_V10)
            db.execute("PRAGMA user_version = 10")
            version = 10
        if version == 10:
            db.executescript(SCHEMA_V11)
            db.execute("PRAGMA user_version = 11")
        db.commit()
