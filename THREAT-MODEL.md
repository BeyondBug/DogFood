# Threat model

## Scope and assets

BeyondBug protects accounts, team drafts, judge assignments and scorecards,
private rankings, and the publication decision. The browser and any direct
HTTP client are untrusted. The local operator controls the Docker host and
SQLite file; this release does not claim to resist a malicious host operator.
The main boundary is between public routes, event-scoped roles, and the
database transaction that changes records.

| Abuse case | Current control | Residual risk or next step |
| --- | --- | --- |
| Judge reads peer scores through an altered query or direct curl | Session identity is checked against the requested judge ID; organizer exports and rankings have separate role checks. The official checker and integration tests exercise denial. | Review any new route that joins scorecards before release. |
| Participant changes another team's project | Team membership is checked from the session inside a write transaction. | There is no project revision history. A mistaken edit before close needs a team correction. |
| Deadline gaming through browser clock, replay, or simultaneous requests | UTC server time is checked inside `BEGIN IMMEDIATE` for project writes. The fixture's closed event rejects writes. | A trusted host operator can change system time. Future work could record a monotonic submission receipt or independent time source, but that conflicts with offline operation. |
| Stolen or reused team/judge invite | Random token is stored only as SHA-256, expires, and can be accepted once. Judge acceptance requires the invited email. Team join and size are checked atomically. | A stolen team link can be used first by another account; captain must share it privately. No email verification is provided. |
| Judge collusion or a declared conflict after assignment | Track eligibility, team membership, and recorded conflict checks precede assignment. Organizer sees assignment and score progress; score writes are audited. A new conflict revokes an unsubmitted assignment. | The system cannot infer hidden relationships or coordinated scores. Submitted conflicts require manual resolution; there is no adjudication workflow. |
| Score manipulation through incomplete or out-of-range data | A submitted scorecard needs every rubric criterion and values in 0–5. Only its assigned judge may write. Publication locks edits. | A judge can still give dishonest valid scores; normalization is not a fraud detector. |
| CSV injection into an organizer's spreadsheet | Exports use CSV quoting and prefix dangerous text beginning with `=`, `+`, `-`, or `@`. | Spreadsheet programs vary; open exports in a trusted viewer when handling untrusted content. |
| Cross-site write using browser cookies | Cookies are HttpOnly and SameSite=Strict. An explicit foreign `Origin` on a write is rejected. | There is no dedicated CSRF token. Deploy behind one HTTPS origin and set `DOGFOOD_COOKIE_SECURE=1`. |
| Password guessing or account creation spam | Passwords use salted PBKDF2; sessions are random, hashed in storage, expiring and revocable. | No login rate limit, account verification, or recovery flow yet. Restrict network exposure until these are added. |
| Submission scraping | The gallery intentionally exposes submitted titles, summaries, teams, and links. Drafts and scores are not public. | Public content can be copied; future per-IP limits or robots policy can reduce automated load, not prevent copying. |
| Duplicate submissions and copied repositories | Equal repository URLs in an event are flagged; duplicates remain visible but are unranked pending organizer review. | A changed URL can bypass detection, and legitimate forks can be flagged. Human review is required. |
| Sybil voting or ballot stuffing | There is no voting endpoint in this T1/T2 release, so no community ballot exists to stuff. | Before T3, add verified eligibility, one vote per eligible identity, rate limits, randomized ballot order, duplicate detection, and a privacy-conscious audit trail. Email alone would not stop Sybils. |
| Host/database tampering | Audit rows show actor, entity, action, time, and details to organizers. A consistent backup can be taken with `src.backup`. | SQLite and its audit rows are mutable by the host operator. A signed external transparency log would be needed for tamper evidence. |

## Review priorities before wider deployment

1. Add login rate limiting and account verification without creating a hosted
   dependency; document recovery for lost passwords.
2. Add a workflow for submitted conflicts, score corrections, and versioned
   result republication.
3. Test reverse proxy headers and Secure cookies under the intended HTTPS
   deployment, then remove demo mode and its fixed credentials.
4. If community voting is built, model the adversary before exposing a ballot.
   One-account-one-vote is not sufficient when accounts are cheap to create.
