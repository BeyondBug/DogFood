# Judging

This document describes the shipped assignment, scoring, and normalization
code in `src/judging.py` and `src/scoring.py`. The organizer's fixture is used
for the numeric proof below.

## Model-assisted review

The organizer desk includes a separate, advisory v2 Isolation Forest review
list trained by a teammate on simulated 0–5 judging data. It reads only
submitted scorecards, derives peer statistics without the target review, and
uses only earlier reviews for judge-history features. A scorecard needs two
other reviews to be evaluated. The local runtime uses a compressed JSON tree
export, so the Docker portal needs no machine-learning packages and never
loads the training pickle. A regression test compares a portable decision
score with the original scikit-learn artifact.

The teammate's held-out synthetic evaluation reports precision 0.52 and
recall 0.56. These are **not** estimates for real events; strict and generous
judges showed more false alarms. The fixture produced 15 advisory signals,
which require a human to inspect the original scorecard and context. This
model does not alter scores, rankings, assignments, eligibility, or awards.
The deterministic review-attention rule remains visible alongside it.
Model signals and peer comparisons are organizer-only in both the UI and API.
Judges see their own assignments, rubric, and review progress; showing peer
patterns while they score could bias independent reviews.

## Assignment strategy

An organizer invites existing accounts with a single-use email-bound link. A
site administrator can also create a new judge account directly, selecting
tracks and receiving a randomly generated temporary password shown once. The
judge signs in with that password and can change it; the change revokes all
existing sessions. Both paths create an accepted judge profile before batch
assignment. An organizer selects eligible tracks and runs batch assignment with a configurable target (default
three reviews per project). Assignment and scoring open only after the
submission deadline. This freezes both project content and team membership
before conflict checks and reviews begin. Published results lock further
assignment and score changes. For each submitted, nonduplicate project, the
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
suspected duplicate is shown to organizers and excluded from the ranking until
an organizer records a confirmed or cleared decision with a reason. Results
cannot be published while an automatic duplicate signal remains unresolved.

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
The organizer's **Judging insight** view displays coverage, overlap warnings,
raw-to-adjusted rank movement, per-judge severity adjustments, and the
individual review values behind each moved project. Its JSON source is
`/api/events/evt_01/judging-insight` and is organizer-only. A positive
displayed adjustment means the model identified a comparatively strict judge;
the stored scorecard itself does not change.

### Review attention

The organizer desk also highlights submitted reviews that differ substantially
from an agreeing peer group. For each review, it computes that review's
calibrated 0–5 score and the median of **other** calibrated reviews for the
same project. A signal appears only when there are at least two peers, the
absolute gap is at least 1.5 points, and the peers' median absolute deviation
is at most 0.5 points. Projects with fewer than three completed reviews cannot
trigger this signal. The desk shows the original score, peer median and peer
count, then links to the unmodified criterion scores and comment. The detail
page and API require organizer authorization; judges cannot use them to read
peer scorecards.

These thresholds are a deterministic triage rule, not evidence of misconduct.
The peer median excludes the candidate review, but the displayed calibration
offsets come from the full ranking model. A connected group and a consistent
strict judge can still create unusual gaps. Organizers should inspect the
rubric, project and written review before acting. Neither the rule nor the
view changes scoring, assignment, publication, or awards.

The earlier v1 Isolation Forest remains in `ml/` as research history and is
not loaded. The retrained v2 model uses the portal's 0–5 scale, excludes the
candidate review from peer statistics, uses only features the portal records,
and runs from a reviewed JSON tree export. Review duration and edit count were
removed because the portal does not record them. The v2 signal is an organizer
triage aid with documented synthetic precision and recall; it is not evidence
of misconduct and makes no scoring decision.

The `rankings.csv` export includes raw and adjusted values. The pure scoring
tests cover constant, sparse, and disconnected cases.

## Pairwise Mode

Pairwise Mode is an optional, separate judging path. After submissions close,
an organizer chooses a target number of comparisons per project. The backend
forms unique pairs and assigns them only to accepted judges eligible for both
tracks, excluding the judge's own team and declared conflicts. A judge can
submit only their assigned pair, and publication locks later edits.

For positive project strengths `s_i`, the Bradley–Terry model uses:

```text
P(i beats j) = s_i / (s_i + s_j)
```

Minorization-maximization updates use a 0.5 pseudo-win prior so sparse and
undefeated projects remain finite. Strengths are rescaled to mean one after
each iteration; fitting stops when the maximum change is below `1e-10` or at
500 iterations. Pairwise wins, coverage, fitted strength, and rank remain
separate from rubric scores. The integration test recovers a known three
project order from every possible pair. Pairwise mode still cannot correct
collusion, inadequate pair coverage, or undisclosed conflicts.

## Integrity and limits

Judges can query only their own scorecards and assigned project queue. A
different judge ID in `/api/judge/scores?judge=...` returns 403. Participants
also receive 403. The organizer can see the audit trail, judge progress,
assignment shortages, and raw/adjusted rankings. Public results return 404
until publication, which requires submissions to be closed and locks project
and score editing. When community voting is
configured, publication also waits until its window closes. CSV exports require organizer
access and escape spreadsheet formulas in text fields.

Judges can recuse themselves before submitting by reporting a conflict from
their queue. The server verifies ownership, removes the assignment and any
draft scorecard, records the reason, and excludes the pair from later batches.
The organizer sees the resulting shortage and audit entry.

An additive model only corrects a consistent leniency or strictness effect.
It cannot fix collusion, a poor rubric, biased assignment, unequal project
mix, or a disconnected judging pool. Low review counts leave uncertainty
that a single rank number cannot show; organizers should inspect counts and
comments before awards. This release does not implement post-publication result versioning.
