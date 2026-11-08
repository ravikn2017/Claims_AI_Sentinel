"""Load the active model, apply hard rules, and let code set the verdict."""

from __future__ import annotations

import json

import joblib
from sqlalchemy import text

from fraud_detection.db import fraud_engine
from fraud_detection.features import build_features, feature_vector
from fraud_detection.training import model_dir

_cached: dict | None = None
_cached_version: str | None = None
_cached_technique: str | None = None

RULE_TEXT = {
    "R_EXCLUDED_PROVIDER": "Billing provider is on the exclusion list.",
    "R_SERVICE_AFTER_END": "Service date is after coverage ended.",
    "R_IMPOSSIBLE_DAY": "Provider units on one date exceed 24 hours.",
}


def error_envelope(message: str) -> dict:
    return {
        "agent": "fraud_detection",
        "verdict": None,
        "confidence": 0,
        "reasons": [],
        "evidence": [],
        "error": message,
        "details": {},
    }


def _view(payload: dict, technique: str) -> dict | None:
    estimators = payload.get("estimators") or {}
    thresholds_by = payload.get("thresholds_by_technique") or {}
    if technique in estimators and technique in thresholds_by:
        return {
            "estimator": estimators[technique],
            "technique": technique,
            "thresholds": {key: float(value) for key, value in thresholds_by[technique].items()},
            "features": payload.get("features"),
        }
    if payload.get("technique") == technique and payload.get("estimator") is not None:
        return payload
    return None


def load_model() -> dict | None:
    global _cached, _cached_version, _cached_technique
    with fraud_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT model_version, active_technique
                FROM fraud.model_run
                WHERE status = 'succeeded'
                ORDER BY trained_at DESC
                LIMIT 1
                """
            )
        ).first()
    if row is None or not row[0]:
        return None
    version = str(row[0])
    technique = str(row[1] or "")
    if _cached is not None and _cached_version == version and _cached_technique == technique:
        return _cached
    path = model_dir(version) / "model.joblib"
    if not path.is_file():
        return None
    view = _view(joblib.load(path), technique)
    if view is None:
        return None
    _cached = view
    _cached_version = version
    _cached_technique = technique
    return view


def clear_model_cache() -> None:
    global _cached, _cached_version, _cached_technique
    _cached = None
    _cached_version = None
    _cached_technique = None


def excluded_npis() -> set[str]:
    with fraud_engine().connect() as conn:
        rows = conn.execute(text("SELECT npi FROM fraud.excluded_provider")).all()
    return {str(row[0]) for row in rows}


def claim_npis(claim: dict) -> set[str]:
    found: set[str] = set()
    if claim.get("rendering_npi"):
        found.add(str(claim["rendering_npi"]))
    provider = (claim.get("reference_snapshot") or {}).get("provider") or {}
    if provider.get("npi"):
        found.add(str(provider["npi"]))
    billing = claim.get("billing_provider") or {}
    if isinstance(billing, dict) and billing.get("npi"):
        found.add(str(billing["npi"]))
    return found


def hard_rules(claim: dict, excluded: set[str]) -> list[str]:
    hits: list[str] = []
    if claim_npis(claim) & excluded:
        hits.append("R_EXCLUDED_PROVIDER")
    policy = (claim.get("reference_snapshot") or {}).get("policy") or {}
    end = policy.get("termination_date")
    start = claim.get("service_from")
    if end and start and str(start) > str(end):
        hits.append("R_SERVICE_AFTER_END")
    totals: dict[str, float] = {}
    for line in claim.get("lines") or []:
        day = str(line.get("service_date") or claim.get("service_from") or "")
        try:
            units = float(line.get("units") or 0)
        except (TypeError, ValueError):
            units = 0
        totals[day] = totals.get(day, 0) + units
    if any(total > 24 for total in totals.values()):
        hits.append("R_IMPOSSIBLE_DAY")
    return hits


def _confidence(score: float, band: str, thresholds: dict) -> float:
    if band == "rule":
        return 1.0
    if band == "gray":
        return 0.6
    if band == "high":
        span = 1 - thresholds["t_high"]
        extra = 0 if span <= 0 else 0.3 * (score - thresholds["t_high"]) / span
        return round(min(1.0, 0.7 + extra), 2)
    span = thresholds["t_low"]
    extra = 0 if span <= 0 else 0.3 * (span - score) / span
    return round(min(1.0, 0.7 + extra), 2)


def _reasons(features: dict, rule_hits: list[str], band: str) -> list[str]:
    if rule_hits:
        return [RULE_TEXT[code] for code in rule_hits]
    reasons = []
    if features["em_level"] >= 5 and features["billed_ratio"] >= 2:
        reasons.append(
            f"Level-5 visit billed at {features['billed_ratio']:.1f} times the typical amount."
        )
    if features["units_ratio"] >= 4:
        reasons.append(f"Units are {features['units_ratio']:.0f} times a typical visit.")
    if features["unbundling"] >= 1:
        reasons.append("Component codes are billed separately on the same date.")
    if features["near_duplicate_count"] >= 2:
        reasons.append(f"{int(features['near_duplicate_count'])} similar claims for this member and service.")
    if reasons:
        return reasons
    if band == "low":
        return ["The visit level, amount, and units look like a typical claim."]
    return ["The model score is in the review band."]


def band(score: float, rule_hits: list[str], thresholds: dict, features: dict, version: str, technique: str) -> dict:
    if rule_hits:
        band_name, verdict, confidence = "rule", "FLAGGED", 1.0
    elif score >= thresholds["t_high"]:
        band_name, verdict = "high", "FLAGGED"
        confidence = _confidence(score, "high", thresholds)
    elif score < thresholds["t_low"]:
        band_name, verdict = "low", "CLEAR"
        confidence = _confidence(score, "low", thresholds)
    else:
        band_name = "gray"
        verdict = "FLAGGED" if score >= thresholds["t_decision"] else "CLEAR"
        confidence = 0.6
    reasons = _reasons(features, rule_hits, band_name)
    headline = reasons[0]
    return {
        "agent": "fraud_detection",
        "verdict": verdict,
        "confidence": confidence,
        "reasons": reasons,
        "evidence": [f"model {version}", f"technique {technique}"],
        "error": None,
        "details": {
            "risk_score": round(score, 4),
            "band": band_name,
            "model_version": version,
            "technique": technique,
            "rule_hits": rule_hits,
            "thresholds": thresholds,
            "narrative": {
                "headline": headline,
                "summary": " ".join(reasons),
                "source": "template",
            },
        },
    }


def propose(claim: dict) -> dict:
    model = load_model()
    features = build_features(claim)
    if model is None:
        return {"features": features, "error": "Fraud model is unavailable"}
    vector = [feature_vector(features)]
    score = float(model["estimator"].predict_proba(vector)[0, 1])
    return {
        "features": features,
        "probability": score,
        "model_version": _cached_version or "",
        "technique": model["technique"],
        "thresholds": {key: float(value) for key, value in model["thresholds"].items()},
        "error": None,
    }


def decide(claim: dict, proposal: dict) -> dict:
    if proposal.get("error"):
        return error_envelope(proposal["error"])
    features = proposal["features"]
    hits = hard_rules(claim, excluded_npis())
    return band(
        float(proposal["probability"]),
        hits,
        proposal["thresholds"],
        features,
        proposal["model_version"],
        proposal["technique"],
    )


def score_claim(claim: dict, claim_id: str) -> dict:
    from fraud_detection.graph.graph_builder import run_fraud

    result = run_fraud(claim, claim_id)
    if claim_id and not result.get("error"):
        features = build_features(claim)
        details = result.get("details") or {}
        fact = {
            "features": features,
            "risk_score": details.get("risk_score"),
            "technique": details.get("technique"),
            "rule_hits": details.get("rule_hits") or [],
            "thresholds": details.get("thresholds") or {},
        }
        narrative = details.get("narrative") or {}
        with fraud_engine().begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO fraud.fraud_assessment (
                        claim_id, model_version, risk_score, band, verdict, confidence,
                        fact_sheet, narrative, narrative_source
                    )
                    VALUES (
                        :claim_id, :model_version, :risk_score, :band, :verdict, :confidence,
                        CAST(:fact_sheet AS jsonb), CAST(:narrative AS jsonb), 'template'
                    )
                    """
                ),
                {
                    "claim_id": claim_id,
                    "model_version": details.get("model_version") or "unknown",
                    "risk_score": details.get("risk_score"),
                    "band": details.get("band"),
                    "verdict": result.get("verdict"),
                    "confidence": result.get("confidence"),
                    "fact_sheet": json.dumps(fact),
                    "narrative": json.dumps(narrative),
                },
            )
    return result
