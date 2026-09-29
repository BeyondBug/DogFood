#!/usr/bin/env python3
"""Simulation study for the cross-judge calibration penalty.

Uses the official fixture's real judge/project review graph (122 reviews of 40
nonduplicate projects by 30 judges), plants known project quality and judge
severity, adds review noise, and measures how well raw means and the calibrated
model recover the planted truth.

    python3 scripts/normalization_study.py            # full table (400 trials)
    python3 scripts/normalization_study.py --trials 50

Standard library only. Deterministic for a given --seed.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.scoring import Review, normalize  # noqa: E402


def fixture_graph(path: Path = ROOT / "fixtures.json") -> list[tuple[str, str]]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    repos: dict[str, str] = {}
    duplicates = set()
    for project in sorted(fixture["projects"], key=lambda row: (row["submitted_at"], row["id"])):
        if project["repo_url"] in repos:
            duplicates.add(project["id"])
        repos.setdefault(project["repo_url"], project["id"])
    return [(row["judge"], row["project"]) for row in fixture["scores"] if row["project"] not in duplicates]


def kendall_tau(truth: dict[str, float], estimate: dict[str, float]) -> float:
    keys = sorted(truth)
    concordant = discordant = 0
    for index, left in enumerate(keys):
        for right in keys[index + 1:]:
            product = (truth[left] - truth[right]) * (estimate[left] - estimate[right])
            concordant += product > 0
            discordant += product < 0
    return (concordant - discordant) / max(concordant + discordant, 1)


def judge_spread(reviews: list[Review], offsets: dict[str, float] | None) -> float:
    by_judge: dict[str, list[float]] = defaultdict(list)
    for review in reviews:
        value = review.raw - (offsets or {}).get(review.judge, 0.0)
        by_judge[review.judge].append(min(5.0, max(0.0, value)))
    return pstdev([mean(values) for values in by_judge.values()])


def run(trials: int, seed: int, penalties: tuple[float, ...], severity_sd: float = 0.4,
        noise_sd: float = 0.3) -> dict:
    rng = random.Random(seed)
    graph = fixture_graph()
    judges = sorted({judge for judge, _ in graph})
    projects = sorted({project for _, project in graph})
    results = {"raw": {"mae": [], "tau": []}}
    results.update({penalty: {"mae": [], "tau": []} for penalty in penalties})
    for _ in range(trials):
        severity = {judge: rng.gauss(0, severity_sd) for judge in judges}
        quality = {project: rng.uniform(1.5, 4.5) for project in projects}
        reviews = [Review(judge, project, min(5.0, max(0.0, quality[project] + severity[judge]
                                                         + rng.gauss(0, noise_sd))))
                   for judge, project in graph]
        by_project: dict[str, list[float]] = defaultdict(list)
        for review in reviews:
            by_project[review.project].append(review.raw)
        raw = {project: mean(values) for project, values in by_project.items()}
        results["raw"]["mae"].append(mean(abs(raw[p] - quality[p]) for p in projects))
        results["raw"]["tau"].append(kendall_tau(quality, raw))
        for penalty in penalties:
            adjusted = normalize(reviews, penalty=penalty)["adjusted"]
            results[penalty]["mae"].append(mean(abs(adjusted[p] - quality[p]) for p in projects))
            results[penalty]["tau"].append(kendall_tau(quality, adjusted))
    return {key: {metric: mean(values) for metric, values in value.items()} for key, value in results.items()}


def fixture_spread() -> list[tuple[str, float]]:
    fixture = json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))
    graph = set(fixture_graph())
    reviews = []
    for row in fixture["scores"]:
        if (row["judge"], row["project"]) in graph:
            values = row["criteria"]
            reviews.append(Review(row["judge"], row["project"], sum(values.values()) / len(values)))
    # Fixture criteria are equally weighted in the seeded rubric.
    rows = [("raw", judge_spread(reviews, None))]
    for penalty in (0.01, 1.0, 3.0):
        rows.append((f"penalty {penalty:g}", judge_spread(reviews, normalize(reviews, penalty=penalty)["offsets"])))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=400)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    penalties = (0.01, 1.0, 3.0, 5.0)
    table = run(args.trials, args.seed, penalties)
    print(f"Planted-truth recovery on the fixture review graph ({args.trials} trials, seed {args.seed})")
    print("judge severity sd 0.4, review noise sd 0.3, project quality U(1.5, 4.5)\n")
    print(f"{'estimator':<18}{'mean abs error':>16}{'Kendall tau':>14}")
    print(f"{'raw mean':<18}{table['raw']['mae']:>16.3f}{table['raw']['tau']:>14.3f}")
    for penalty in penalties:
        label = f"calibrated λ={penalty:g}" + (" *" if penalty == 3.0 else "")
        print(f"{label:<18}{table[penalty]['mae']:>16.3f}{table[penalty]['tau']:>14.3f}")
    print("\n* shipped default\n")
    print("Fixture judge spread: population sd of each judge's mean review")
    for label, value in fixture_spread():
        print(f"  {label:<14} σ = {value:.3f}")


if __name__ == "__main__":
    main()
