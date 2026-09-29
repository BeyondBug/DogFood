# DOGFOOD bonus evidence

This index separates implemented bonus work from work BeyondBug does not
claim. Bonus points break ties under the supplied rules; they do not change
the weighted 0–5 score.

## Normalization Proof — implemented

- Method: regularized two-way additive project-quality and judge-severity
  model, documented with equations and limits in [JUDGING.md](../JUDGING.md).
- Fixture effect: Iron Switch moves from raw rank 2 to adjusted rank 1; Salt
  Ledger moves from 1 to 2. Thirty-three of 40 eligible fixture projects move.
- Edge cases: automated tests cover sparse judges, a constant-scoring judge,
  disconnected overlap groups, shrinkage, and finite outputs.
- Product evidence: the organizer's Judging insight view shows raw and
  adjusted ranks, judge adjustments, overlap groups, and the reviews behind a
  movement. JSON is available at `GET /api/events/{event_id}/judging-insight`.
- Reproduce: run `python3 scripts/test_fresh.py`, or start the seeded portal
  and open the organizer desk for `evt_01`.

## Threat Model — implemented

- Document: [THREAT-MODEL.md](../THREAT-MODEL.md).
- Covered attacks include Sybil voting, ballot stuffing, submission scraping,
  judge collusion, deadline gaming, peer-score access, stolen invites, CSV
  injection, password guessing, comment abuse, host tampering, and misleading
  certificates.
- The document states residual risks rather than treating mitigations as
  guarantees. Integration tests exercise the key authorization, deadline,
  rate-limit, conflict, voting, and duplicate boundaries.

## API First — implemented

- Every browser mutation carrying `data-action` is dispatched through a JSON
  API in `src/static/app.js`; the server applies the same authorization and
  lifecycle rules to direct clients.
- Public JSON endpoints cover event data, paginated gallery search, and
  submitted project detail. Private APIs cover participant, judge, organizer,
  voting, certificate, audit, export, backup, and administrator workflows.
- FastAPI serves live documentation at `/docs` and `/openapi.json`.
- The committed [openapi.json](../openapi.json) is checked byte-for-structure
  against the running application's generated schema by
  `tests/test_openapi.py`.
- The contract and role boundaries are summarized in
  [API-CONTRACT.md](API-CONTRACT.md) and [ARCHITECTURE.md](../ARCHITECTURE.md).

## Pairwise Mode — implemented

- Organizers generate balanced pair assignments after submissions close.
- Track eligibility, team membership, declared conflicts, assignment ownership,
  and publication locks are enforced in the backend.
- Judges choose one project from each assigned pair in their judge desk.
- A Bradley–Terry minorization-maximization estimator recovers a separate
  strength ranking with 0.5 pseudo-wins for finite sparse estimates.
- Pairwise output never silently replaces the weighted rubric ranking.
- The integration suite proves recovery of the known order `Project 0 >
  Project 1 > Project 2` from all three pair outcomes.
