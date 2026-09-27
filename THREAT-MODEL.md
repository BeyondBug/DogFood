# Threat model

## Scope and assets

BeyondBug protects accounts, team drafts, judge assignments and scorecards,
private rankings and ballot totals, and the publication decision. The browser and any direct
HTTP client are untrusted. The local operator controls the Docker host and
SQLite file; this release does not claim to resist a malicious host operator.
The main boundary is between public routes, event-scoped roles, and the
database transaction that changes records.

| Abuse case | Current control | Residual risk or next step |
| --- | --- | --- |
| Judge reads peer scores through an altered query or direct curl | Session identity is checked against the requested judge ID; organizer exports and rankings have separate role checks. The official checker and integration tests exercise denial. | Review any new route that joins scorecards before release. |
| Participant changes another team's project | Team membership is checked from the session inside a write transaction. | There is no project revision history. A mistaken edit before close needs a team correction. |
| Deadline gaming through browser clock, replay, or simultaneous requests | UTC server time is checked inside `BEGIN IMMEDIATE` for project and team writes. The fixture's closed event rejects writes. Team membership freezes at submission close, preserving conflict checks. Organizer date edits are audited, cannot extend a closed window or move submission close into a configured voting window, and lock after a ballot is cast. | A trusted host operator can change system time. Future work could record a monotonic submission receipt or independent time source, but that conflicts with offline operation. |
| Stolen or reused team/judge invite | Random token is stored only as SHA-256, expires, and can be accepted once. Judge acceptance requires the invited email. Team join and size are checked atomically. | A stolen team link can be used first by another account; captain must share it privately. No email verification is provided. |
| Judge collusion or a declared conflict after assignment | Track eligibility, team membership, and recorded conflict checks precede assignment. A judge can report a conflict only on their own unsubmitted assignment; the assignment is revoked, the report is audited, and re-assignment excludes that judge/project pair. Organizer sees the new coverage gap. | The system cannot infer hidden relationships or coordinated scores. Submitted conflicts require manual resolution; there is no adjudication workflow. |
| Score manipulation through incomplete or out-of-range data | A submitted scorecard needs every rubric criterion and values in 0–5. Only its assigned judge may write. Publication requires closed submissions and locks both scores and projects. | A judge can still give dishonest valid scores; normalization is not a fraud detector. |
| CSV injection into an organizer's spreadsheet | Exports use CSV quoting and prefix dangerous text beginning with `=`, `+`, `-`, or `@`. | Spreadsheet programs vary; open exports in a trusted viewer when handling untrusted content. |
| Cross-site write using browser cookies | Cookies are HttpOnly and SameSite=Strict. An explicit foreign `Origin` on a write is rejected. | There is no dedicated CSRF token. Deploy behind one HTTPS origin and set `DOGFOOD_COOKIE_SECURE=1`. |
| Password guessing or account creation spam | Passwords use salted PBKDF2; sessions are random, hashed in storage, expiring and revocable. SQLite tracks failed logins by keyed account and client-IP digests; five failures per account or twenty per IP in ten minutes block further attempts, including a correct password. Unknown accounts run a dummy password check. | Shared IPs can be temporarily blocked, and multiple IPs can bypass per-IP limits. There is no account verification, MFA, or recovery flow yet. The login limiter does not limit account registration. |
| Submission scraping | The gallery intentionally exposes submitted titles, summaries, teams, and links. Drafts and scores are not public. | Public content can be copied; future per-IP limits or robots policy can reduce automated load, not prevent copying. |
| Duplicate submissions and copied repositories | Equal repository URLs in an event are flagged; duplicates remain visible but are unranked pending organizer review. | A changed URL can bypass detection, and legitimate forks can be flagged. Human review is required. |
| Sybil voting or ballot stuffing | Organizers can choose curated email-bound invite links or participants registered before voting opens. The database permits one ballot per account and event. The write route checks eligibility and rejects self-votes and duplicate projects. Account and keyed IP-digest limits count failed and successful attempts, and organizer-only attempt summaries expose suspicious patterns. | Email matching does not prove inbox ownership. Earlier fake accounts, shared networks, coordinated voters, and invitation sharing remain possible. A trusted voter roster or offline identity verification is needed for high-stakes awards. |
| Ballot position bias or premature results | A per-event secret seeds a stable HMAC order for each voter. Vote totals and judge rankings are restricted to organizers until publication, and publication waits for voting close. | Organizers can see interim totals and may influence decisions. A malicious host operator can read or alter them. |
| Comment spam or harassment | Comments require a login, open only during voting, reject exact repeats, and limit each account to five per hour. Organizers can hide comments; creation and moderation are audited. | Multiple accounts can bypass limits. There is no automated content screening or appeal flow. |
| Host/database tampering | Audit rows show actor, entity, action, time, and details to organizers. A consistent backup can be taken with `src.backup`. | SQLite and its audit rows are mutable by the host operator. A signed external transparency log would be needed for tamper evidence. |

## Review priorities before wider deployment

1. Add account verification and a local recovery flow without creating a
   hosted dependency; decide how operators should handle lost passwords.
2. Add a workflow for submitted conflicts, score corrections, and versioned
   result republication.
3. Test reverse proxy headers and Secure cookies under the intended HTTPS
   deployment, then remove demo mode and its fixed credentials.
4. For high-stakes community awards, curate the voter roster and add offline
   identity checks. One-account-one-vote is insufficient when accounts are
   cheap to create.
