\# Model Card — BeyondBug Judge Anomaly Detection v2



\## Purpose

Assistive anomaly detection for hackathon judging.

Surfaces unusual review patterns for organizer inspection only.

Never modifies scores or rankings.



\## Algorithm

Isolation Forest (scikit-learn), contamination=0.05, 300 estimators



\## Score Scale

0–5 weighted rubric scores (matches BeyondBug portal)



\## Training Data

Synthetic BeyondBug judging simulation:

\- 120 events, 30 projects/event, 4 reviews/project

\- 14,400 reviews total, \~4.6% injected anomalies

\- Judge types: normal (60%), strict (15%), generous (15%), inconsistent (10%)

\- Stable per-judge bias, unique judge IDs per event



\## Key Fixes vs v1

\- Correct 0–5 score scale (v1 used 1–10)

\- Peer stats exclude the review being evaluated

\- Judge history uses only prior reviews (leave-one-out)

\- Anomaly injection avoids boundary clipping

\- Event-based train/val/test split (no row leakage)

\- Interaction features: peer\_x\_judge, unexplained\_peer\_delta



\## Features Used

overall\_score, peer\_delta, peer\_abs\_delta (x2),

project\_z\_score (x2), judge\_z\_score (x2),

peer\_x\_judge (x2), unexplained\_peer\_delta,

has\_judge\_history, judge\_mean\_before, judge\_std\_before,

project\_peer\_std, project\_peer\_mean,

category\_spread, rubric\_completion\_ratio



\## Features Removed Pending Instrumentation

review\_duration\_sec, edit\_count

(not yet recorded by the portal — add when available)



\## Evaluation (test events 108–119)

\- Anomaly F1:            0.54

\- Anomaly recall:        0.56

\- Anomaly precision:     0.52

\- Overall accuracy:      0.95

\- Decision score gap:    0.137



\## False Alarm Rate by Judge Type

\- Normal:        0.8%

\- Inconsistent:  2.9%

\- Strict:        5.2%

\- Generous:      7.5%



\## Known Limitation

Generous and strict judges show elevated false alarm rates

compared with normal judges. This is caused by high peer

deviation that is not fully offset by consistent judge history.

Documented for investigation in v3.



\## What This Model Does NOT Do

\- Does not modify judge scores

\- Does not disqualify judges

\- Does not select winners or rank teams

\- Does not expose peer scores to judges



\## Intended Users

Organizers only. Judges and participants have no access.



\## Risk Thresholds

HIGH:   decision\_score <= 0.0322

MEDIUM: decision\_score <= 0.0788

See feature\_config\_v2.json



\## Training Date

2026-09-28

