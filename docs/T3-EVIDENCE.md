# T3 public features: independent evidence

The supplied `run.py` checks seven T1/T2 HTTP behaviors and has no T3
assertions. `.dogfood.toml` therefore claims T1 and T2 only. The features
below are implemented and exercised by our own tests; **T3 is not described
as checker-verified**.

| DOGFOOD T3 requirement | Working path and boundary | Test evidence |
| --- | --- | --- |
| Configurable community voting | Organizer configures `disabled`, `invite_only`, `participants`, or `open_link` at `PUT /api/events/{id}/voting`. Account voters use the event ballot; open-link voters use an opaque share URL and anonymous browser identity. | `tests/test_voting.py`: invitation, participant, and open-link lifecycle tests |
| Project comments | Signed-in visitors post during the voting window; public readers see visible comments; organizers hide comments without deleting their records. | `test_invited_ballot_stays_private_until_publication` |
| Hidden results during voting | Public vote totals and judge rankings return 404 until organizer publication. Publication waits until the voting window closes. The ballot omits totals and its secret seed. | `test_invited_ballot_stays_private_until_publication`; `tests/test_lifecycle.py::test_judging_publication_and_isolation` |
| Randomized project order | Ballot projects are sorted by HMAC of a private event seed, voter ID, and project ID. Order is stable on refresh but differs across voters; it does not depend on database insertion order. | `test_ballot_order_is_stable_and_varies_by_voter`; invited-ballot repeat fetch |
| Rate limiting | Account ballots use account and keyed IP limits. Open ballots use signed browser identity, keyed IP and user-agent digests, ten-minute attempt limits, a daily accepted-vote network ceiling, and review flags after repeated network use. Comments are limited per account per hour. | `test_participant_ballot_blocks_self_vote_sybil_and_retries`; `test_open_link_ballot_uses_browser_identity_and_abuse_signals`; comment limit test |
| Duplicate detection | Database constraints prevent a second ballot for the same event/account or event/open-browser identity. The API returns 409 for repeated votes or comments. Duplicate repository submissions require an audited organizer decision before publication. | All three voting lifecycle tests; fixture import, adjudication, and ranking tests |
| Audit trail | Vote casts, invitations, voting configuration, comment creation, and moderation append event audit entries. Organizer-only `/api/events/{id}/audit` exposes raw history; the organizer desk presents names, actions, targets, times, and filters. | `test_invited_ballot_stays_private_until_publication` checks moderation entry; `tests/test_lifecycle.py` checks organizer boundary and readable view |

## Limits that matter

Invite-only mode binds an invitation to the account's email string, but this
release does not verify inbox ownership. Participant mode excludes accounts
created after voting opens; it cannot prove that older accounts represent
distinct humans. Open-link mode intentionally requires no account. It binds
one vote to an HttpOnly browser identity, caps repeated network activity, and
flags shared-network patterns without storing raw IP addresses. Clearing
cookies, rotating networks, or spoofing user agents can evade these signals;
shared networks can also trigger them legitimately, and anonymous voters
cannot be reliably blocked from voting for their own project. Use curated
invites for high-stakes public awards. The full
[threat model](../THREAT-MODEL.md) records these residual risks.

Reproduce this evidence with `python3 scripts/test_fresh.py`; it starts an
isolated Compose project and removes its volume afterward. Direct unittest
runs intentionally require an explicit `DOGFOOD_TEST_URL` so they cannot
mutate the normal demo portal. The unmodified organizer checker remains in
[acceptance-report.txt](../acceptance-report.txt).
