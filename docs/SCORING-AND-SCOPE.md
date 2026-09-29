# Scoring and out-of-scope audit

This audit applies the [published DOGFOOD scoring and out-of-scope rules](https://dogfoodhack.com/#scoring)
to the submitted `Addons` branch. It identifies evidence and limits; it is not
an organizer score or a substitute for the acceptance report.

The site's **40/25/20/15 weighting and five-point scale** describe how the
organizers evaluate *entries*. They do not prescribe a four-criterion rubric
for every event hosted by BeyondBug. In the portal, organizers configure their
own weighted criteria. A judge scores each criterion on a 0–5 scale; the raw
project score is the mean of completed judges' weighted scorecards. The
published ranking additionally adjusts for judge severity as described in
[JUDGING.md](../JUDGING.md). Raw and adjusted scores are both visible to organizers
and in the rankings export.

| Organizer criterion | Evidence in this repository | Honest limit |
| --- | --- | --- |
| Tier completion and correctness (40%) | The unedited [acceptance-report.txt](../acceptance-report.txt) passes all seven supplied T1/T2 checks. [TIER-COVERAGE.md](TIER-COVERAGE.md) maps the rest of the ladder. | `.dogfood.toml` claims only T1/T2. The supplied checker does not certify all UI flows or T3/T4. |
| Judging integrity (25%) | Backend denial of peer scores and cross-track assignment is checked in `tests/test_tier_isolation.py`; [JUDGING.md](../JUDGING.md) gives the calibration equations and fixture rank movement; `src/audit_view.py` renders organizer-readable history; [THREAT-MODEL.md](../THREAT-MODEL.md) covers vote abuse. | The assignment algorithm does not optimize judge overlap. Disconnected review graphs cannot be fully calibrated; account-based voting cannot prevent all Sybil accounts. |
| Adoptability and operability (20%) | `docker compose up` starts the local fixture and SQLite portal; [RELEASE-VERIFICATION.md](RELEASE-VERIFICATION.md) records fresh-volume, restart and network-disabled runtime checks. [DATA-MODEL.md](../DATA-MODEL.md) documents CSV, portable JSON, and full SQLite backup/restore. [LICENSE](../LICENSE) is MIT. | A first offline build needs the Docker base image cached. The portable JSON exchange does not restore historical review/vote/audit records; full SQLite restore does. Native ARM64 runtime was not tested. |
| Code quality and innovation (15%) | [ARCHITECTURE.md](../ARCHITECTURE.md) explains transactions, roles and schema boundaries; `tests/` includes 39 passing tests. Versioned rubrics, judge-severity calibration, and explainable review signals are implemented. | Maintainability and innovation require human review. The optional ML signal is advisory and must not be treated as proof of misconduct. |

| Published out-of-scope failure | Check in this project |
| --- | --- |
| 01. Mockups or hardcoded-data frontend | Pages render event, team, project, review and result records from SQLite. The committed [demo](../media/beyondbug-demo.mp4) walks a live event lifecycle. |
| 02. Cloud, hosted database or auth dependency | Docker runs one FastAPI process with SQLite, local sessions, vendored wheels and local assets. A network-disabled runtime was tested. The locally cached base-image requirement is stated above. |
| 03. Login-only authentication demo | Registration, team invitation, submission, judging, publication, voting and exports run after login; the browser demo and lifecycle tests exercise them. |
| 04. Gallery without judging, or judging without gallery | Both routes operate over the same event and project records; the official checker exercises gallery and judge endpoints. |
| 05. Frontend-only role checks | Protected reads and writes check session, event role, assignment and ownership in API routes. The official checker denies peer-score reads; `tests/test_tier_isolation.py` denies cross-track scoring. |
| 06. Undocumented architecture or undefended schema | [ARCHITECTURE.md](../ARCHITECTURE.md), [DATA-MODEL.md](../DATA-MODEL.md), and [JUDGING.md](../JUDGING.md) state the design, schema, invariants, and mathematical choices. |
| 07. Closed source or non-OSI license | The public repository has an MIT [LICENSE](../LICENSE). The bundled font includes its OFL notice. |
| 08. Custom hardware, GUI toolchain or proprietary runtime | Runtime requires Docker on a laptop. Optional browser tooling used during development is not part of startup. |
| 09. Renamed rewrite of an existing platform | The repository has its own schema, application code, commit history and design documents. Source provenance and authorship remain a process claim for the team to substantiate; no automated test can certify them. |

The remaining T3/T4 gaps are listed in [TIER-COVERAGE.md](TIER-COVERAGE.md).
