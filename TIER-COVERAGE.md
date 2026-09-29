# DOGFOOD 2026 tier coverage

This maps the [published tier ladder](https://dogfoodhack.com/#tiers) to
working code and validation. The organizer's `run.py` has seven T1/T2 checks;
it does not certify every item below. `.dogfood.toml` claims **T1 and T2**.
The exact checker output is in [acceptance-report.txt](acceptance-report.txt).

| Tier | Published requirement | Current evidence | Status |
| --- | --- | --- | --- |
| T1 | Authentication and sessions | Local password/session routes in `src/core.py` and `src/auth.py`; logout and throttling tests in `tests/test_lifecycle.py` | Implemented |
| T1 | Visitor, participant, judge, organizer, admin roles | Backend role checks in `src/auth.py`, ownership checks on project and scorecard routes | Implemented |
| T1 | Event dates, tracks and prizes | Event create/update routes in `src/core.py`; organizer setup UI | Implemented |
| T1 | Team formation by invite link | Single-use team invitation and four-member cap in `src/core.py`; lifecycle tests | Implemented |
| T1 | Draft/edit submission until deadline | `src/main.py` creates; `src/core.py` edits; both check the server clock inside a transaction | Implemented |
| T1 | Deadline enforcement | Closed fixture submission is rejected by the official checker; lifecycle tests cover new events | Implemented |
| T1 | Public searchable/filterable gallery | `src/main.py` and `src/templates/gallery.html` provide search, track/technology filters and pagination | Implemented |
| T1 reference | Full media/link/tag field set and custom questions | Project schema and form include media, links, tags and track; `src/submission_questions.py` enforces event prompts | Implemented |
| T2 | Judge invitation and assignment | Invitation, admin provisioning and track-matched balanced batch in `src/judging.py` | Implemented |
| T2 | Weighted configurable rubric | Versioned rubric and weighted criteria in `src/judging.py`; scoring in `src/scoring.py` | Implemented |
| T2 | Backend role and track isolation | Peer-score denial in official checker; assignment and scorecard ownership checks; `tests/test_tier_isolation.py` exercises cross-track attack | Implemented |
| T2 | Live organizer progress | `/api/events/{id}/progress` and organizer desk show assigned/submitted counts and gaps | Implemented |
| T2 | Cross-judge normalization | Calibrated ranking in `src/scoring.py`, fixture demonstration in `JUDGING.md`, edge-case tests in `tests/test_scoring.py` | Implemented |
| T2 | CSV exports throughout workflow | Organizer exports for participants, teams, projects, judges, assignments, scores, rankings, votes, audit and certificates | Implemented |
| T3 | Configurable community voting | Invite-only and registered-participant modes in `src/public.py`; no anonymous open-link mode or verified email delivery | Partial |
| T3 | Comments | Window-limited, rate-limited comments with organizer moderation in `src/public.py` | Implemented |
| T3 | Hidden results during voting | Public results require publication; publication waits for voting to close | Implemented |
| T3 | Random ballot ordering | Per-voter HMAC order in `src/public.py`, tested in `tests/test_voting.py` | Implemented |
| T3 | Rate limits, duplicate checks, readable audit | Vote/comment limits, duplicate vote constraint, duplicate-project adjudication and organizer activity desk | Implemented; Sybil resistance is limited |
| T4 | REST API and webhooks covering UI actions | UI domain writes use the documented REST API; event audit writes enqueue signed webhooks in `src/webhooks.py` | Partial: login, local theme changes and some read actions do not emit webhooks |
| T4 | Certificates and records | `src/certificates.py` issues participation/winner certificates; `src/judge_records.py` issues judge records | Implemented |
| T4 | Signed publicly verifiable judge records | Ed25519 signature and public verification endpoint; tests detect tampering | Implemented; external issuer trust requires pinning the public key |
| T4 | Embeddable gallery | Public iframe route `/widgets/events/{id}/gallery`, organizer embed snippet and widget test | Implemented |
| T4 | Bulk import and export | CSV exports, portable pre-judging JSON bundle, full SQLite backup/restore; fixture test preserves 41 projects | Partial: portable JSON does not import historical reviews, ballots, certificates or audit entries |

`docker compose up` seeds the published fixture. The fresh-volume suite, exact
official checker and network-disabled startup are recorded in
[RELEASE-VERIFICATION.md](RELEASE-VERIFICATION.md). T3 voting limitations are
expanded in [T3-EVIDENCE.md](T3-EVIDENCE.md) and [THREAT-MODEL.md](THREAT-MODEL.md).
