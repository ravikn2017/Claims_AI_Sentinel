"""Fraud-service HTTP calls. A failure is an error, never a clear verdict."""

from __future__ import annotations

import os

import httpx


def fraud_base() -> str:
    return os.environ.get("FRAUD_SERVICE_URL", "http://127.0.0.1:47114")


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


def score_claim(claim: dict, claim_id: str, correlation_id: str) -> dict:
    try:
        response = httpx.post(
            f"{fraud_base()}/score",
            json={"claim_id": claim_id, "claim": claim},
            headers={
                "X-Actor-Type": "service",
                "X-Actor-Id": "adjudicator",
                "X-Actor-Role": "adjudicator",
                "X-Correlation-ID": correlation_id or "",
            },
            timeout=30,
        )
    except httpx.HTTPError:
        return error_envelope("Fraud model is unavailable")
    try:
        body = response.json()
    except ValueError:
        return error_envelope("Fraud model is unavailable")
    if response.status_code >= 500 or not isinstance(body, dict) or "agent" not in body:
        return error_envelope("Fraud model is unavailable")
    return body
