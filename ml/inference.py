import json
import joblib
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent.parent.parent / "ml" / "artifacts"

_model  = None
_scaler = None
_config = None

def _load():
    global _model, _scaler, _config
    if _model is None:
        _model  = joblib.load(BASE / "judge_anomaly_iforest_v1.joblib")
        _scaler = joblib.load(BASE / "robust_scaler_v1.joblib")
        with open(BASE / "feature_config_v1.json") as f:
            _config = json.load(f)

def predict(feature_dict: dict) -> dict:
    _load()
    features = _config["features"]
    x = np.array([[feature_dict.get(f, 0.0) for f in features]])
    x_scaled = _scaler.transform(x)
    score = float(_model.decision_function(x_scaled)[0])
    thresholds = _config["risk_thresholds"]

    if score <= thresholds["high"]:
        risk = "high"
    elif score <= thresholds["medium"]:
        risk = "medium"
    else:
        risk = "low"

    reasons = []
    if abs(feature_dict.get("peer_abs_delta", 0)) >= 2.5:
        reasons.append("large_peer_score_deviation")
    if abs(feature_dict.get("judge_z_score", 0)) >= 2.0:
        reasons.append("unusual_for_this_judge")
    if feature_dict.get("category_spread", 0) >= 4.0:
        reasons.append("high_rubric_variance")
    if feature_dict.get("rubric_completion_ratio", 1.0) < 1.0:
        reasons.append("incomplete_rubric")

    return {
        "model_version": _config["model_version"],
        "anomaly_score": round(1.0 - (score + 0.15) / 0.30, 3),
        "risk": risk,
        "reasons": reasons,
        "action": "organizer_review_recommended" if risk != "low" else "none"
    }