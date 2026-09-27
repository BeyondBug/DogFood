# BeyondBug contribution workflow

The team requested a shared `Features` → `Develop` → `main` promotion flow.
These exact branch names are used throughout this repository.

1. Make feature code and bug fixes on `Features`. Write or update tests for
   behavior that could regress, especially permissions, deadlines, and scoring.
2. When a coherent part is ready, merge `Features` into `Develop`. Run the
   focused tests and any affected end-to-end flow on `Develop`.
3. If integration passes and the feature is reviewable, merge `Develop` into
   `main`. Keep the tier claim and documentation aligned with what actually
   works. Generate the acceptance report from the official checker.

When a test fails on `Develop`, make the fix on `Features`, merge it back, and
rerun the affected tests. Do not patch `Develop` directly. Do not push code
directly to `main` after the kickoff.

Coordinate shared schema and API contracts before parallel edits. Review
permission changes against the role matrix and direct HTTP tests, with a
teammate review when one becomes available. Never promote a branch because
the UI looks right alone; verify the direct HTTP behavior. The release README
will record known gaps instead of hiding failures.

Before the official kickoff, only planning and documentation may be added.
Feature code begins 2026-09-26 18:00 UTC and freezes 2026-09-29 18:00 UTC,
per the organizer's September 26 postponement.

## Current branches

The public `BeyondBug/DogFood` repository has `main`, `Develop`, and
`Features`. The first project-code commit was made after the revised kickoff.
`main` and `Develop` contain only promoted, tested commits. Work resumes from
`Features`; contributors should coordinate before adding changes because this
branch is shared.

For each completed part, merge `Features` into `Develop`, run its integration
checks there, then merge `Develop` into `main` if the checks pass. Keep a
record of the exact tests and acceptance checker run for each promotion.
