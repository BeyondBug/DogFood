# BeyondBug delivery board

Coding began after the revised 2026-09-26 18:00 UTC kickoff. This board tracks
the [challenge](https://dogfoodhack.com/) and the published checker alongside
the implementation. [README.md](README.md), tests, and the committed
[acceptance report](acceptance-report.txt) are the release evidence.

## Shared definition of done

A feature is done only when its HTTP path enforces the correct role and event
scope, its user path works, relevant edge cases are tested, and an organizer
can understand the result. Merge to `Develop` for integration; promote to
`main` only after verification. Keep failures and gaps visible.

## Time gates (UTC; add 5h 30m for IST)

| Gate | Deadline | Deliverable | Current state |
| --- | --- | --- | --- |
| G0 | Sep 26 18:00 | Recheck spec, checker, and Discord; first code commit may begin | Done; code started after kickoff |
| G1 | Sep 27 00:00 | Compose boots; migrations and fixture seed run; seed auth headers are printed; checker has been run once | Done |
| G2 | Sep 27 12:00 | T1 complete: auth, roles, event config, teams, drafts, deadline, gallery | Done; tests and checker pass |
| G3 | Sep 28 12:00 | T2 complete: invitations, assignment, rubric, scorecards, permissions, progress, CSV | Done ahead of gate; tests and checker pass |
| G4 | Sep 29 04:00 | Normalization, audit trail, ranking proof, operator polish | Normalization proof and audit documented; polish in progress |
| G5 | Sep 29 12:00 | Final docs, demo recording, fresh-volume and offline checks | Fresh-volume/offline checks done; video and release review pending |
| Freeze | Sep 29 18:00 | Public repo, acceptance report, honest tier claim, final submission | Public remote, video, submission pending |

Dates are gates, not an invitation to leave tests until the end. The release
buffer begins at G5, six hours before freeze.

## Work packages and ownership

One human teammate and the AI assistant are active. The human owns event
registration, repository access, product review, demo recording, and final
submission. The assistant performs the planned implementation and test work
in the shared workspace after kickoff. The table below is an ordered backlog,
not an assumption that four people are coding. If teammates join later, hand
them a bounded package with an explicit API/schema contract.

| Package | Priority | Owner | Dependency | Acceptance evidence |
| --- | --- | --- | --- | --- |
| Compose, migration, fixture seed, health | P0 | Active pair | None | Fresh boot; restart unchanged; fixture projects visible |
| Auth, sessions, role middleware | P0 | Active pair | Users schema | Login/logout; expired session denied; participant/judge/organizer distinct |
| Event, track, prize configuration | P0 | Active pair | Auth | Organizer can create and edit own event; other organizers denied |
| Teams and invite links | P0 | Active pair | Auth, event | Invite accepted once; max four; cross-event join denied |
| Draft and submission | P0 | Active pair | Teams, event | Edit before close; POST at/after close denied by server |
| Public searchable gallery | P0 | Active pair | Projects, seed | Anonymous 200; fixture title on first page; search/filter work |
| Judge invitation and assignment | P0 | Active pair | Projects, roles | Track/conflict rules; load balance; shortage visible |
| Weighted rubric, scorecards and judge console | P0 | Active pair | Assignments | Assigned judge scores own work; peer/cross-track denied |
| Progress dashboard and CSV | P0 | Active pair | Assignments, scores | Counts match DB; organizer export has stable headers |
| Normalization and result publication | P1 | Active pair | Scorecards | Raw/adjusted comparison; sparse/constant judge tests |
| Audit trail | P1 | Active pair | Service actions | Organizer sees who changed assignment/score/publication |
| Threat model and OpenAPI coverage | P1 | Active pair | Final routes | Docs match the shipped behavior; see [SECURITY-PLAN.md](SECURITY-PLAN.md) |
| Professional event and role UI | P1 | Active pair | T1/T2 paths | Responsive, accessible flows; see [UI-DESIGN.md](UI-DESIGN.md) |
| T3 voting/comments | P2 | Active pair | Stable T2 | Implemented and integration tested; not claimed because checker has no T3 assertions |
| Pairwise mode, T4 certificates/webhooks | P3 | Unassigned | Stable T2/T3 | Not implemented or claimed |

## Integration order

1. Agree on IDs, event scoping, transaction ownership, and response shapes in
   [API-CONTRACT.md](API-CONTRACT.md) before implementing routes. Keep one
   schema owner; any teammate who joins proposes changes through that owner.
2. In the first hour, seed the fixture event with its own
   `2026-03-01T18:00:00Z` submission close time, print four usable auth
   headers at startup, fill `.dogfood.toml`, and run the official checker once.
   Then ship a thin vertical path: fixture import → public gallery → local
   login → closed submission denial → judge score read → CSV. Rerun the checker
   after each relevant change.
3. Complete the real T1 lifecycle. The fixture event remains historically
   closed; create a separate open event in the UI for submission tests/demo.
4. Complete T2 with direct HTTP permission tests. Query parameters never grant
   identity or authorization.
5. Add normalization and operations proof, then one optional bonus slice if
   time and gates allow. Prefer normalization proof and a truthful threat model
   to a broad, unfinished T4.

If a `Develop` test fails, diagnose there but make the fix on `Features` and
merge again. `Develop` remains an integration branch, and `main` receives only
tested promotions.

## Required test matrix

| Test | Expected result |
| --- | --- |
| Anonymous gallery, fixture title | 200 and a known title in first response |
| Anonymous submission | 401/403 |
| Participant submits to closed fixture event | 4xx due to event deadline |
| Participant edits another team's project | 403/404 |
| Fifth member uses invite | Rejected atomically |
| Judge A reads own scores | 200 |
| Judge B requests Judge A's scores | 401/403 |
| Judge requests another track or unassigned project | 403/404 |
| Participant requests judge scores | 401/403 |
| Organizer exports CSV | 200, stable comma-separated header |
| Different event organizer mutates event | 403/404 |
| Fixture seed runs twice | No duplicate rows or overwritten edits |
| Constant scorer and one-review scorer | Finite, bounded normalized score |
| Results before/after publication | Private, then public as configured |

## Release artifacts

`README.md`, `ARCHITECTURE.md`, `DATA-MODEL.md`, `JUDGING.md`, `LICENSE`,
`docker-compose.yml`, `.dogfood.toml`, `acceptance-report.txt`, tests, and a
five-minute demo link. Update draft documents to describe actual behavior.
Use the official checker output verbatim. If its current seven checks remain
unchanged, it only verifies T1/T2; do not claim T3/T4 without organizer
clarification.
