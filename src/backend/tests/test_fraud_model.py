"""Classical fraud model. Code keeps the best F1 and never clears a failure."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from fraud_detection.metrics import TECHNIQUES, choose_technique, due
from fraud_detection.scoring import clear_model_cache, score_claim
from fraud_detection.training import activate, train


def _clean() -> dict:
    return {
        "rendering_npi": "1234567893",
        "service_from": "2026-10-20",
        "service_to": "2026-10-20",
        "flags": [],
        "lines": [{"cpt_code": "99213", "units": 1, "billed_amount": "185.00", "service_date": "2026-10-20"}],
        "reference_snapshot": {"policy": {"termination_date": None}, "provider": {"npi": "1234567893"}},
    }


def _upcoding() -> dict:
    return {
        "rendering_npi": "1234567893",
        "service_from": "2026-10-20",
        "service_to": "2026-10-20",
        "flags": [],
        "lines": [{"cpt_code": "99215", "units": 8, "billed_amount": "2000.00", "service_date": "2026-10-20"}],
        "reference_snapshot": {"policy": {"termination_date": None}, "provider": {"npi": "1234567893"}},
    }


def _excluded() -> dict:
    claim = _clean()
    claim["rendering_npi"] = "9999999999"
    claim["reference_snapshot"] = {"policy": {"termination_date": None}, "provider": {"npi": "9999999999"}}
    return claim


@pytest.fixture(scope="module")
def trained():
    clear_model_cache()
    report = train()
    clear_model_cache()
    return report


def test_refresh_is_due_at_15_days():
    trained_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert due(trained_at, trained_at + timedelta(days=14)) is False
    assert due(trained_at, trained_at + timedelta(days=15)) is True


def test_every_technique_has_a_confusion_matrix(trained):
    found = {row["technique"]: row for row in trained["techniques"]}
    assert set(found) == set(TECHNIQUES)
    selected = [name for name, row in found.items() if row["selected"]]
    assert selected == [choose_technique(trained["techniques"])]
    for row in found.values():
        assert row["tp"] + row["tn"] + row["fp"] + row["fn"] > 0
        for key in ("precision", "recall", "f1"):
            assert 0 <= row[key] <= 1


def test_a_click_can_choose_another_technique(trained):
    original = trained["active_technique"]
    chosen = next(name for name in TECHNIQUES if name != original)
    try:
        report = activate(chosen)
        assert report["active_technique"] == chosen
        assert [row["technique"] for row in report["techniques"] if row["selected"]] == [chosen]
    finally:
        activate(original)
        clear_model_cache()


def test_clean_claim_is_clear_and_planted_claim_is_flagged(trained):
    clean = score_claim(_clean(), "CLM-FRAUD-CLEAN")
    planted = score_claim(_upcoding(), "CLM-FRAUD-UPCODE")
    excluded = score_claim(_excluded(), "CLM-FRAUD-EXCLUDED")
    assert clean["error"] is None
    assert clean["verdict"] == "CLEAR"
    assert clean["confidence"] >= 0.7
    assert planted["error"] is None
    assert planted["verdict"] == "FLAGGED"
    assert planted["confidence"] >= 0.7
    assert planted["details"]["rule_hits"] == []
    assert excluded["verdict"] == "FLAGGED"
    assert excluded["confidence"] == 1.0
    assert excluded["details"]["rule_hits"] == ["R_EXCLUDED_PROVIDER"]


def test_missing_model_does_not_clear(monkeypatch):
    monkeypatch.setattr("fraud_detection.scoring.load_model", lambda: None)
    result = score_claim(_clean(), "CLM-FRAUD-MISSING")
    assert result["error"]
    assert result["verdict"] != "CLEAR"


def test_down_service_does_not_clear(monkeypatch):
    def down(*_args, **_kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("adjudicator.tools.fraud.httpx.post", down)
    from adjudicator.tools.fraud import score_claim as remote_score

    result = remote_score(_clean(), "CLM-FRAUD-DOWN", "corr")
    assert result["error"]
    assert result["verdict"] != "CLEAR"
