# BeyondBug

BeyondBug is an open-source, self-hosted hackathon portal built for DOGFOOD
2026. It covers registration, teams, submissions, the public gallery, judge
assignment, weighted scoring, normalized rankings, community voting, comments,
and result publication.
The portal runs on one laptop with FastAPI, SQLite, and locally bundled assets.

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

The image installs pinned Python wheels from `vendor/wheels`; fonts, scripts,
templates, and fixture data are also local. The container makes no external
runtime requests. A first offline *build* needs the `python:3.12-slim` base
image already present in Docker's local image store. No cloud account,
hosted database, authentication provider, or external API is used.

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
   future submission deadline, tracks, and optional prizes. The organizer desk
   has an Event details panel for later schedule and description edits.
2. Sign in as a participant, open the new event page, join, create a team,
   and copy a single-use invite link. Save a project draft, then submit it.
3. In the organizer desk, set rubric weights, create judge invites, choose
   their tracks, and batch assign projects. The desk shows missing coverage.
4. As an invited judge, open the judge desk, score only assigned projects,
   and submit a review. A judge can report a conflict from their queue before
   submitting; the assignment is removed and the organizer can reassign it.
   Another judge cannot read that scorecard.
5. The organizer reviews raw and calibrated rankings and publishes results.
   Submissions must be closed first. Public result routes return 404 until
   publication; project edits and submitted scores then lock.
6. For an event with an active voting window, the organizer chooses invited
   voters or existing participants. Eligible voters receive a stable shuffled
   ballot, cast one vote, and can comment on projects. The organizer sees
   attempt signals and moderates comments. Publishing waits until voting closes.

The API driving these actions is documented at `/docs`, `/openapi.json`, and
the committed [OpenAPI specification](openapi.json).
The server enforces event roles, team membership, assignment ownership, and
deadlines for direct API requests as well as browser actions. Team membership
freezes at submission close, and published events reject project changes.

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

The active team develops on `Features`, tests integrations on `Develop`, and
promotes reviewed releases to `main`. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Known limits

- T3 is not claimed in `.dogfood.toml`: its voting and comment features work,
  but the supplied checker has no T3 checks. T4 webhooks, certificates,
  widgets, and bulk import are not implemented.
- Community voting cannot establish one human per account. Invite acceptance
  matches an account email but does not verify inbox ownership; participant
  mode excludes accounts created after voting opens, but earlier fake accounts
  remain possible. Use curated invites for high-stakes public prizes.
- Invite links are copied by an organizer or captain; the portal does not send
  email. There is no outbound email dependency.
- SQLite with one application worker suits small and medium self-hosted
  events. Multi-host deployment needs a different database and queue design.
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
- [DEMO-SCRIPT.md](DEMO-SCRIPT.md): five-minute lifecycle recording plan

Licensed under [MIT](LICENSE). The bundled IBM Plex Sans files have their
own [SIL Open Font License](src/static/fonts/OFL.txt).
