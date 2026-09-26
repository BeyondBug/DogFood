# Judging method — design draft

This is a pre-kickoff proposal. We will publish the exact implemented math,
tests, and fixture results before claiming T2 or the normalization bonus.

## Assignment

For each submitted, eligible project, target three independent judges. A
candidate must be assigned to the project's track and must not be a team
member or have a declared conflict. Among eligible candidates, prefer lower
current workload and overlap that connects judges through shared projects.
Use deterministic tie breaking and record the assignment batch, reason, and
actor. If a track lacks capacity, show the shortage instead of secretly
assigning an ineligible judge. Organizers can override with an audited reason.

Shared project coverage matters: without overlap, judge severity cannot be
estimated across otherwise separate review groups. The progress dashboard
should show assigned, started, and submitted counts for each judge and track.
The published fixture's judge-overlap graph is connected across all 30 judges;
that fact helps the proof but does not guarantee future events will be.

## Raw scoring

The organizer configures named criteria, each with a positive weight and a
bounded score range. For a completed scorecard, the raw score is

`raw(j,p) = sum_c(weight(c) * score(j,p,c)) / sum_c(weight(c))`.

The scorecard stores the rubric version. Incomplete scorecards do not enter
rankings. An event-level result should show review coverage and flag projects
below the configured minimum review count.

## Proposed cross-judge calibration

Use a regularized, two-way additive model on completed scorecards:

`raw(j,p) = quality(p) + severity(j) + error(j,p)`.

Fit project quality and judge severity by minimizing squared residuals plus
`lambda * sum_j severity(j)^2`, with severities centered at zero. The penalty
shrinks poorly observed judges toward no adjustment. Only overlapping reviews
can distinguish project quality from judge severity; disconnected groups must
be labeled as weakly comparable. Adjust each review by subtracting its fitted
judge severity, clamp to the rubric range, and average adjusted reviews for
the project. Keep raw and adjusted results visible to organizers, along with
review counts, fitted offsets, and ranking changes.

We will not scale by each judge's standard deviation. The fixture includes a
judge who gave every reviewed project the same criterion vector, so their
variance is zero; division would be undefined and could greatly amplify noise.
The fixture also includes judges with only one review, whose offset should be
strongly shrunk. The method corrects additive leniency/severity, not collusion,
poor rubric design, or every difference in project mix. Those limitations
belong in the final explanation.

## Integrity and publication

Only an assigned judge can edit their own scorecard. A judge cannot read peer
scorecards or projects outside their permitted tracks. Organizers can inspect
all scorecards and audit entries. Results stay private until a recorded
publication action. Corrections after publication require an explicit reason
and a new published result version.

The final document will include fixture calculations, raw and adjusted rank
tables, tests for sparse/constant judges, and a worked example. It must match
the actual implementation rather than this proposal.
