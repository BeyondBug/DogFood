"""Organizer-only, advisory review signals from the trained v2 forest.

The runtime reads a JSON export, never an executable pickle. Scores and ranks
are computed elsewhere and are never modified by this module.
"""

from __future__ import annotations

import gzip
import json
import math
import struct
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from sqlite3 import Connection


ARTIFACT = Path(__file__).resolve().parents[1] / "ml/artifacts/judge_anomaly_runtime_v2.json.gz"


@lru_cache(maxsize=1)
def _artifact() -> dict:
    with gzip.open(ARTIFACT, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _average_path_length(n: int) -> float:
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0
    return 2.0 * (math.log(n - 1) + 0.5772156649015329) - 2.0 * (n - 1) / n


def decision_score(features: dict[str, float]) -> float:
    """Match IsolationForest.decision_function without runtime ML packages."""
    data = _artifact()
    names = data["config"]["features"]
    values = [struct.unpack("f", struct.pack("f", (features.get(name, 0.0) - center) / scale))[0]
              for name, center, scale in zip(names, data["center"], data["scale"])]
    total_depth = 0.0
    for tree in data["trees"]:
        node = 0
        depth = 0
        while tree["left"][node] != -1:
            feature = tree["features"][tree["split"][node]]
            node = tree["left"][node] if values[feature] <= tree["threshold"][node] else tree["right"][node]
            depth += 1
        total_depth += depth + _average_path_length(tree["samples"][node])
    denominator = len(data["trees"]) * _average_path_length(data["max_samples"])
    return -2 ** (-total_depth / denominator) - data["offset"]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def organizer_ml_insight(db: Connection, event_id: str) -> dict:
    from .scoring import load_reviews

    reviews = load_reviews(db, event_id)
    by_project = defaultdict(list)
    by_judge = defaultdict(list)
    for review in reviews:
        by_project[review.project].append(review)
        by_judge[review.judge].append(review)
    names = {row["id"]: row["name"] for row in db.execute(
        "SELECT j.id,u.name FROM judge_profiles j JOIN users u ON u.id=j.user_id WHERE j.event_id=?",
        (event_id,),
    )}
    projects = {row["id"]: row["title"] for row in db.execute(
        "SELECT id,title FROM projects WHERE event_id=?", (event_id,),
    )}
    rubric_rows = db.execute(
        "SELECT cs.scorecard_id,5.0*cs.score/c.max_score AS normalized"
        " FROM criterion_scores cs JOIN rubric_criteria c ON c.id=cs.criterion_id"
        " JOIN scorecards s ON s.id=cs.scorecard_id"
        " JOIN judge_assignments a ON a.id=s.assignment_id WHERE a.event_id=?",
        (event_id,),
    ).fetchall()
    categories = defaultdict(list)
    for row in rubric_rows:
        categories[row["scorecard_id"]].append(row["normalized"])
    signals = []
    limited = 0
    thresholds = _artifact()["config"]["risk_thresholds"]
    for review in sorted(reviews, key=lambda r: (r.judge, r.project, r.scorecard_id)):
        peers = [other.raw for other in by_project[review.project] if other.scorecard_id != review.scorecard_id]
        if len(peers) < 2:
            limited += 1
            continue
        prior = [other.raw for other in by_judge[review.judge]
                 if (other.project, other.scorecard_id) < (review.project, review.scorecard_id)]
        if len(prior) >= 2:
            judge_mean, judge_std = _mean(prior), max(_std(prior), 0.1)
            judge_z = max(-5.0, min(5.0, (review.raw - judge_mean) / judge_std))
            has_history = 1.0
        else:
            judge_mean, judge_std, judge_z, has_history = 2.5, 0.5, 0.0, 0.0
        peer_mean, peer_std = _mean(peers), _std(peers)
        peer_delta = review.raw - peer_mean
        peer_abs_delta = abs(peer_delta)
        category = categories[review.scorecard_id]
        features = {
            "overall_score": review.raw,
            "peer_delta": peer_delta,
            "peer_abs_delta": peer_abs_delta,
            "project_z_score": max(-5.0, min(5.0, peer_delta / (peer_std + 0.2))),
            "judge_z_score": judge_z,
            "peer_x_judge": peer_abs_delta * abs(judge_z),
            "unexplained_peer_delta": peer_abs_delta * (1 - has_history) + peer_abs_delta * has_history / (abs(judge_z) + 1),
            "has_judge_history": has_history,
            "judge_mean_before": judge_mean,
            "judge_std_before": judge_std,
            "project_peer_std": peer_std,
            "project_peer_mean": peer_mean,
            "category_spread": max(category) - min(category) if category else 0.0,
            "rubric_completion_ratio": 1.0,
        }
        value = decision_score(features)
        risk = "high" if value <= thresholds["high"] else "medium" if value <= thresholds["medium"] else "low"
        if risk != "low":
            signals.append({
                "scorecard_id": review.scorecard_id,
                "project": projects.get(review.project, review.project),
                "judge": names.get(review.judge, review.judge),
                "score": review.raw,
                "peer_mean": peer_mean,
                "risk": risk,
                "decision_score": round(value, 4),
                "peer_count": len(peers),
            })
    signals.sort(key=lambda item: (item["decision_score"], item["project"], item["judge"]))
    return {"version": _artifact()["config"]["model_version"], "signals": signals,
            "evaluated": len(reviews) - limited, "limited": limited}
