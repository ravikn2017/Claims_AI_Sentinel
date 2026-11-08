"""Held-out metrics and the 15-day refresh predicate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

REFRESH_DAYS = 15
TECHNIQUES = (
    "logistic_regression",
    "random_forest",
    "xgboost",
    "soft_voting_ensemble",
)
PREFERENCE = {
    "soft_voting_ensemble": 4,
    "xgboost": 3,
    "random_forest": 2,
    "logistic_regression": 1,
}


def due(trained_at: datetime, now: datetime, days: int = REFRESH_DAYS) -> bool:
    if trained_at.tzinfo is None:
        trained_at = trained_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - trained_at >= timedelta(days=days)


def counts_at(labels: list[int], scores: list[float], threshold: float) -> dict[str, int]:
    tp = tn = fp = fn = 0
    for label, score in zip(labels, scores):
        predicted = score >= threshold
        if predicted and label == 1:
            tp += 1
        elif predicted and label == 0:
            fp += 1
        elif label == 1:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "tn": tn, "fp": fp, "fn": fn}


def rates(counts: dict[str, int]) -> dict[str, float]:
    precision = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else 0.0
    recall = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def best_f1_threshold(labels: list[int], scores: list[float]) -> tuple[float, dict[str, int], dict[str, float]]:
    best_threshold = 0.5
    best_counts = counts_at(labels, scores, best_threshold)
    best_rates = rates(best_counts)
    for step in range(1, 20):
        threshold = step / 20
        found = counts_at(labels, scores, threshold)
        scored = rates(found)
        if scored["f1"] > best_rates["f1"]:
            best_threshold = threshold
            best_counts = found
            best_rates = scored
    return best_threshold, best_counts, best_rates


def band_thresholds(labels: list[int], scores: list[float], decision: float) -> dict[str, float]:
    ordered = sorted(set(round(score, 4) for score in scores))
    t_high = None
    for threshold in ordered:
        found = counts_at(labels, scores, threshold)
        precision = rates(found)["precision"]
        if found["tp"] + found["fp"] and precision >= 0.85:
            t_high = threshold
            break
    t_low = None
    for threshold in reversed(ordered):
        found = counts_at(labels, scores, threshold)
        recall = rates(found)["recall"]
        if found["tp"] + found["fn"] and recall >= 0.90:
            t_low = threshold
            break
    if t_high is None:
        t_high = decision
    if t_low is None:
        t_low = decision
    if t_low > t_high:
        t_low = t_high
    return {"t_low": float(t_low), "t_decision": float(decision), "t_high": float(t_high)}


def choose_technique(results: list[dict]) -> str:
    winner = max(results, key=lambda row: (row["f1"], PREFERENCE[row["technique"]]))
    return winner["technique"]
