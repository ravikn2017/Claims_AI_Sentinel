"""Fit the four techniques and keep the best F1 model."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.linear_model import LogisticRegression
from sqlalchemy import text
from xgboost import XGBClassifier

from fraud_detection.dataset import dataset_path, read_dataset, write_dataset
from fraud_detection.db import fraud_engine
from fraud_detection.features import FEATURE_NAMES
from fraud_detection.metrics import REFRESH_DAYS, TECHNIQUES, band_thresholds, best_f1_threshold, choose_technique, due

_lock = threading.Lock()


class TrainingBusy(Exception):
    """A run is already fitting."""


class UnknownTechnique(Exception):
    """The named technique is not one of the four."""


class TechniqueUnavailable(Exception):
    """This saved run does not contain that technique."""


def model_dir(version: str):
    root = dataset_path().parents[2]
    return root / "models" / "fraud" / version


def _matrix(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    values = [[float(row[name]) for name in FEATURE_NAMES] for row in rows]
    labels = [int(row["label"]) for row in rows]
    return np.array(values, dtype=float), np.array(labels, dtype=int)


def _estimators(positive_weight: float) -> dict:
    return {
        "logistic_regression": LogisticRegression(max_iter=500, class_weight="balanced", random_state=11),
        "random_forest": RandomForestClassifier(
            n_estimators=80,
            max_depth=8,
            class_weight="balanced",
            random_state=11,
            n_jobs=1,
        ),
        "xgboost": XGBClassifier(
            n_estimators=80,
            max_depth=4,
            scale_pos_weight=positive_weight,
            random_state=11,
            n_jobs=1,
            verbosity=0,
        ),
    }


def _fit_all(train_rows: list[dict], test_rows: list[dict]) -> tuple[list[dict], dict, dict]:
    train_x, train_y = _matrix(train_rows)
    test_x, test_y = _matrix(test_rows)
    positives = int(train_y.sum())
    negatives = int(len(train_y) - positives)
    weight = negatives / positives if positives else 1.0
    fitted = {}
    results = []
    labels = [int(value) for value in test_y]
    for name, estimator in _estimators(weight).items():
        estimator.fit(train_x, train_y)
        fitted[name] = estimator
        scores = [float(score) for score in estimator.predict_proba(test_x)[:, 1]]
        threshold, counts, scored = best_f1_threshold(labels, scores)
        results.append({"technique": name, "threshold": threshold, **counts, **scored, "scores": scores})
    ensemble = VotingClassifier(
        estimators=[(name, fitted[name]) for name in ("logistic_regression", "random_forest", "xgboost")],
        voting="soft",
    )
    ensemble.fit(train_x, train_y)
    fitted["soft_voting_ensemble"] = ensemble
    scores = [float(score) for score in ensemble.predict_proba(test_x)[:, 1]]
    threshold, counts, scored = best_f1_threshold(labels, scores)
    results.append(
        {"technique": "soft_voting_ensemble", "threshold": threshold, **counts, **scored, "scores": scores}
    )
    winner = choose_technique(results)
    # Band on the planted scheme. The noisy training label is only for the F1 matrix.
    planted = [0 if row["scheme"] == "clean" else 1 for row in test_rows]
    thresholds_by = {
        row["technique"]: band_thresholds(planted, row["scores"], row["threshold"]) for row in results
    }
    payload = {
        "estimators": fitted,
        "thresholds_by_technique": thresholds_by,
        "estimator": fitted[winner],
        "technique": winner,
        "thresholds": thresholds_by[winner],
        "features": list(FEATURE_NAMES),
    }
    public = []
    for row in results:
        public.append({key: value for key, value in row.items() if key != "scores"})
    return public, payload, {"labels": labels}


def _insert_run(version: str, rows: list[dict], results: list[dict], technique: str, thresholds: dict) -> str:
    run_id = f"run-{uuid4().hex[:12]}"
    fraud_count = sum(int(row["label"]) for row in rows)
    with fraud_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO fraud.model_run (
                    run_id, row_count, fraud_count, active_technique, model_version, thresholds, status
                )
                VALUES (
                    :run_id, :row_count, :fraud_count, :technique, :version, CAST(:thresholds AS jsonb), 'succeeded'
                )
                """
            ),
            {
                "run_id": run_id,
                "row_count": len(rows),
                "fraud_count": fraud_count,
                "technique": technique,
                "version": version,
                "thresholds": json.dumps(thresholds),
            },
        )
        for row in results:
            conn.execute(
                text(
                    """
                    INSERT INTO fraud.technique_result (
                        run_id, technique, threshold, tp, tn, fp, fn, precision, recall, f1, selected
                    )
                    VALUES (
                        :run_id, :technique, :threshold, :tp, :tn, :fp, :fn, :precision, :recall, :f1, :selected
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "technique": row["technique"],
                    "threshold": row["threshold"],
                    "tp": row["tp"],
                    "tn": row["tn"],
                    "fp": row["fp"],
                    "fn": row["fn"],
                    "precision": row["precision"],
                    "recall": row["recall"],
                    "f1": row["f1"],
                    "selected": row["technique"] == technique,
                },
            )
    return run_id


def _insert_failure(message: str) -> None:
    with fraud_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO fraud.model_run (run_id, row_count, fraud_count, status, error)
                VALUES (:run_id, 0, 0, 'failed', :error)
                """
            ),
            {"run_id": f"run-{uuid4().hex[:12]}", "error": message[:500]},
        )


def train() -> dict:
    if not _lock.acquire(blocking=False):
        raise TrainingBusy()
    try:
        try:
            write_dataset()
            rows = read_dataset()
            train_rows = [row for row in rows if row["split"] == "train"]
            test_rows = [row for row in rows if row["split"] == "test"]
            results, payload, _held = _fit_all(train_rows, test_rows)
            version = "claim-risk-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            folder = model_dir(version)
            folder.mkdir(parents=True, exist_ok=True)
            joblib.dump(payload, folder / "model.joblib")
            (folder / "thresholds.json").write_text(json.dumps(payload["thresholds"]))
            run_id = _insert_run(version, rows, results, payload["technique"], payload["thresholds"])
        except Exception as exc:
            try:
                _insert_failure(str(exc))
            except Exception:
                pass
            raise
        return report_for(run_id)
    finally:
        _lock.release()


def latest_success() -> dict | None:
    with fraud_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT run_id, trained_at, row_count, fraud_count, active_technique, model_version, thresholds
                FROM fraud.model_run
                WHERE status = 'succeeded'
                ORDER BY trained_at DESC
                LIMIT 1
                """
            )
        ).mappings().first()
    return dict(row) if row else None


def activate(technique: str) -> dict:
    if technique not in TECHNIQUES:
        raise UnknownTechnique(technique)
    current = latest_success()
    if current is None:
        raise TechniqueUnavailable("No fraud model has been trained yet")
    path = model_dir(current["model_version"]) / "model.joblib"
    payload = joblib.load(path)
    estimators = payload.get("estimators") or {}
    if technique not in estimators:
        raise TechniqueUnavailable("Train now once, then choose a technique. This run only kept the active model.")
    thresholds = payload["thresholds_by_technique"][technique]
    with fraud_engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE fraud.model_run
                SET active_technique = :technique, thresholds = CAST(:thresholds AS jsonb)
                WHERE run_id = :run_id
                """
            ),
            {"technique": technique, "thresholds": json.dumps(thresholds), "run_id": current["run_id"]},
        )
        conn.execute(
            text("UPDATE fraud.technique_result SET selected = FALSE WHERE run_id = :run_id"),
            {"run_id": current["run_id"]},
        )
        conn.execute(
            text(
                """
                UPDATE fraud.technique_result
                SET selected = TRUE
                WHERE run_id = :run_id AND technique = :technique
                """
            ),
            {"run_id": current["run_id"], "technique": technique},
        )
    from fraud_detection.scoring import clear_model_cache

    clear_model_cache()
    return report_for(current["run_id"])


def train_if_due(now: datetime | None = None) -> dict | None:
    current = latest_success()
    moment = now or datetime.now(timezone.utc)
    if current is not None and not due(current["trained_at"], moment, REFRESH_DAYS):
        return None
    return train()


def report_for(run_id: str | None = None) -> dict:
    with fraud_engine().connect() as conn:
        if run_id is None:
            run = conn.execute(
                text(
                    """
                    SELECT run_id, trained_at, row_count, fraud_count, active_technique, model_version, thresholds, status
                    FROM fraud.model_run
                    WHERE status = 'succeeded'
                    ORDER BY trained_at DESC
                    LIMIT 1
                    """
                )
            ).mappings().first()
        else:
            run = conn.execute(
                text(
                    """
                    SELECT run_id, trained_at, row_count, fraud_count, active_technique, model_version, thresholds, status
                    FROM fraud.model_run
                    WHERE run_id = :run_id
                    """
                ),
                {"run_id": run_id},
            ).mappings().first()
        if run is None:
            return {}
        techniques = conn.execute(
            text(
                """
                SELECT technique, threshold, tp, tn, fp, fn, precision, recall, f1, selected
                FROM fraud.technique_result
                WHERE run_id = :run_id
                ORDER BY technique
                """
            ),
            {"run_id": run["run_id"]},
        ).mappings()
        technique_rows = [dict(item) for item in techniques]
    trained_at = run["trained_at"]
    if trained_at.tzinfo is None:
        trained_at = trained_at.replace(tzinfo=timezone.utc)
    thresholds = run["thresholds"]
    if isinstance(thresholds, str):
        thresholds = json.loads(thresholds)
    return {
        "run_id": run["run_id"],
        "trained_at": trained_at.isoformat(),
        "next_refresh_at": (trained_at + timedelta(days=REFRESH_DAYS)).isoformat(),
        "row_count": int(run["row_count"]),
        "fraud_count": int(run["fraud_count"]),
        "active_technique": run["active_technique"],
        "model_version": run["model_version"],
        "thresholds": {key: float(value) for key, value in (thresholds or {}).items()},
        "dataset": "claim_risk_synthetic",
        "dataset_path": "data/fraud/claim_risk_synthetic.csv",
        "techniques": [
            {
                "technique": item["technique"],
                "threshold": float(item["threshold"]),
                "tp": int(item["tp"]),
                "tn": int(item["tn"]),
                "fp": int(item["fp"]),
                "fn": int(item["fn"]),
                "precision": float(item["precision"]),
                "recall": float(item["recall"]),
                "f1": float(item["f1"]),
                "selected": bool(item["selected"]),
            }
            for item in technique_rows
        ],
    }
