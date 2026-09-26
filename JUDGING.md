# Judging

This document describes the shipped assignment, scoring, and normalization
code in `src/judging.py` and `src/scoring.py`. The organizer's fixture is used
for the numeric proof below.

## Assignment strategy

An organizer invites judges with a single-use email-bound link, selects their
eligible tracks, and runs batch assignment with a configurable target (default
three reviews per project). For each submitted, nonduplicate project, the
algorithm considers only accepted judges who:

- opted into the project's track;
- are not members of its team;
- have no declared conflict with the project; and
- are not already assigned to it.

It picks the lowest current assignment count, breaking ties by stable judge
ID. Existing fixture assignments are kept. An uncovered project appears in
the returned `shortages` list and organizer progress table; the algorithm
does not silently use an ineligible judge. Each generated assignment records
its reason and the batch action is audited. The organizer can record a
conflict; an unsubmitted assignment is revoked, while an already submitted
review requires separate resolution and returns 409.

This is a deterministic load-balancing heuristic, not an optimum matching
solver. It does not explicitly maximize overlap between judges. The fixture
already has a connected judge/project overlap graph; in a new event, the
dashboard's overlap-group count warns when review pools cannot be compared
reliably. More sophisticated assignment should consider capacity, declared
availability, and overlap during optimization.

## Weighted scorecards

The organizer sets criterion names and positive weights before the first
assignment. Each criterion is scored from 0 to 5. A draft may be partial, but
a submitted scorecard must contain every criterion and belong to the assigned
judge. Scorecards preserve the rubric version used. The raw score for judge
`j` reviewing project `p` is:

```text
raw(j,p) = Σ_c [weight(c) × 5 × score(j,p,c) / max_score(c)] / Σ_c weight(c)
```

The shipped API uses `max_score(c)=5`, so this is the weighted average on the
five-point scale. Missing or incomplete scorecards do not enter rankings.
The raw project score is the arithmetic mean of its completed reviews.
Review count remains visible; projects without reviews are unranked. A
suspected duplicate is shown to organizers but excluded from the ranking.

## Cross-judge normalization

Some judges score more strictly than others. We fit a two-way additive model
to all completed reviews of nonduplicate projects:

```text
raw(j,p) = quality(p) + severity(j) + error(j,p)

minimize over quality and severity:
    Σ_(j,p) [raw(j,p) - quality(p) - severity(j)]²
    + 3 × Σ_j severity(j)²
```

The penalty `3` shrinks judges with few reviews toward zero adjustment. It is
a fixed, documented regularization choice; operators should validate it on
their own event data before treating close ranks as decisive. We initialize
project quality at its raw mean, then alternate two updates until the maximum
quality change is under `1e-10` or 500 iterations:

```text
severity(j) = Σ_p [raw(j,p) - quality(p)] / (review_count(j) + 3)
quality(p)  = mean_j [raw(j,p) - severity(j)]
```

At the optimum, severities sum to zero: project effects absorb the global
mean, and summing the optimality equations with positive penalty forces the
sum of judge effects to zero. For each review we compute
`adjusted(j,p) = clamp(raw(j,p) - severity(j), 0, 5)` and average the adjusted
reviews for the project's final score. A scorecard's 0–5 bounds remain intact.
Equal adjusted scores break by greater review count, then project ID.

The method needs **overlap**: when judges never review common projects, their
relative severity is not established by data. The API reports connected
components of the judge/project review graph so an organizer can spot this.
It does not divide by each judge's standard deviation. That matters for the
fixture's constant-scoring judge `jdg_07`, whose variance is zero.

## Fixture proof

The official fixture contains 126 historical scorecards. Four belong to the
duplicate `prj_41`, leaving 122 completed reviews over 40 ranked projects.
The 30 judges form one connected overlap component. The calculation in the
running portal produces:

| Project | Raw rank | Adjusted rank | Adjusted score |
| --- | ---: | ---: | ---: |
| Iron Switch | 2 | 1 | 4.316 |
| Salt Ledger | 1 | 2 | 4.295 |
| Dry Relay | 4 | 3 | 4.176 |
| Salt Loom | 5 | 4 | 4.069 |
| Salt Kiln | 6 | 5 | 4.043 |

Thirty-three of the 40 projects change rank, often by only a small score
difference. `Open Beacon` moves from raw rank 26 to adjusted rank 19;
`Paper Anchor` moves from 21 to 28. These shifts demonstrate effect, **not**
proof that a changed order is objectively correct. Judge `jdg_01` and
`jdg_23` each supplied one review. With penalty 3 their fitted offsets are
about `-0.340` and `-0.118`; with almost no penalty (`0.01`) they would be
about `-1.804` and `-0.992`. The fixed penalty prevents sparse reviewers
from receiving extreme adjustments. Constant-scoring `jdg_07` remains finite
with an offset of about `+0.209`.

Reproduce the table by starting the portal and opening the organizer desk for
`evt_01`, or calling `/api/events/evt_01/rankings` as the demo organizer.
The `rankings.csv` export includes raw and adjusted values. The pure scoring
tests cover constant, sparse, and disconnected cases.

## Integrity and limits

Judges can query only their own scorecards and assigned project queue. A
different judge ID in `/api/judge/scores?judge=...` returns 403. Participants
also receive 403. The organizer can see the audit trail, judge progress,
assignment shortages, and raw/adjusted rankings. Public results return 404
until publication, which locks score editing. CSV exports require organizer
access and escape spreadsheet formulas in text fields.

An additive model only corrects a consistent leniency or strictness effect.
It cannot fix collusion, a poor rubric, biased assignment, unequal project
mix, or a disconnected judging pool. Low review counts leave uncertainty
that a single rank number cannot show; organizers should inspect counts and
comments before awards. This release does not implement pairwise scoring or
post-publication result versioning.
