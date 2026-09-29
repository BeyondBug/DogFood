# Release verification

## Current status — 29 September 2026

| Check | Result |
| --- | --- |
| Official acceptance checker | **7/7 PASS; T1 and T2 verified** |
| Independent unit and HTTP integration suite | **31/31 PASS** |
| Disposable fresh-volume test runner | **31/31 PASS:** new Compose project and volume; removed after run |
| Fresh disposable Compose volume | **PASS on schema 9:** fixture seed, migrations, lifecycle, permissions, scoring, voting, certificates, pairwise ranking, signed records, webhooks, bulk import, embeds, backup, OpenAPI, and portable ML checks run before the volume is removed |
| Fresh portal checked by official `run.py` | **7/7 PASS** |
| Restart persistence | **PASS:** same event, project, judge, and local secret counts |
| Runtime with container network disabled | **PASS on schema 9 image:** isolated in Docker, local `/health` returned HTTP 200; webhooks remain optional |
| OpenAPI artifact synchronization | **PASS:** test compares committed JSON to FastAPI schema |
| Desktop and mobile visual review | **PASS:** Event Desk, Pulse, and Studio at 1440 px and 390 px; Studio light/dark, no mobile overflow, theme and mode persisted after reload |
| Portable ML inference | **PASS:** 300-tree JSON export matches trained scikit-learn decision score on a reference vector; organizer-only panel rendered on fixture in 0.13 s |
| Local gallery read probe | **PASS:** 500/500 at 20 workers and 1,000/1,000 at 50 workers; see [CAPACITY.md](CAPACITY.md) |
| Administrator backup | **PASS:** isolated portal created and downloaded a valid 1-event, 41-project SQLite snapshot; anonymous download returned 401 |
| Event page Back link | **PASS:** visible at mobile size with a direct-link fallback to the event directory |
| Five-minute lifecycle recording | **PASS:** fresh seeded portal, live browser actions through publication, direct peer-score HTTP 403, CSV download; 300-second H.264 file in `media/` |
| Certificate design studio | **PASS:** admin-only participant and winner previews/settings, separate layouts and accents, no issued rows from preview, design snapshots remain unchanged after later edits |
| Event creation authorization | **PASS:** participant, judge, and organizer accounts see no creation form and receive HTTP 403; only administrators may create events |
| Participant and judge onboarding | **PASS:** per-event team and draft progress, published anonymized feedback, admin-only judge and organizer provisioning, judge sign-in, password change, and organizer-only ML signals |

The canonical [acceptance-report.txt](acceptance-report.txt) is the unedited
checker output against localhost:8080. `.dogfood.toml` claims only T1/T2.
[T3-EVIDENCE.md](T3-EVIDENCE.md) records separately tested capabilities that
the supplied checker does not test. All checks above ran after the current
schema, certificates, theme, judging insight, review attention, and login-throttling changes.

## Verification history

Verified on 2026-09-27 after kickoff, on Linux x86-64. The checks below were
run during earlier implementation passes before promotion to `Develop` and
`main`.

## Clean build and seed

`docker build --network none --no-cache -t dogfood-portal:offline-check .`
completed using only files in this repository and a locally cached
`python:3.12-slim` base image. The local Python dependencies were installed
with `pip --no-index --find-links=/wheels` inside that build.

A separate `beyondbugfresh` Compose project on port 18080 created a new SQLite
volume. Its service became healthy and printed four usable checker auth
headers. The official checker returned **7/7 PASS** against that fresh portal.
The integration suite returned **14/14 PASS** against the same instance.

After the tests, the volume contained eight events and 48 projects, including
the fixture event. Restarting the container kept those counts unchanged; the
fixture's 30 judge profiles were not duplicated. The temporary project and
volume were removed after verification.

## Network-disabled runtime

The tested image was started with Docker's `--network none --pull never` and
a fresh temporary `/data` filesystem. An HTTP health request from inside the
container returned `{"status":"ok"}`. The database contained 41 fixture
projects and 30 judge profiles. This verifies startup and seeding without
container network access.

## ARM64 dependency bundle

`vendor/wheels` contains Linux x86-64 and ARM64 wheels for the binary
dependencies (`MarkupSafe` and `pydantic-core`); other dependencies are pure
Python. Offline `pip download --no-index --find-links vendor/wheels` resolved
the entire `requirements.txt` set for CPython 3.12 on Linux ARM64. An ARM64
container was not available here, so native ARM64 execution remains untested.

## Reproduce

```sh
docker compose up --build
python3 scripts/test_fresh.py
python3 run.py .dogfood.toml > acceptance-report.txt
```

The canonical [acceptance report](acceptance-report.txt) uses localhost:8080.
The official checker exercises seven HTTP behaviors; it does not verify all
UI paths, T3 voting, or the full ranking methodology. The independent suite
and [JUDGING.md](JUDGING.md) provide additional evidence. A fresh offline
*build* still requires the platform-specific Python base image in Docker's
local store; the repository does not include a Docker base-image tarball.

After the landing-page navigation and event-data correction, the local build
again passed all 14 integration tests and seven official checks. Desktop and
mobile screenshots were reviewed. A separate fresh-volume event was taken
through creation, team formation, draft and final submission, judge assignment,
scoring, and publication to refresh the committed silent demo.

The later public event directory and gallery pagination pass the expanded
15-test suite and the same seven official checks. A separate 49-project test
event verifies that the gallery exposes the project on page two. Desktop and
mobile gallery screenshots were reviewed.

The committed `openapi.json` was regenerated after those routes changed. A
test now compares the artifact with FastAPI's current schema so future route
changes cannot leave the published API description stale.

The judging integrity pass blocks batch assignment until submissions close,
blocks new assignments after publication, and rejects non-finite criterion
scores. The 16-test suite and all seven official checks pass after rebuilding
with these rules.
