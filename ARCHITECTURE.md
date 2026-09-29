# Architecture

## One local service

`docker compose up` builds one Python 3.12 image and starts one FastAPI/Uvicorn
worker on `127.0.0.1:8080`. SQLite lives on the `portal-data` named volume.
The image installs pinned wheels from `vendor/wheels` with `--no-index` and
serves Jinja templates, JavaScript, CSS, and IBM Plex Sans from its own
filesystem. There are no outbound runtime calls or hosted services.

Startup applies SQLite schema migrations (`PRAGMA user_version` 1 through 11),
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
Failed logins are counted per account and keyed client-IP digest in SQLite;
five failures per account or twenty per IP in ten minutes return 429. The
HMAC key is generated locally and persists with the database.

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
| `src/ml_insight.py` | Standard-library inference over the reviewed compressed v2 tree export |
| `src/audit_view.py` | Plain-language actor, action, target and category presentation for organizers |
| `src/public.py` | Voting configuration, eligibility, ballots, attempts, comments, moderation |
| `src/certificates.py` | Prize assignment, certificate issuance and public verification |
| `src/stretch.py` | Pairwise ranking, optional signed callbacks, bulk import, embeds, archives, and signed judge records |
| `src/submission_questions.py` | Organizer-defined project questions, private answers, and required-answer enforcement |
| `src/portable_bundle.py` | Bounded, transactional pre-judging event import and portable JSON export |
| `src/backup.py`, `src/restore.py` | Consistent SQLite snapshot and offline restore |
| `src/ui.py` | Public and role workspaces from live records |
| `src/main.py` | Application assembly, gallery, acceptance routes |

## Key invariants

- A write to a project checks the server's UTC time inside the same database
  transaction. The fixture event is deliberately closed. Drafts and
  submissions share one project record and can be edited only by team members
  before the deadline.
- An organizer can edit event dates before publication. The submission close
  must remain before configured voting opens and cannot be extended once the
  window has closed. Dates lock once a ballot is cast. This prevents later
  schedule edits from reopening submissions or changing the judging roster.
- A team invite is a hashed, expiring, single-use token. Membership is checked
  under a write lock, and the service enforces the four-member limit. Team
  creation, invite creation, and invite acceptance stop at submission close,
  keeping judge conflict checks tied to a fixed membership roster.
- Each scorecard belongs to one assignment and rubric version. A judge cannot
  score another assignment, an unassigned project, or a project with a
  declared conflict. Assignment and scoring wait until submissions close, so
  a review cannot target a project or team roster that participants can still
  edit. All criteria are required for final submission, and scores must be
  finite values on the rubric scale.
- Batch assignment considers accepted judges with matching tracks and excludes
  team members and declared conflicts. It reports uncovered projects instead
  of silently assigning ineligible judges.
- A judge can report a conflict on their own unsubmitted assignment. The
  transaction records the conflict, removes that assignment and any draft,
  and audits the report. The next batch excludes that judge/project pair.
- Public pages query rankings only after publication. Publishing results
  requires closed submissions, adjudication of automatic duplicate signals,
  and at least one completed review per nonduplicate project. One-review
  projects or disconnected review groups require explicit organizer
  acknowledgement, which is recorded in the audit entry. Published events reject
  later project creation and edits so the public ranking cannot drift.
- A ballot belongs to exactly one account and event by database constraint.
  Eligible choices exclude the voter's team and flagged duplicates. A secret
  event seed drives stable per-voter HMAC ordering. Attempt logs store a keyed
  IP digest instead of the address, and rate limits use account and digest.
- Voting eligibility and the window are rechecked inside the vote transaction.
  Organizer configuration locks once ballots exist. Comments are accepted only
  during voting, are rate limited, and can be hidden with an audit entry.
- Only an organizer can assign a configured prize to a submitted, nonduplicate
  project after results publication. Certificate issuance runs in one write
  transaction, joins actual project team members, and is idempotent under
  unique indexes. Award assignments lock after winner records issue. Public
  verification looks up the opaque certificate ID against the local database;
  these records are not cryptographically signed.

## Operations and limits

The DB file is the operational state. `src.backup` uses SQLite's online backup
API to produce a consistent copy while the portal is running. `src.restore`
validates and restores a snapshot while the portal is stopped, retaining a
safety copy of the previous database. Migrations run forward at startup; take
a backup before upgrading. CSV exports provide paths
out for projects, participants, teams, judges, assignments, scorecards,
rankings, audit history, votes, and certificates. Fixture JSON is an initial
import format for initial fixture seeding. The portable JSON bundle moves
pre-judging event data into an empty open event with new local IDs. A whole
SQLite snapshot can restore a complete BeyondBug installation, including
historical results and audit data.
The admin overview reads disk and database size, offers an on-demand
`PRAGMA quick_check`, and writes/downloads SQLite snapshots through
administrator-only routes. Snapshots live under the data volume, outside
public static assets. An operator must copy them off-host and arrange any
retention. Webhook delivery is optional: each audited event action writes a
delivery row in the same database transaction; the single-process worker sends
HMAC-signed callbacks with bounded retries. Receiver failure never rolls back
the event action. The widget reads the public gallery without credentials.
Judge records sign a fixed JSON payload with a locally stored Ed25519 key.
Public verification checks the payload against its stored public key; an
operator must publish or pin that key independently for third parties to
authenticate the issuer. The private key must be backed up separately from
the SQLite snapshot if the installation will continue issuing records after
a restore.

The event is served by a single process on one host. A larger deployment would
need shared database, job queue, dedicated rate limiting, observability, and
an explicit result correction/versioning workflow. Audit entries help an
organizer understand actions, but a database administrator can alter them;
they are not tamper-evident records.
The short read-only gallery probe and its measured limits are recorded in
[CAPACITY.md](docs/CAPACITY.md). It is not evidence for concurrent write capacity.
