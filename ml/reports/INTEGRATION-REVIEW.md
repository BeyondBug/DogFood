# Judge anomaly model integration review

The `ml/` contribution from PR #1 is preserved on `Develop` and `Features` as
research. Its model is **not** loaded by the portal, used for rankings, or
shown to organizers. The shipped review-attention rule remains the operational
baseline described in [JUDGING.md](../../JUDGING.md).

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
