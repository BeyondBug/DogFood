# Architecture

## One local service

`docker compose up` builds one Python 3.12 image and starts one FastAPI/Uvicorn
worker on `127.0.0.1:8080`. SQLite lives on the `portal-data` named volume.
The image installs pinned wheels from `vendor/wheels` with `--no-index` and
serves Jinja templates, JavaScript, CSS, and IBM Plex Sans from its own
filesystem. There are no outbound runtime calls or hosted services.

Startup applies SQLite schema migrations (`PRAGMA user_version` 1 through 3),
loads `fixtures.json` if its event is absent, and prints the demo auth headers
when demo mode is enabled. A restart leaves user changes intact. The health
route checks database access. A one-worker process keeps SQLite write
contention manageable for laptop-scale events; write operations use
`BEGIN IMMEDIATE`, a 10-second busy timeout, WAL, and foreign keys.

## Request path and trust boundary

```text
Browser / API client
        │ HTTP
        ▼
FastAPI route ── session lookup ── event role + object ownership check
        │                               │
        ├── JSON / HTML / CSV response  └── 401 / 403 / 409 when denied
        ▼
SQLite transaction ── domain rows + audit entry
```

The browser submits actions to the documented JSON API; pages render current
database records. An attacker can call those same routes directly, so the
server checks session identity and scope for every protected read and write.
The cookie contains an opaque random session token; SQLite stores only its
SHA-256 digest. Passwords use salted PBKDF2-HMAC-SHA256 with 260,000 rounds.
Login cookies are HttpOnly, SameSite=Strict, and optionally Secure behind
HTTPS. Requests presenting an `Origin` header from a different origin are
rejected for writes. Session tokens expire and logout removes the record.

Admin authority is a global `users.is_admin` flag provisioned through local
bootstrap environment variables; ordinary event roles live in `event_roles`.
The application distinguishes five actors:

| Actor | Scope |
| --- | --- |
| Visitor | Public event pages, submitted projects, published results and visible comments |
| Participant | Their event membership, team, draft and submission before deadline; a ballot when eligible |
| Judge | Their assigned projects and their own scorecards only |
| Organizer | Event setup, invitations, progress, all reviews, private ranking and vote tally, comment moderation, publication and exports for their event |
| Admin | Cross-event oversight and event administration |

The critical isolation path is `/api/judge/scores`: the requested judge ID
must belong to the current session. The assigned-scorecard write route checks
the assignment's judge user ID. Organizer exports and rankings require the
organizer role. Public results return 404 until publication. Result
publication locks later score edits, so visible rankings cannot drift.
During a configured voting window, publication is also blocked. Ballot totals
are organizer-only until publication; public vote results then become visible.

## Main modules

| Module | Responsibility |
| --- | --- |
| `src/db.py` | Connections, migrations, schema |
| `src/seed.py` | One-time fixture import and local bootstrap |
| `src/auth.py` | Passwords, session resolution, event role checks |
| `src/core.py` | Accounts, events, registration, teams, invites, project edits |
| `src/judging.py` | Judge invitation, rubric, assignments, scorecards, progress, exports, publication |
| `src/scoring.py` | Weighted averages, cross-judge calibration, ranking |
| `src/public.py` | Voting configuration, eligibility, ballots, attempts, comments, moderation |
| `src/ui.py` | Public and role workspaces from live records |
| `src/main.py` | Application assembly, gallery, acceptance routes |

## Key invariants

- A write to a project checks the server's UTC time inside the same database
  transaction. The fixture event is deliberately closed. Drafts and
  submissions share one project record and can be edited only by team members
  before the deadline.
- A team invite is a hashed, expiring, single-use token. Membership is checked
  under a write lock, and the service enforces the four-member limit.
- Each scorecard belongs to one assignment and rubric version. A judge cannot
  score another assignment, an unassigned project, or a project with a
  declared conflict. All criteria are required for final submission.
- Batch assignment considers accepted judges with matching tracks and excludes
  team members and declared conflicts. It reports uncovered projects instead
  of silently assigning ineligible judges.
- A judge can report a conflict on their own unsubmitted assignment. The
  transaction records the conflict, removes that assignment and any draft,
  and audits the report. The next batch excludes that judge/project pair.
- Public pages query rankings only after publication. Publishing results
  requires at least one completed review per nonduplicate project and records
  an audit entry.
- A ballot belongs to exactly one account and event by database constraint.
  Eligible choices exclude the voter's team and flagged duplicates. A secret
  event seed drives stable per-voter HMAC ordering. Attempt logs store a keyed
  IP digest instead of the address, and rate limits use account and digest.
- Voting eligibility and the window are rechecked inside the vote transaction.
  Organizer configuration locks once ballots exist. Comments are accepted only
  during voting, are rate limited, and can be hidden with an audit entry.

## Operations and limits

The DB file is the operational state. `src.backup` uses SQLite's online backup
API to produce a consistent copy while the portal is running. Migrations run
forward at startup; take a backup before upgrading. CSV exports provide paths
out for teams, projects, assignments, scorecards, and rankings. Fixture JSON
is an initial import format, not a general bulk import facility.

The event is served by a single process on one host. A larger deployment would
need shared database, job queue, dedicated rate limiting, observability, and
an explicit result correction/versioning workflow. Audit entries help an
organizer understand actions, but a database administrator can alter them;
they are not tamper-evident records.
