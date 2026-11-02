"""Adjudicator routing. Stand-ins supply the verdict. The payer client is a stub."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from adjudicator.consumer import handle_body
from adjudicator.db import adjudicator_engine
from adjudicator.nodes.routing import investigation_route, join_route, medical_route
from adjudicator.service import resume_investigation, resume_review, start_run
from adjudicator.standin import clear_stand_in, set_stand_in
from adjudicator.tools import payer


def _result(verdict: str, confidence: float = 0.95, error=None, issues=None, reasons=None) -> dict:
    return {
        "verdict": verdict,
        "confidence": confidence,
        "reasons": reasons or [verdict],
        "evidence": [],
        "error": error,
        "details": {"issues": issues} if issues is not None else {},
    }


def _state(policy: dict, fraud: dict, **extra) -> dict:
    return {"policy_result": policy, "fraud_result": fraud, **extra}


class Recorder:
    def __init__(self):
        self.transitions: list[dict] = []
        self.claims: dict[str, dict] = {}

    def get_claim(self, claim_id: str, attempt: int, correlation_id: str) -> dict:
        return self.claims[claim_id]

    def request_transition(self, claim_id, attempt, from_status, to_status, reason_code, reason, issues, correlation_id):
        self.transitions.append(
            {
                "from_status": from_status,
                "to_status": to_status,
                "reason_code": reason_code,
                "issues": issues or [],
            }
        )
        return "applied"


def _claim(claim_id: str, amount: str = "120.00") -> dict:
    return {
        "claim_id": claim_id,
        "member_id": "M-100",
        "policy_id": "POL-1",
        "diagnosis_codes": ["M54.5"],
        "total_billed": amount,
        "lines": [{"line_no": 1, "cpt_code": "99213", "billed_amount": amount}],
    }


def _targets(recorder: Recorder) -> list[str]:
    return [row["to_status"] for row in recorder.transitions]


def _events(claim_id: str) -> list[dict]:
    with adjudicator_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT event_type, payload
                FROM adjudication.adjudication_event
                WHERE claim_id = :claim_id
                ORDER BY event_id
                """
            ),
            {"claim_id": claim_id},
        ).mappings()
        return [dict(row) for row in rows]


def _outbox(claim_id: str) -> list[dict]:
    with adjudicator_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT payload FROM adjudication.outbox WHERE claim_id = :claim_id ORDER BY id"),
            {"claim_id": claim_id},
        ).mappings()
        return [dict(row)["payload"] for row in rows]


def _tasks(claim_id: str) -> list[dict]:
    with adjudicator_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT task_type, status, summary
                FROM adjudication.review_tasks
                WHERE claim_id = :claim_id
                ORDER BY task_id
                """
            ),
            {"claim_id": claim_id},
        ).mappings()
        return [dict(row) for row in rows]


def _agents(claim_id: str) -> list[str]:
    names = []
    for event in _events(claim_id):
        if event["event_type"] == "AGENT_RESULT":
            names.append(event["payload"]["agent"])
    return names


@pytest.fixture
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(payer, "get_claim", rec.get_claim)
    monkeypatch.setattr(payer, "request_transition", rec.request_transition)
    yield rec
    clear_stand_in()


def _begin(recorder: Recorder, amount: str = "120.00") -> str:
    claim_id = f"CLM-ADJ-{uuid4().hex[:12]}"
    recorder.claims[claim_id] = _claim(claim_id, amount)
    return claim_id


def _ready(claim_id: str) -> bytes:
    return (
        '{"message_type":"claim.ready_for_adjudication","schema_version":"1.1",'
        f'"message_id":"{uuid4()}","claim_id":"{claim_id}","submission_id":"sub-{claim_id}",'
        '"validated_at":"2026-11-01T00:00:00Z","flags":[],"adjudication_attempt":1}'
    ).encode()


def test_join_table():
    covered = _result("COVERED")
    clear = _result("CLEAR")
    assert join_route(_state(covered, clear)) == "medical_necessity"
    assert join_route(_state(_result("NOT_COVERED"), clear)) == "return"
    assert join_route(_state(_result("NEEDS_INFO"), clear)) == "return"
    assert join_route(_state(covered, _result("FLAGGED"))) == "investigation"
    assert join_route(_state(_result("COVERED", 0.6), clear)) == "review"
    assert join_route(_state(_result("COVERED", error="lookup failed"), clear)) == "review"
    assert investigation_route(_state(covered, clear, investigation={"outcome": "CONFIRMED"})) == "review"
    assert investigation_route(_state(covered, clear, investigation={"outcome": "CLEARED"})) == "medical_necessity"
    assert investigation_route(_state(_result("NOT_COVERED"), clear, investigation={"outcome": "CLEARED"})) == "return"
    assert medical_route({"med_result": _result("NECESSARY")}) == "review"
    assert medical_route({"med_result": _result("NOT_NECESSARY")}) == "review"
    assert medical_route({"med_result": _result("NEEDS_INFO")}) == "return"
    assert medical_route({"med_result": _result("NECESSARY", error="timeout")}) == "review"


def _script_policy_covered(claim_id: str) -> None:
    set_stand_in(claim_id, "policy_compliance", _result("COVERED"))


def test_covered_clear_necessary_pauses_then_approves(recorder):
    claim_id = _begin(recorder)
    _script_policy_covered(claim_id)
    handle_body(_ready(claim_id), "corr-1")
    assert "PENDING_REVIEW" in _targets(recorder)
    assert "DENIED" not in _targets(recorder)
    assert "APPROVED" not in _targets(recorder)
    assert _outbox(claim_id) == []
    assert _tasks(claim_id)[0]["task_type"] == "REVIEW"
    assert _tasks(claim_id)[0]["summary"]["recommendation"] == "approve"

    resumed = resume_review(claim_id, 1, "APPROVED", 80, "reviewer-1", "ok")
    assert resumed["result"] == "resumed"
    assert "APPROVED" in _targets(recorder)
    assert _outbox(claim_id)[0]["decision"] == "APPROVED"
    assert len(_outbox(claim_id)) == 1
    again = resume_review(claim_id, 1, "APPROVED", 80, "reviewer-1", "ok")
    assert again["result"] == "ignored"
    assert len(_outbox(claim_id)) == 1


def test_not_necessary_waits_for_the_reviewer(recorder):
    claim_id = _begin(recorder)
    _script_policy_covered(claim_id)
    set_stand_in(claim_id, "medical_necessity", _result("NOT_NECESSARY", reasons=["The notes do not support the service."]))
    start_run(claim_id, 1, "sub", "corr")
    assert _tasks(claim_id)[0]["summary"]["recommendation"] == "deny"
    assert "DENIED" not in _targets(recorder)
    assert _outbox(claim_id) == []
    resume_review(claim_id, 1, "DENIED", 0, "reviewer-1", "not necessary")
    assert "DENIED" in _targets(recorder)
    assert _outbox(claim_id)[0]["decision"] == "DENIED"


def test_policy_needs_info_returns_issues(recorder):
    claim_id = _begin(recorder)
    issue = {
        "field_path": "lines[1].prior_auth_number",
        "issue_code": "PRIOR_AUTH_REQUIRED",
        "message": "Provide the authorization number.",
    }
    set_stand_in(claim_id, "policy_compliance", _result("NEEDS_INFO", issues=[issue]))
    start_run(claim_id, 1, "sub", "corr")
    pending = [row for row in recorder.transitions if row["to_status"] == "PENDING_INFO"]
    assert pending[0]["issues"] == [issue]
    assert "DENIED" not in _targets(recorder)
    assert _outbox(claim_id) == []
    assert "medical_necessity" not in _agents(claim_id)


def test_not_covered_denies_without_review(recorder):
    claim_id = _begin(recorder)
    set_stand_in(claim_id, "policy_compliance", _result("NOT_COVERED", reasons=["Excluded by the plan."]))
    start_run(claim_id, 1, "sub", "corr")
    assert "DENIED" in _targets(recorder)
    assert _tasks(claim_id) == []
    assert _outbox(claim_id)[0]["decision"] == "DENIED"
    assert len(_outbox(claim_id)) == 1
    assert "medical_necessity" not in _agents(claim_id)


def test_flagged_claim_waits_for_investigation(recorder):
    claim_id = _begin(recorder)
    _script_policy_covered(claim_id)
    set_stand_in(claim_id, "fraud_detection", _result("FLAGGED", confidence=0.91, reasons=["Unusual units."]))
    start_run(claim_id, 1, "sub", "corr")
    assert _targets(recorder) == ["IN_ADJUDICATION"]
    assert _tasks(claim_id)[0]["task_type"] == "INVESTIGATION"
    assert "medical_necessity" not in _agents(claim_id)
    resume_investigation(claim_id, 1, "CONFIRMED", "pattern matches")
    assert "PENDING_REVIEW" in _targets(recorder)
    assert "DENIED" not in _targets(recorder)
    assert "medical_necessity" not in _agents(claim_id)
    review = [row for row in _tasks(claim_id) if row["task_type"] == "REVIEW"]
    assert review[0]["summary"]["recommendation"] == "deny"


def test_low_confidence_and_error_go_to_review(recorder):
    low = _begin(recorder)
    set_stand_in(low, "policy_compliance", _result("COVERED", confidence=0.6))
    start_run(low, 1, "sub", "corr")
    assert "PENDING_REVIEW" in _targets(recorder)
    assert "DENIED" not in _targets(recorder)
    assert "medical_necessity" not in _agents(low)

    before = len(recorder.transitions)
    failed = _begin(recorder)
    set_stand_in(failed, "policy_compliance", _result("COVERED", error="lookup failed"))
    start_run(failed, 1, "sub", "corr")
    failed_rows = recorder.transitions[before:]
    assert "PENDING_REVIEW" in [row["to_status"] for row in failed_rows]
    assert "DENIED" not in [row["to_status"] for row in failed_rows]
    assert "medical_necessity" not in _agents(failed)


def test_schema_failure_asks_for_information(recorder):
    claim_id = _begin(recorder, amount="0")
    start_run(claim_id, 1, "sub", "corr")
    assert "PENDING_INFO" in _targets(recorder)
    assert "DENIED" not in _targets(recorder)
    assert _agents(claim_id) == []
    pending = [row for row in recorder.transitions if row["to_status"] == "PENDING_INFO"]
    assert pending[0]["issues"][0]["issue_code"] == "AMOUNT_MISMATCH"


def test_redelivery_does_not_start_a_second_run(recorder):
    claim_id = _begin(recorder)
    _script_policy_covered(claim_id)
    body = _ready(claim_id)
    handle_body(body, "corr")
    handle_body(body, "corr")
    started = [event for event in _events(claim_id) if event["event_type"] == "RUN_STARTED"]
    assert len(started) == 1
    assert set(_agents(claim_id)) == {"policy_compliance", "fraud_detection", "medical_necessity"}


def test_adjudication_event_is_append_only():
    claim_id = f"CLM-ADJ-{uuid4().hex[:12]}"
    with pytest.raises(DBAPIError):
        with adjudicator_engine().begin() as conn:
            event_id = conn.execute(
                text(
                    """
                    INSERT INTO adjudication.adjudication_event
                        (claim_id, adjudication_attempt, actor, event_type, payload)
                    VALUES (:claim_id, 1, 'adjudicator:test', 'RUN_STARTED', '{}'::jsonb)
                    RETURNING event_id
                    """
                ),
                {"claim_id": claim_id},
            ).scalar_one()
            conn.execute(
                text("UPDATE adjudication.adjudication_event SET actor = 'changed' WHERE event_id = :event_id"),
                {"event_id": event_id},
            )
