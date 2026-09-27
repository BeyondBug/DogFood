# Release verification

Verified on 2026-09-27 after kickoff, on Linux x86-64. The checks below were
repeated after the final application and wheel changes, before promotion to
`Develop` and `main`.

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
python3 -m unittest discover -s tests -v
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
