"""Weighted score aggregation and regularized cross-judge calibration."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from sqlite3 import Connection
from statistics import median


@dataclass(frozen=True)
class Review:
    judge: str
    project: str
    raw: float
    scorecard_id: str = ""


def connected_components(reviews: list[Review]) -> list[dict[str, list[str]]]:
    """Return overlap groups in the judge/project bipartite graph."""
    neighbours: dict[str, set[str]] = defaultdict(set)
    for review in reviews:
        judge = "j:" + review.judge
        project = "p:" + review.project
        neighbours[judge].add(project)
        neighbours[project].add(judge)
    unseen = set(neighbours)
    groups = []
    while unseen:
        start = min(unseen)
        stack = [start]
        group = set()
        while stack:
            node = stack.pop()
            if node in group:
                continue
            group.add(node)
            stack.extend(neighbours[node] - group)
        unseen.difference_update(group)
        groups.append({"judges": sorted(node[2:] for node in group if node.startswith("j:")),
                       "projects": sorted(node[2:] for node in group if node.startswith("p:"))})
    return sorted(groups, key=lambda group: group["projects"][0] if group["projects"] else "")


def normalize(reviews: list[Review], penalty: float = 3.0) -> dict:
    """Fit raw(j,p)=quality(p)+severity(j) with ridge shrinkage on severity.

    Alternating coordinate updates converge for this convex objective. At its
    optimum, judge severities sum to zero because project effects absorb the
    global mean. Project means are the starting point and the zero-variance
    case never divides by a judge's standard deviation.
    """
    by_project: dict[str, list[Review]] = defaultdict(list)
    by_judge: dict[str, list[Review]] = defaultdict(list)
    for review in reviews:
        by_project[review.project].append(review)
        by_judge[review.judge].append(review)
    if not reviews:
        return {"offsets": {}, "adjusted": {}, "components": []}
    quality = {project: sum(r.raw for r in entries) / len(entries)
               for project, entries in by_project.items()}
    offsets = {judge: 0.0 for judge in by_judge}
    for _ in range(500):
        next_offsets = {
            judge: sum(r.raw - quality[r.project] for r in entries) / (len(entries) + penalty)
            for judge, entries in by_judge.items()
        }
        next_quality = {
            project: sum(r.raw - next_offsets[r.judge] for r in entries) / len(entries)
            for project, entries in by_project.items()
        }
        change = max(abs(next_quality[project] - quality[project]) for project in quality)
        quality, offsets = next_quality, next_offsets
        if change < 1e-10:
            break
    adjusted = {
        project: sum(min(5.0, max(0.0, r.raw - offsets[r.judge])) for r in entries) / len(entries)
        for project, entries in by_project.items()
    }
    return {"offsets": offsets, "adjusted": adjusted, "components": connected_components(reviews)}


def load_reviews(db: Connection, event_id: str) -> list[Review]:
    rows = db.execute(
        "SELECT s.id AS scorecard_id,a.judge_id,a.project_id"
        " FROM scorecards s JOIN judge_assignments a ON a.id=s.assignment_id"
        " JOIN projects p ON p.id=a.project_id"
        " WHERE a.event_id=? AND s.status='submitted' AND p.status='submitted' AND p.duplicate_of IS NULL",
        (event_id,),
    ).fetchall()
    result = []
    for row in rows:
        criteria = db.execute(
            "SELECT c.weight,c.max_score,cs.score"
            " FROM rubric_criteria c LEFT JOIN criterion_scores cs"
            " ON cs.criterion_id=c.id AND cs.scorecard_id=?"
            " JOIN scorecards s ON s.rubric_id=c.rubric_id WHERE s.id=?",
            (row["scorecard_id"], row["scorecard_id"]),
        ).fetchall()
        if not criteria or any(item["score"] is None for item in criteria):
            continue
        weight = sum(item["weight"] for item in criteria)
        raw = sum(item["weight"] * 5 * item["score"] / item["max_score"] for item in criteria) / weight
        result.append(Review(row["judge_id"], row["project_id"], raw, row["scorecard_id"]))
    return result


def review_attention(reviews: list[Review], offsets: dict[str, float],
                     project_names: dict[str, str] | None = None,
                     judge_names: dict[str, str] | None = None) -> dict:
    """Surface large deviations from an agreeing peer group for human review.

    The candidate is excluded from its peer median. Offsets are the same
    regularized estimates used by the ranking and never alter scorecards.
    """
    project_names = project_names or {}
    judge_names = judge_names or {}
    by_project: dict[str, list[tuple[Review, float]]] = defaultdict(list)
    for review in reviews:
        calibrated = min(5.0, max(0.0, review.raw - offsets.get(review.judge, 0.0)))
        by_project[review.project].append((review, calibrated))
    items = []
    limited = 0
    for project_id, entries in by_project.items():
        if len(entries) < 3:
            limited += 1
            continue
        for index, (review, calibrated) in enumerate(entries):
            peers = [value for peer_index, (_, value) in enumerate(entries) if peer_index != index]
            peer_median = median(peers)
            peer_mad = median(abs(value - peer_median) for value in peers)
            gap = abs(calibrated - peer_median)
            if gap < 1.5 or peer_mad > 0.5:
                continue
            items.append({
                "scorecard_id": review.scorecard_id,
                "project_id": project_id,
                "project": project_names.get(project_id, project_id),
                "judge": judge_names.get(review.judge, review.judge),
                "original_score": review.raw,
                "calibrated_score": calibrated,
                "peer_median": peer_median,
                "peer_count": len(peers),
                "peer_mad": peer_mad,
                "gap": gap,
            })
    items.sort(key=lambda item: (-item["gap"], item["project_id"], item["judge"]))
    return {"items": items, "limited_evidence_projects": limited,
            "rule": "At least two other reviews, calibrated gap >= 1.5/5, peer median absolute deviation <= 0.5/5"}


def event_ranking(db: Connection, event_id: str) -> dict:
    reviews = load_reviews(db, event_id)
    raw_scores: dict[str, list[float]] = defaultdict(list)
    for review in reviews:
        raw_scores[review.project].append(review.raw)
    model = normalize(reviews)
    projects = db.execute(
        "SELECT p.id,p.title,p.duplicate_of,t.name AS team,tr.name AS track"
        " FROM projects p JOIN teams t ON t.id=p.team_id JOIN tracks tr ON tr.id=p.track_id"
        " WHERE p.event_id=? AND p.status='submitted' ORDER BY p.id",
        (event_id,),
    ).fetchall()
    rows = []
    for project in projects:
        project_id = project["id"]
        scores = raw_scores.get(project_id, [])
        rows.append({**dict(project), "review_count": len(scores),
                     "raw_score": sum(scores) / len(scores) if scores else None,
                     "adjusted_score": model["adjusted"].get(project_id)})
    eligible = sorted((row for row in rows if row["adjusted_score"] is not None),
                      key=lambda row: (-row["adjusted_score"], -row["review_count"], row["id"]))
    for position, row in enumerate(eligible, start=1):
        row["rank"] = position
    for row in rows:
        row.setdefault("rank", None)
    rows.sort(key=lambda row: (row["rank"] is None, row["rank"] or 9999, row["id"]))
    return {"projects": rows, "judge_offsets": model["offsets"],
            "overlap_components": model["components"], "review_count": len(reviews)}


def judging_insight(db: Connection, event_id: str, ranking: dict | None = None) -> dict:
    """Explain calibration with the exact reviews and offsets used in rankings."""
    ranking = ranking or event_ranking(db, event_id)
    reviews = load_reviews(db, event_id)
    offsets = ranking["judge_offsets"]
    names = {row["id"]: row["name"] for row in db.execute(
        "SELECT j.id,u.name FROM judge_profiles j JOIN users u ON u.id=j.user_id"
        " WHERE j.event_id=?", (event_id,),
    )}
    raw_order = sorted(
        (row for row in ranking["projects"] if row["raw_score"] is not None),
        key=lambda row: (-row["raw_score"], -row["review_count"], row["id"]),
    )
    raw_ranks = {row["id"]: rank for rank, row in enumerate(raw_order, 1)}
    project_reviews: dict[str, list[dict]] = defaultdict(list)
    judge_values: dict[str, list[float]] = defaultdict(list)
    for review in reviews:
        offset = offsets[review.judge]
        project_reviews[review.project].append({
            "judge": names.get(review.judge, review.judge),
            "raw": review.raw,
            "adjustment": -offset,
            "calibrated": min(5.0, max(0.0, review.raw - offset)),
        })
        judge_values[review.judge].append(review.raw)
    movements = []
    for row in ranking["projects"]:
        if row["rank"] is None:
            continue
        movements.append({
            "project_id": row["id"], "title": row["title"],
            "raw_rank": raw_ranks[row["id"]], "adjusted_rank": row["rank"],
            "rank_change": raw_ranks[row["id"]] - row["rank"],
            "raw_score": row["raw_score"], "adjusted_score": row["adjusted_score"],
            "reviews": sorted(project_reviews[row["id"]], key=lambda item: item["judge"]),
        })
    movements.sort(key=lambda row: (-abs(row["rank_change"]), row["adjusted_rank"]))
    judges = [{
        "name": names.get(judge_id, judge_id),
        "reviews": len(values), "raw_average": sum(values) / len(values),
        "adjustment": -offsets[judge_id],
    } for judge_id, values in judge_values.items()]
    judges.sort(key=lambda row: (row["adjustment"], row["name"]))
    unique_projects = [row for row in ranking["projects"] if row["duplicate_of"] is None]
    attention = review_attention(reviews, offsets,
                                 {row["id"]: row["title"] for row in ranking["projects"]}, names)
    return {
        "coverage": {"reviewed": sum(row["review_count"] > 0 for row in unique_projects),
                     "total": len(unique_projects),
                     "unreviewed": sum(row["review_count"] == 0 for row in unique_projects)},
        "overlap_components": ranking["overlap_components"],
        "movements": movements,
        "judges": judges,
        "attention": attention,
    }


def scorecard_detail(db: Connection, event_id: str, scorecard_id: str) -> dict | None:
    """Return the original submitted review, scoped to one event."""
    row = db.execute(
        "SELECT s.id,s.status,s.comment,s.submitted_at,s.updated_at,"
        "a.project_id,p.title AS project_title,j.id AS judge_id,u.name AS judge_name,"
        "r.name AS rubric_name"
        " FROM scorecards s JOIN judge_assignments a ON a.id=s.assignment_id"
        " JOIN projects p ON p.id=a.project_id"
        " JOIN judge_profiles j ON j.id=a.judge_id"
        " JOIN users u ON u.id=j.user_id JOIN rubrics r ON r.id=s.rubric_id"
        " WHERE s.id=? AND a.event_id=? AND s.status='submitted'",
        (scorecard_id, event_id),
    ).fetchone()
    if row is None:
        return None
    criteria = db.execute(
        "SELECT c.name,c.weight,c.max_score,cs.score FROM rubric_criteria c"
        " JOIN criterion_scores cs ON cs.criterion_id=c.id"
        " WHERE cs.scorecard_id=? ORDER BY c.sort_order,c.id", (scorecard_id,),
    ).fetchall()
    return {**dict(row), "criteria": [dict(item) for item in criteria]}
