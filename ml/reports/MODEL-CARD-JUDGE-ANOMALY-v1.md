# Model Card — BeyondBug Judge Anomaly Detection v1

**Status:** contributed research artifact; not integrated into the portal.
The evaluation below applies to synthetic 1–10 scores and is not a result on
BeyondBug's 0–5 scorecards. See [INTEGRATION-REVIEW.md](INTEGRATION-REVIEW.md)
for the deployment gate and known feature mismatch.

## Purpose
Assistive anomaly detection for hackathon judging review.
Surfaces unusual review patterns for organizer inspection.

## Algorithm
Isolation Forest (scikit-learn)

## Training Data
Synthetic BeyondBug judging simulation:
- 100 events, 30 projects/event, 3 reviews/project
- 9,000 reviews total, ~7% injected anomalies
- Anomaly types: single-review outlier, peer deviation, high rubric variance

## Features
overall_score, judge_mean_before, judge_std_before,
project_peer_median, project_peer_std, peer_delta,
peer_abs_delta, project_z_score, category_spread,
rubric_completion_ratio, review_duration_sec,
comment_word_count, edit_count

## Evaluation (test set, events 91–100)
- Anomaly recall:    0.679
- Anomaly precision: 0.621
- Anomaly F1:        0.649
- Overall accuracy:  0.960

## Risk Thresholds
Set from validation set percentiles (p7/p20).
See feature_config_v1.json.

## What this model does NOT do
- Does not modify judge scores
- Does not disqualify judges
- Does not select winners
- Does not rank teams

## Intended users
Organizers only. Judges and participants have no access.

## Training date
2026-09-28
