# Judge anomaly model integration review

## Current status: v2 organizer aid

The September 28 v2 contribution is integrated into the organizer's Judging
insight panel as **advisory review signals**. The earlier v1 analysis below is
retained as the record of why that version was gated. The v2 training notebook
uses 0–5 scores, peer statistics that exclude the target review, prior judge
reviews, and an event-based evaluation split. Duration and edit-count inputs
remain out of scope because the portal does not record them.

The portal derives each feature from submitted scorecards and the active rubric.
Reviews with fewer than two peers are skipped. Its runtime uses a reviewed,
compressed JSON export of the 300 trees and a standard-library reader; Docker
still installs no NumPy, joblib, or scikit-learn and loads no pickle. The
portable decision function is regression-tested against the trained artifact.

The model appears only on organizer pages. It never changes scorecards, judge
assignments, normalization, rankings, or certificates. Its synthetic test
precision (0.52) and recall (0.56) are **not** real-event accuracy claims.
Consistently strict and generous judges had higher false-alarm rates in the
teammate's synthetic test. The deterministic peer-median attention rule remains
visible alongside it and is documented in `JUDGING.md`.
The organizer-only API is `/api/events/{event_id}/ml-review-signals`; direct
judge and participant requests are denied with HTTP 403 in the integration
suite. Original scorecards remain available through organizer-only links.

One model detail is intentional: `feature_config_v2.json` repeats three feature
names to weight them more heavily. The runtime reads the ordered feature list
exactly, including repeats, and the exported tree check catches schema drift.

## Historical v1 gate

The `ml/` contribution from PR #1 is preserved on `Develop` and `Features` as
research. Its v1 model is **not** loaded by the portal or used for rankings.
The shipped review-attention rule remains the operational baseline described
in [JUDGING.md](../../JUDGING.md).

## Why inference is gated

| Contract | Contributed artifact | Running portal |
| --- | --- | --- |
| Score scale | Notebook samples and clips scores from 1 to 10 | Weighted rubric scores are 0 to 5 |
| Input features | 13 features, including review duration and edit count | Those two measurements are not stored |
| Peer comparison | Project mean, median and standard deviation include the review being evaluated | Attention comparisons exclude that review |
| Judge history | Initial training features use all reviews for each judge, including later reviews | Live inference would have only earlier submitted reviews |
| Runtime | `app/ml/inference.py` imports NumPy and joblib; the serialized model also requires scikit-learn | The pinned offline image installs none of them and copies only `src/` |

The notebook includes a later exploratory cell for prior-review judge history,
but the exported model and reported evaluation come from the earlier feature
matrix. Judge IDs are reused across its synthetic events, so those aggregates
also cross the train/test event boundary. The synthetic judge bias is drawn
for each review instead of remaining stable for a judge. These details make
the reported precision, recall and F1 **research results for that simulation**,
not evidence of accuracy on BeyondBug scorecards. The model card does not yet
compare false alarms against the deterministic rule or report behavior for
consistently strict judges.

`joblib` uses Python pickle serialization. Load only reviewed, trusted
artifacts with a pinned compatible scikit-learn version. The current portal
does not deserialize the contributed files.

## Acceptance gate for a deployable version

1. Generate 0–5 rubric scores with stable per-judge severity and event-unique
   judge IDs. Derive peer features without the target review and judge history
   only from earlier reviews. Use only fields recorded in the schema, or add
   and test real instrumentation before training on them.
2. Split by complete events. Report precision, recall, flagged-review rate,
   calibration by review count, and false alarms for strict and generous
   judges. Compare against the shipped rule on the same held-out examples and
   inspect the official fixture without treating it as labeled ground truth.
3. Package inference and its exact dependencies locally for both supported
   architectures, or export a reviewed format with a small offline reader.
   `docker compose up` and the network-disabled runtime check must still pass.
4. Add an organizer-only API and UI with original scorecard links, evidence
   counts, and an explanation of missing features. Treat every result as a
   review prompt. Never alter rubric values, normalized rankings, or awards.

Until those checks pass, the model is not a claimed platform capability.
