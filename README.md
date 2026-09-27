# BeyondBug

BeyondBug is an open-source, self-hosted hackathon portal built for DOGFOOD
2026. It covers registration, teams, submissions, the public gallery, judge
assignment, weighted scoring, normalized rankings, community voting, comments,
and result publication. Organizers can assign configured prizes after
publication and issue distinct participant and winner certificates. Each
public certificate ID can be checked against the local database. Visitors can
switch between light and dark modes; their choice persists in the browser.
The portal runs on one laptop with FastAPI, SQLite, and locally bundled assets.
Public visitors can browse and search events at `/events`; each event has its
own page and event-scoped gallery links. Galleries paginate beyond 48 projects,
so large events remain browsable.

Watch the [five-minute silent lifecycle demo](media/beyondbug-demo-silent.mp4),
captured from a running local event. Its captions show event creation, team
formation, draft and final submission, judge assignment and scoring, and
result publication. [DEMO-SCRIPT.md](DEMO-SCRIPT.md) lists the live actions for
a narrated recording.

## Run it

```sh
docker compose up
```

Open [http://localhost:8080](http://localhost:8080). On first boot the app
creates its SQLite database and loads the official `fixtures.json`: one closed
event, 8 tracks, 30 judges, 40 teams, 41 project records, and 126 historical
scorecards. The fixture event's original submission deadline is retained, so
late submissions are rejected. To demonstrate a live submission, sign in and
create a new event with a future deadline.

The image installs pinned Python wheels from `vendor/wheels` for Linux x86-64
and ARM64; fonts, scripts, templates, and fixture data are also local. The
container makes no external runtime requests. A first offline *build* needs
the matching `python:3.12-slim` base image already present in Docker's local
image store. No cloud account, hosted database, authentication provider, or
external API is used. [Release verification](RELEASE-VERIFICATION.md) records
the clean-build, fresh-volume, restart, and network-disabled checks.

## Demo access

The default Compose file enables local demo mode. These accounts all use the
password `BeyondBugDemo2026!` on the seeded portal:

| Role | Email | Main page |
| --- | --- | --- |
| Organizer | `organizer@beyondbug.local` | `/organizer/evt_01` |
| Judge A | `tomas.varga@example.org` | `/judge/evt_01` |
| Judge B | `wei.lindqvist@example.org` | `/judge/evt_01` |
| Participant | `priya1@example.org` | `/workspace/evt_01` |

Startup logs also print the four bearer headers used in `.dogfood.toml`.
Those fixed credentials are **demo only**. For a real deployment, use a fresh
volume, set `DOGFOOD_DEMO_MODE=0`, and configure
`DOGFOOD_BOOTSTRAP_EMAIL` and `DOGFOOD_BOOTSTRAP_PASSWORD` (at least 12
characters). Set `DOGFOOD_COOKIE_SECURE=1` when serving through HTTPS.
Disabling demo mode removes its known sessions and passwords from an existing
database too.

## Walk through one event

1. Sign in as the organizer, open `/dashboard`, and create an event with a
   guided four-step form for the description, UTC schedule, tracks, and prizes.
   Its unfinished values stay in this browser. The organizer desk
   has an Event details panel for later schedule and description edits.
2. Sign in as a participant, open the new event page, join, create a team,
   and copy a single-use invite link. Save a project draft, then submit it.
3. In the organizer desk, set rubric weights, create judge invites, choose
   their tracks, and batch assign projects. Invite status shows pending,
   accepted, and expired links. The desk shows setup readiness,
   its recommended next action, missing coverage, and pending reviews.
4. As an invited judge, open the judge desk, score only assigned projects,
   and submit a review. Drafts save after a short pause, while final submission
   remains explicit. The queue links directly to the next unfinished review.
   A judge can report a conflict from their queue before
   submitting; the assignment is removed and the organizer can reassign it.
   Another judge cannot read that scorecard.
5. The organizer reviews raw and calibrated rankings and publishes results.
   Submissions must be closed first. Public result routes return 404 until
   publication; project edits and submitted scores then lock.
6. For an event with an active voting window, the organizer chooses invited
   voters or existing participants. Eligible voters receive a stable shuffled
   ballot, cast one vote, and can comment on projects. The organizer sees
   attempt signals and moderates comments. Publishing waits until voting closes.
7. After publication, select winning projects for configured prizes and issue
   certificates. Team members can open `/my/certificates`, download vector
   artwork, or print from a public verification page.

The API driving these actions is documented at `/docs`, `/openapi.json`, and
the committed [OpenAPI specification](openapi.json).
The server enforces event roles, team membership, assignment ownership, and
deadlines for direct API requests as well as browser actions. Team membership
freezes at submission close, and published events reject project changes.
The participant workspace checks required and recommended submission fields
and previews the information a judge will see. It does not make external
requests to validate repository or demo links.

## Tests and acceptance

With the portal running:

```sh
python3 -m unittest discover -s tests -v
python3 run.py .dogfood.toml > acceptance-report.txt
```

`run.py` is the organizer's standard-library checker. The committed
`acceptance-report.txt` is its unedited output. Our tier claim is **T1 and
T2**. The checker verifies seven HTTP behaviors; the additional tests cover
the event lifecycle, deadline and role denials, publication lock, exports,
normalization edge cases, and voting abuse controls. The official checker has
no T3 assertions. Community voting and comments are implemented and covered
by our integration tests, but we leave T3 unclaimed because the checker cannot
verify it. The code and demo remain part of the evidence.
See [T3-EVIDENCE.md](T3-EVIDENCE.md) for the requirement-by-requirement test
map.

## Operate and extend

- Data lives in the named Compose volume at `/data/portal.sqlite3`. SQLite
  uses WAL, foreign keys, and schema migrations. Restarting does not replace
  user edits with fixture values.
- For a consistent live backup, run
  `docker compose exec portal python -m src.backup /data/portal-backup.sqlite3`,
  then `docker compose cp portal:/data/portal-backup.sqlite3 ./portal-backup.sqlite3`.
- Organizer CSV exports cover projects, teams, assignments, scorecards, and
  raw/adjusted rankings. Open them from the organizer desk or use the API.
- The default service binds only to `127.0.0.1:8080`. Put a TLS reverse proxy
  in front of it for a shared deployment; disable demo mode first.
- [CAPACITY.md](CAPACITY.md) gives measured local gallery throughput and the
  limits of the single-host SQLite design; this release does not claim a
  multi-instance load balancer.
- A locally bootstrapped global admin can open `/admin` to inspect event totals,
  data volume size and free space, run an on-demand SQLite integrity check,
  create an online backup, and download recent snapshots. Backup files stay
  under the local data volume; an operator must copy and protect them. No
  scheduled backup is claimed.

The active team develops on `Features`, tests integrations on `Develop`, and
promotes reviewed releases to `main`. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Known limits

- T3 is not claimed in `.dogfood.toml`: its voting and comment features work,
  but the supplied checker has no T3 checks. T4 is not claimed: certificates
  are implemented, while webhooks, signed judge records, widgets, and bulk
  import remain absent. Certificate verification depends on the local
  database, so it is not a cryptographic signature.
- Community voting cannot establish one human per account. Invite acceptance
  matches an account email but does not verify inbox ownership; participant
  mode excludes accounts created after voting opens, but earlier fake accounts
  remain possible. Use curated invites for high-stakes public prizes.
- Invite links are copied by an organizer or captain; the portal does not send
  email. There is no outbound email dependency.
- SQLite with one application worker suits small and medium self-hosted
  events. Multi-host deployment needs a different database and queue design.
- The administrator backup button creates local snapshots only. It does not
  schedule backups, move them off-host, or restore them through the browser.
- Login throttling persists in SQLite: five failed attempts per account or
  twenty per client IP in ten minutes return 429. Account recovery and email
  verification remain operator workflows, not built-in features.
- Published scores are locked. Correcting a submitted review after publication
  requires an explicit future workflow; this release does not provide one.
- Duplicate repository URLs are flagged and excluded from rankings pending
  organizer review. The heuristic can flag legitimate forks or miss copied
  work under a different URL.

## Project documents

- [ARCHITECTURE.md](ARCHITECTURE.md): deployment, trust boundaries, and choices
- [DATA-MODEL.md](DATA-MODEL.md): schema, seed import, exports, and migrations
- [JUDGING.md](JUDGING.md): assignment, score math, normalization, fixture proof
- [THREAT-MODEL.md](THREAT-MODEL.md): abuse cases, controls, and residual risks
- [UI-DESIGN.md](UI-DESIGN.md): visual direction and screen inventory
- [T3-EVIDENCE.md](T3-EVIDENCE.md): independently tested public-voting features
- [DEMO-SCRIPT.md](DEMO-SCRIPT.md): five-minute lifecycle recording plan
- [RELEASE-VERIFICATION.md](RELEASE-VERIFICATION.md): fresh-start and offline evidence
- [CAPACITY.md](CAPACITY.md): reproducible local read probe and scaling boundary

Licensed under [MIT](LICENSE). The bundled IBM Plex Sans files have their
own [SIL Open Font License](src/static/fonts/OFL.txt).
