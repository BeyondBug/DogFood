# Security and abuse plan — pre-kickoff draft

This is a threat analysis for design work. It does not claim that a mitigation
has been implemented. The release threat model should mark each control as
tested, partial, or absent and name residual risk honestly.

## Assets and trust boundaries

Protect sessions, participant drafts, judge assignments and private scores,
unpublished rankings, invitation tokens, and the integrity of event deadlines.
The browser, query parameters, uploaded content, and CSV fields are untrusted.
The local application and SQLite database are under the operator's control;
an administrator with database access can alter data, so application audit
entries alone are not tamper proof.

## Threats to design and test

| Threat | Proposed control | Verification / residual risk |
| --- | --- | --- |
| Participant or judge changes an ID in a URL | Event scope and ownership checks in the service/query | Direct HTTP tests for peer score, other team, other track; 403/404 |
| Deadline gaming through browser clock or delayed request | Compare UTC server time in the write transaction; reject at `now >= close` | Boundary test; clock skew on host remains operator risk |
| Reused or guessed team invite | Long random token stored hashed, expiry, limited use, atomic max-four check | Reuse and fifth-member tests |
| Duplicate submission | Preserve records, flag matching team/repo and likely duplicate titles for organizer review | Fixture `prj_07`/`prj_41` shown and flagged; false positives require human review |
| Judge collusion or conflicts | Conflict declaration, track-aware assignment, independent reviews, audit trail, anomaly view | Hard to prove intent; organizer adjudication remains necessary |
| Score manipulation after submission | Rubric versioning, scorecard ownership, audit entries, explicit correction reason | Database administrator remains trusted |
| Session theft or CSRF | Opaque revocable cookie, HttpOnly/SameSite, secure production cookie, CSRF token on writes | Test logout/expiry and CSRF denial; TLS is operator deployment duty |
| Malicious HTML or uploaded media | Template escaping, file type/size limits, serve media with safe content type | Test unsafe input; antivirus scanning may be out of scope |
| CSV formula injection | Quote fields and neutralize spreadsheet formula prefixes in human-facing exports | Test `=`, `+`, `-`, `@`, tabs; document machine-export tradeoff |
| Submission scraping | Public gallery exposes only intended fields; bounded pagination and rate limits | Public data can still be copied; no false claim of prevention |
| Sybil or ballot stuffing (T3) | If voting ships: authenticated ballots, per-account limits, rate limits, randomized order, organizer-visible audit signals | Offline local email cannot prove unique humans; do not claim it can |

## Permission review checklist

Check every route under anonymous, participant, judge A, judge B, organizer of
the event, organizer of a different event, and admin. Pay special attention to
GET endpoints: hiding a button does not protect JSON or CSV. Keep private
scores and results out of public HTML, API responses, error messages, and
embedded widgets until publication.

