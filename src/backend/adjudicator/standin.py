"""Scripted agent results. A missing script uses the covered, clear, necessary path."""

from __future__ import annotations

_SCRIPTS: dict[str, dict[str, dict]] = {}

DEFAULTS = {
    "policy_compliance": {
        "verdict": "COVERED",
        "confidence": 0.95,
        "reasons": ["Stand-in: the line is covered."],
        "evidence": [],
        "error": None,
        "details": {},
    },
    "fraud_detection": {
        "verdict": "CLEAR",
        "confidence": 0.95,
        "reasons": ["Stand-in: the claim is clear."],
        "evidence": [],
        "error": None,
        "details": {},
    },
    "medical_necessity": {
        "verdict": "NECESSARY",
        "confidence": 0.95,
        "reasons": ["Stand-in: the service is necessary."],
        "evidence": [],
        "error": None,
        "details": {},
    },
}


def set_stand_in(claim_id: str, agent: str, result: dict) -> None:
    _SCRIPTS.setdefault(claim_id, {})[agent] = result


def clear_stand_in(claim_id: str | None = None) -> None:
    if claim_id is None:
        _SCRIPTS.clear()
        return
    _SCRIPTS.pop(claim_id, None)


def scripted_result(claim_id: str, agent: str) -> dict | None:
    source = _SCRIPTS.get(claim_id, {}).get(agent)
    if source is None:
        return None
    return _shape(agent, source)


def result_for(claim_id: str, agent: str) -> dict:
    scripted = _SCRIPTS.get(claim_id, {}).get(agent)
    source = scripted if scripted is not None else DEFAULTS[agent]
    return _shape(agent, source)


def _shape(agent: str, source: dict) -> dict:
    return {
        "agent": agent,
        "verdict": source.get("verdict"),
        "confidence": source.get("confidence", 0),
        "reasons": list(source.get("reasons") or []),
        "evidence": list(source.get("evidence") or []),
        "error": source.get("error"),
        "details": dict(source.get("details") or {}),
    }
