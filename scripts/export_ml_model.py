"""Export the teammate's trained Isolation Forest for dependency-free inference.

Run with scikit-learn==1.6.1, numpy and joblib in a development environment.
The portal loads only the resulting gzip JSON and never unpickles model files.
"""

import gzip
import json
from pathlib import Path

import joblib


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "ml" / "artifacts"
model = joblib.load(ARTIFACTS / "judge_anomaly_iforest_v2.joblib")
scaler = joblib.load(ARTIFACTS / "robust_scaler_v2.joblib")
config = json.loads((ARTIFACTS / "feature_config_v2.json").read_text())
payload = {
    "config": config,
    "center": scaler.center_.tolist(),
    "scale": scaler.scale_.tolist(),
    "offset": float(model.offset_),
    "max_samples": int(model.max_samples_),
    "trees": [],
}
for estimator, features in zip(model.estimators_, model.estimators_features_):
    tree = estimator.tree_
    payload["trees"].append({
        "features": features.tolist(),
        "left": tree.children_left.tolist(),
        "right": tree.children_right.tolist(),
        "split": tree.feature.tolist(),
        "threshold": tree.threshold.tolist(),
        "samples": tree.n_node_samples.tolist(),
    })
target = ARTIFACTS / "judge_anomaly_runtime_v2.json.gz"
with gzip.open(target, "wt", encoding="utf-8", compresslevel=9) as stream:
    json.dump(payload, stream, separators=(",", ":"))
print(f"Exported {len(payload['trees'])} trees to {target} ({target.stat().st_size} bytes)")
