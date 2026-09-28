# BeyondBug: the score that moved, the boundary that held

Three days is enough time to build a convincing interface. It is much less
time than it sounds like when the interface must also enforce deadlines,
separate five roles, survive direct HTTP requests, calibrate judges, preserve
an audit trail, and start offline from one command.

BeyondBug is our answer to DOGFOOD 2026: a self-hosted hackathon platform that
takes an event from registration through published results. This is the story
of the decisions that mattered, the model we refused to trust blindly, and the
features we deliberately left out.

## We designed the denial paths first

The most dangerous authorization bug was also the easiest one to imagine: a
judge changing a query parameter to request somebody else's scorecard. We
treated the browser as untrusted and put event role and ownership checks in
the API transaction. Judge B requesting Judge A's scores receives HTTP 403.
A participant receives the same denial. Organizer exports live behind a
different event-scoped role check.

That decision shaped the rest of the schema. A user is global; participant,
judge, and organizer roles belong to an event. Judge assignments point to a
judge profile and project. Scorecards point to assignments. The server can
therefore answer “does this session own this scorecard?” without trusting an
ID supplied by the page.

Our role model still changed late. A participant briefly saw event-creation
controls because the dashboard treated every authenticated account too
similarly. We fixed the UI and the API together: event creation became
administrator-only, organizer tools stayed event-scoped, judge tools stayed
assignment-scoped, and regression tests checked both missing controls and
403 responses. Hiding a button was never accepted as the fix.

## Normalization changed the winner

An ordinary average assumes every judge uses the five-point scale in the same
way. Real panels contain strict and generous reviewers. BeyondBug fits the
additive model

```text
raw(judge, project) = project quality + judge severity + error
```

and regularizes judge severity toward zero. Sparse judges therefore receive
smaller corrections than well-connected judges. Adjusted project scores are
computed from the original rubric scores with the estimated judge offset
removed and values kept inside the original 0–5 range.

On the published fixture, the calculation changes the leading order: Iron
Switch moves from raw rank 2 to adjusted rank 1, while Salt Ledger moves from
raw rank 1 to adjusted rank 2. The point is not that calibration discovers an
objective winner. The point is that the transformation is explicit,
reproducible, and inspectable. The organizer sees raw score, adjusted score,
rank movement, judge offsets, review coverage, and disconnected overlap
groups before publishing anything.

The awkward fixture cases mattered. A judge who gives every project the same
score cannot cause division by zero because the estimator does not standardize
by that judge's variance. Missing reviews remain missing instead of becoming
zeroes. Projects with two reviews and projects with five reviews both remain
valid, while the coverage dashboard makes that imbalance visible.

## The ML model became a queue, not a verdict

A teammate contributed an Isolation Forest for unusual judge reviews. The
first artifact used a 1–10 scale, depended on fields the portal did not record,
and included the candidate review in peer statistics. We kept it out of the
running product and wrote down why.

The retrained v2 artifact uses the portal's 0–5 scores, excludes the candidate
from peer statistics, splits evaluation by complete events, and removes the
unavailable duration and edit-count features. We export its 300 trees to
compressed JSON and reproduce the scikit-learn decision function with the
Python standard library. The offline image loads no pickle and needs no ML
runtime dependency.

Its held-out synthetic precision is 0.52 and recall is 0.56. Strict and
generous simulated judges produce more false alarms. Those numbers stopped us
from calling it fraud detection. It appears only as an organizer inspection
queue, requires at least two peer reviews, links back to the untouched
scorecard, and cannot alter assignments, scores, rankings, certificates, or
eligibility. A deterministic peer-median rule remains beside it so the human
can compare two very different kinds of signal.

## Offline changed ordinary product decisions

There is no hosted database, authentication provider, email service, CDN, or
external API. FastAPI, SQLite, fonts, model export, fixtures, and Python wheels
ship in the repository. `docker compose up` initializes migrations, imports
the official fixture once, and prints the four acceptance headers.

Avoiding email forced honest invitation UX: the platform creates expiring,
single-use links and tells the organizer to share them privately. Avoiding a
hosted queue kept the deployment to one worker and made SQLite's transaction
boundaries important. We use WAL, foreign keys, a busy timeout, and immediate
write transactions for team limits, deadlines, ballots, and assignments.

The limitation is explicit. This architecture suits a laptop and small or
medium events. Multi-host deployment needs a different database and a shared
rate-limit and job layer. We measured the current design instead of drawing a
load balancer in the architecture diagram and calling it scalable.

## What we cut

We did not build pairwise Bradley–Terry judging. It would have been an
interesting bonus and a dangerous late addition to the most sensitive part of
the product. We also left webhooks, a gallery widget, cryptographically signed
judge records, account recovery, and a browser restore workflow out of the
release.

Community voting is deliberately modest. Ballots are stable-shuffled per
voter, totals stay private until publication, self-votes and duplicate ballots
are rejected, attempts are rate-limited, and organizers can inspect an audit
trail. Email matching does not prove inbox ownership and one account does not
prove one human. Curated invitations remain the recommended mode for a
high-stakes community prize.

## The evidence we would want as adopters

The official checker passes seven of seven requests and verifies T1 and T2.
Our disposable Compose suite creates a fresh project and volume, exercises the
full lifecycle and security boundaries, and removes its data afterward. The
repository includes the unedited acceptance report, threat model, schema and
migration notes, normalization proof, OpenAPI document, capacity measurements,
and a five-minute lifecycle recording.

The most important artifact is still a failed request:

```text
Judge B → GET Judge A scores → 403 Forbidden
```

That line is less visually impressive than a dashboard. It is also the reason
an organizer can trust the dashboard.

## What we would redo

We would introduce explicit result snapshots earlier. BeyondBug locks scores
after publication, which is safe, but a production system eventually needs a
correction and republication workflow with a visible version history. We would
also model richer submission media and organizer-defined questions before the
first migration rather than adding them after the core project record had
settled.

The lasting lesson was that fairness features need an explanation surface.
Normalization hidden in a backend function is difficult to defend. Anomaly
signals without evidence counts look accusatory. An audit table without names
and actions is technically present and operationally useless. The final
product became stronger whenever we made the system show its reasoning and
its limits.

BeyondBug is available at https://github.com/BeyondBug/DogFood under the MIT
license. Built by team BeyondBug for #DogfoodHackathon.
