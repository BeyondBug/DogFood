# Dogfood 2026 pre-kickoff plan

Planning document only. No project code is written here. The coding window is
2026-09-26 18:00 UTC through 2026-09-29 18:00 UTC after the organizer's
September 26 Discord postponement. The full DOGFOOD context
provided by the user in this conversation is the requirements baseline for
the project. If a plan item conflicts with that text, correct the plan before
implementation rather than guessing.

Sources: the full user-provided brief, the organizer's September 26 Discord
update, https://dogfoodhack.com/ and https://dogfoodhack.com/spec/ . Recheck
the official Discord and spec page at kickoff for clarifications and checker
updates. The Discord update overrides the older dates on the website.

## Goal and order

Ship an honest, complete T2 portal first. Pass the published checker, then
verify the full T1/T2 lifecycle through independent integration tests and a
five-minute demo. Spend remaining time on one polished T3 slice or a bonus.
The checker currently contains seven checks and cannot verify T3/T4, so do not
claim those tiers until the organizers clarify how they will be verified.
Build the event landing page and role-specific workspaces to a professional
standard alongside these flows; see [UI-DESIGN.md](UI-DESIGN.md).

## Chosen stack and boundaries

- Python/FastAPI, SQLite, server-rendered Jinja templates, small amounts of
  JavaScript. Keep every UI mutation behind an authenticated API/service path.
- One application container on localhost:8080, one persistent SQLite volume,
  migration and idempotent fixture seed at startup. No hosted dependency.
- Session cookies: HttpOnly, SameSite=Lax, secure in production; password hashes
  with an established library; CSRF protection for cookie-authenticated writes.
- Enforce permissions in backend services and queries. Judge reads must be
  filtered by session principal, assignment, and track. Organizers can inspect
  all event records; participants can edit only their own team project.
- Store timestamps in UTC. Check submission deadline in the write transaction
  using server time; never trust browser time or hidden form fields.

## Core data model sketch

`users`, `sessions`, `events`, `event_roles`, `tracks`, `prizes`, `teams`,
`team_members`, `team_invites`, `projects`, `project_revisions`, `rubrics`,
`rubric_criteria`, `judge_tracks`, `judge_assignments`, `scorecards`,
`criterion_scores`, `audit_entries`. Use event-scoped foreign keys, unique
memberships, unique active project per team where the product requires it, and
unique judge/project scorecards. Preserve imported project IDs and mark
duplicate candidates for organizer review instead of silently discarding them.

## Judging design

1. Assign three judges per project when track capacity allows. Exclude a judge
   if their identity matches a team member or a declared conflict. Prefer
   matching tracks, then balance review load. Keep overlapping judge/project
   coverage for calibration, and save an assignment reason and batch ID.
2. Validate rubric weights, ranges, and version. A scorecard stores the rubric
   version used. Raw score is the weighted sum divided by total weight.
3. Estimate judge severity from *shared projects*, using a regularized model
   `score(j,p) = project_quality(p) + judge_offset(j) + error`. Shrink offsets
   toward zero when a judge has few shared reviews. Clip adjusted scores to the
   rubric range. Do not divide by judge standard deviation: a constant scorer
   has zero variance. Show raw and adjusted rankings, coverage, and uncertainty;
   flag projects with too few reviews. Document the exact calculation and its
   limits in JUDGING.md.
4. Results remain private until the organizer publishes them. Record edits,
   assignment changes, score submissions, and publication in an audit log.

## Published fixture facts

- 1 closed event, 8 tracks, 30 judges, 40 teams, 41 project records, 126
  scorecards. The event's submission deadline is 2026-03-01 18:00 UTC.
- The shared-project review graph connects all 30 judges. Judge workloads range
  from 1 to 11 reviews, so offset estimates need shrinkage and coverage labels.
- All scorecards use functionality, quality, and innovation. Project coverage:
  26 have three reviews, 8 have two, 4 have five, and 3 have four.
- `prj_41` duplicates `prj_07` by team and repository URL. Preserve both in
  seed data and flag the pair. Judge `jdg_07` gives the same criterion vector
  to all three projects reviewed; normalization must handle zero variance.
- Team names repeat. Use IDs, not names, as keys. Two judges have only one
  fixture score each, so calibration must avoid large one-review corrections.

## Acceptance contract as published before kickoff

The root `.dogfood.toml` gives the checker a base URL, role auth headers, and
routes. Its seven probes are:

The organizer's September 26 kickoff note asks teams to run it in the first
hour, print the four seed auth headers, and retain the fixture's historical
`submissions_close` date. We will follow that order.

1. Anonymous gallery GET returns 200.
2. First gallery page includes one of the first three fixture project titles.
3. Participant POST to the closed fixture event returns 4xx.
4. Judge A GET for own scores returns 200.
5. Judge B GET for Judge A's score route returns 401 or 403.
6. Participant GET for judge scores returns 401 or 403.
7. Organizer CSV GET returns 200 with a comma in the first line.

The current checker marks only T1 and T2 as verifiable. The complete feature
descriptions on the main site still govern manual judging.

## Work sequence for the active builder pair

**Before kickoff:** BeyondBug is registered, but one human teammate and the AI
assistant are doing the active preparation. Agree on schema and API contracts;
choose a repository owner and demo narrator. Read the checker and fixtures.
Prepare to check official announcements at kickoff.

Preflight: confirm Docker, Python, Git, GitHub access, available hours, and
the demo recorder. The human owner handles registration, public-repo access,
and final submission. The assistant drafts and implements in the shared
workspace, with the human reviewing product decisions and demo behavior. If
other teammates become active, assign them a bounded package from
[DELIVERY-BOARD.md](DELIVERY-BOARD.md). No project code or code commit occurs
before kickoff.

The fixture event is already closed. The live lifecycle test and demo must
create a separate event with future dates; the historical fixture event remains
closed for the acceptance probe. Detailed gates and route agreements are in
[DELIVERY-BOARD.md](DELIVERY-BOARD.md) and [API-CONTRACT.md](API-CONTRACT.md).

**0–12 hours:** Create repository, license, Compose setup, migrations, seed,
authentication, roles, event and team flows, submission deadline enforcement,
gallery. Make the T1 checker pass immediately.

**12–36 hours:** Judge invitations/assignments, rubric editor, scorecards,
backend permission tests, progress view, CSV exports. Make the T2 checker pass.

**36–54 hours:** Normalization proof on fixture data, auditability, end-to-end
workflow, organizer usability, and focused security tests. Add one T3/bonus
slice only after T2 is stable.

**54–72 hours:** Offline boot check, fresh-volume seed check, acceptance report,
documentation, five-minute lifecycle recording, public repository, honest tier
claim and final submission. Freeze time is 2026-09-29 18:00 UTC.

The active pair works through platform/auth, participant flows, judging,
operations, and demo in that dependency order. Parallel work packages are
reserved for teammates who join later. The schema and API contract have one
owner at a time to keep integration coherent.

## Gates that matter more than feature count

- A fresh `docker compose up` produces fixture-backed pages and documented
  seed credentials. Test again after disconnecting network access, with local
  images and dependencies already available.
- Direct HTTP tests verify denied peer score reads, cross-track access,
  participant access, deadline bypass attempts, and owner-only project edits.
- Imported IDs and historical scorecards survive restart; seeding is
  idempotent and does not overwrite live edits.
- README, ARCHITECTURE.md, DATA-MODEL.md, JUDGING.md, LICENSE,
  `.dogfood.toml`, tests, and the unedited checker output are in the repo.
- The demo shows create → register/team → submit → assign → score → publish.
