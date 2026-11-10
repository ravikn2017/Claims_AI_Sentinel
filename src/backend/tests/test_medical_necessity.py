"""Medical necessity. A quote is kept only when it is in the cited note."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from adjudicator.db import adjudicator_engine
from adjudicator.errors import AdjudicationError
from adjudicator.index import chunk_markdown
from adjudicator.service import start_run
from adjudicator.standin import clear_stand_in, set_stand_in
from adjudicator.tools import documents, payer
from db_url import ROOT
from medical_necessity.graph.graph_builder import run_medical
from medical_necessity.nodes.propose import CriterionFinding, LineFindings

NECESSARY_NOTE = "8 weeks of PT and NSAIDs, pain unchanged"
UNNECESSARY_NOTE = "Back pain for 1 week. No neuro deficit."


class _Response:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def _chunks(doc_id: str, cpt: str) -> list[dict]:
    body = (ROOT / "data" / "medical_policies" / f"{doc_id}.md").read_text()
    return [{"doc_id": doc_id, "doc_type": "medical_policy", "cpt_codes": [cpt], **chunk} for chunk in chunk_markdown(body)]


def _policies(cpt: str) -> list[dict]:
    if cpt == "72148":
        return _chunks("MP-001", cpt)
    if cpt == "97110":
        return _chunks("MP-003", cpt)
    return []


def _line(line_no: int, cpt: str, amount: str = "185.00") -> dict:
    return {"line_no": line_no, "cpt_code": cpt, "billed_amount": amount, "diagnosis_pointers": [1]}


def _claim(lines: list[dict], rating: int = 4, city: str = "Minneapolis", state: str = "MN") -> dict:
    total = "230.00" if len(lines) > 1 else "185.00"
    return {
        "member_id": "MBR-100231",
        "diagnosis_codes": ["M54.5"],
        "total_billed": total,
        "service_from": "2026-10-20",
        "service_to": "2026-10-20",
        "reference_snapshot": {
            "provider": {
                "npi": "1678901236" if rating <= 2 else "1234567893",
                "network_status": "in",
                "quality_rating": rating,
                "city": city,
                "state": state,
            }
        },
        "lines": lines,
    }


def _notes(body: str, document_id: str = "DOC-1") -> list[dict]:
    return [{"document_id": document_id, "received_at": "2026-10-20T00:00:00", "text": body}]


def _mri_necessary(*_args, **_kwargs) -> LineFindings:
    return LineFindings(
        criteria=[
            CriterionFinding(criterion_id="MP-001.1", status="met", quote="8   Weeks of PT and NSAIDs, pain unchanged", document_id="DOC-1"),
            CriterionFinding(criterion_id="MP-001.2", status="not_documented"),
        ]
    )


def _mri_unnecessary(*_args, **_kwargs) -> LineFindings:
    return LineFindings(
        criteria=[
            CriterionFinding(criterion_id="MP-001.1", status="not_met", quote="Back pain for 1 week.", document_id="DOC-1"),
            CriterionFinding(criterion_id="MP-001.2", status="not_met", quote="No neuro deficit.", document_id="DOC-1"),
        ]
    )


def _forbid_model(*_args, **_kwargs):
    raise AssertionError("model called")


def _bad_quote(*_args, **_kwargs) -> LineFindings:
    return LineFindings(
        criteria=[
            CriterionFinding(criterion_id="MP-001.1", status="met", quote="not in the notes", document_id="DOC-1"),
            CriterionFinding(criterion_id="MP-001.2", status="not_documented"),
        ]
    )


def _run(monkeypatch, claim: dict, covered: list[int], notes: list[dict] | None, propose):
    calls = {"model": 0, "records": 0}

    def propose_line(*args, **kwargs):
        calls["model"] += 1
        if propose is None:
            raise AssertionError("model called")
        return propose(*args, **kwargs)

    def get_records(*_args, **_kwargs):
        calls["records"] += 1
        return list(notes or [])

    monkeypatch.setattr(documents, "get_medical_policy", _policies)
    monkeypatch.setattr(payer, "get_medical_records", get_records)
    monkeypatch.setattr("medical_necessity.nodes.propose.propose_line", propose_line)
    result = run_medical(
        {
            "claim": claim,
            "claim_id": "CLM-MN",
            "attempt": 1,
            "correlation_id": "corr-1",
            "policy_result": {"verdict": "COVERED", "confidence": 1, "details": {"covered_lines": covered}},
        }
    )
    return result, calls


def _tasks(claim_id: str) -> list[dict]:
    with adjudicator_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT task_type, summary
                FROM adjudication.review_tasks
                WHERE claim_id = :claim_id
                ORDER BY task_id
                """
            ),
            {"claim_id": claim_id},
        ).mappings()
        return [dict(row) for row in rows]


def _walk(monkeypatch, lines: list[dict], covered: list[int], notes: list[dict], propose, rating: int = 4):
    claim_id = f"CLM-MN-{uuid4().hex[:12]}"
    claim = _claim(lines, rating=rating)
    claim["claim_id"] = claim_id
    transitions = []

    def get_claim(claim_id: str, attempt: int, correlation_id: str) -> dict:
        return claim

    def request_transition(claim_id, attempt, from_status, to_status, reason_code, reason, issues, correlation_id):
        transitions.append({"to_status": to_status, "issues": issues or []})
        return "applied"

    monkeypatch.setattr(payer, "get_claim", get_claim)
    monkeypatch.setattr(payer, "request_transition", request_transition)
    monkeypatch.setattr(documents, "get_medical_policy", _policies)
    monkeypatch.setattr(payer, "get_medical_records", lambda *_args, **_kwargs: list(notes))
    monkeypatch.setattr("medical_necessity.nodes.propose.propose_line", propose or _forbid_model)
    set_stand_in(
        claim_id,
        "policy_compliance",
        {
            "verdict": "COVERED",
            "confidence": 0.95,
            "reasons": ["covered"],
            "evidence": [],
            "error": None,
            "details": {"covered_lines": covered},
        },
    )
    set_stand_in(
        claim_id,
        "fraud_detection",
        {"verdict": "CLEAR", "confidence": 0.95, "reasons": ["clear"], "evidence": [], "error": None, "details": {}},
    )
    try:
        start_run(claim_id, 1, "sub", "corr")
        return claim_id, transitions
    finally:
        clear_stand_in(claim_id)


def test_medical_records_use_the_medical_actor(monkeypatch):
    seen = {}

    def fake(method, url, headers, json=None, timeout=30):
        seen["actor"] = headers["X-Actor-Id"]
        seen["url"] = url
        seen["correlation"] = headers["X-Correlation-ID"]
        return _Response(200, [{"document_id": "DOC-1", "received_at": "2026-10-20T00:00:00", "text": "note"}])

    monkeypatch.setattr("adjudicator.tools.payer.httpx.request", fake)
    rows = payer.get_medical_records("CLM-1", 1, "corr-1")
    assert rows == [{"document_id": "DOC-1", "received_at": "2026-10-20T00:00:00", "text": "note"}]
    assert seen["actor"] == "adjudicator:medical_necessity"
    assert seen["correlation"] == "corr-1"
    assert "/claims/CLM-1/medical-records" in seen["url"]


def test_payer_outage_is_an_error(monkeypatch):
    def fake(method, url, headers, json=None, timeout=30):
        return _Response(503, {"detail": "down"})

    monkeypatch.setattr("adjudicator.tools.payer.httpx.request", fake)
    try:
        payer.get_medical_records("CLM-1", 1, "corr-1")
    except AdjudicationError as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("expected AdjudicationError")


def test_necessary_mri_reaches_review_with_approve(monkeypatch):
    lines = [_line(1, "72148"), _line(2, "99213", "45.00")]
    result, calls = _run(monkeypatch, _claim(lines), [1, 2], _notes(NECESSARY_NOTE), _mri_necessary)
    assert result["verdict"] == "NECESSARY"
    assert result["confidence"] == 0.8
    assert result["error"] is None
    assert calls["model"] == 1
    mri = result["details"]["lines"][0]
    assert mri["status"] == "meets"
    assert mri["carc"] is None

    claim_id, transitions = _walk(monkeypatch, lines, [1, 2], _notes(NECESSARY_NOTE), _mri_necessary)
    statuses = [row["to_status"] for row in transitions]
    assert "PENDING_REVIEW" in statuses
    assert "DENIED" not in statuses
    summary = _tasks(claim_id)[0]["summary"]
    assert summary["recommendation"] == "approve"
    assert summary["med_result"]["verdict"] == "NECESSARY"


def test_unnecessary_mri_reaches_review_with_deny(monkeypatch):
    lines = [_line(1, "72148"), _line(2, "99213", "45.00")]
    result, _calls = _run(monkeypatch, _claim(lines), [1, 2], _notes(UNNECESSARY_NOTE), _mri_unnecessary)
    assert result["verdict"] == "NOT_NECESSARY"
    assert result["error"] is None
    assert result["details"]["lines"][0]["carc"] == "CO-50"
    assert result["details"]["lines"][0]["status"] == "does_not_meet"

    claim_id, transitions = _walk(monkeypatch, lines, [1, 2], _notes(UNNECESSARY_NOTE), _mri_unnecessary)
    statuses = [row["to_status"] for row in transitions]
    assert "PENDING_REVIEW" in statuses
    assert "DENIED" not in statuses
    assert _tasks(claim_id)[0]["summary"]["recommendation"] == "deny"


def test_bad_quote_retries_then_review_without_denial(monkeypatch):
    lines = [_line(1, "72148")]
    result, calls = _run(monkeypatch, _claim(lines), [1], _notes(NECESSARY_NOTE), _bad_quote)
    assert calls["model"] == 2
    assert result["error"]
    assert result["verdict"] is None

    claim_id, transitions = _walk(monkeypatch, lines, [1], _notes(NECESSARY_NOTE), _bad_quote)
    statuses = [row["to_status"] for row in transitions]
    assert "PENDING_REVIEW" in statuses
    assert "DENIED" not in statuses
    assert _tasks(claim_id)[0]["summary"]["recommendation"] == "review"


def test_office_visit_skips_the_model(monkeypatch):
    result, calls = _run(monkeypatch, _claim([_line(1, "99213")]), [1], None, None)
    assert result["verdict"] == "NECESSARY"
    assert result["confidence"] == 1.0
    assert result["details"]["lines"][0]["status"] == "not_applicable"
    assert calls["model"] == 0
    assert calls["records"] == 0


def test_missing_record_asks_for_information(monkeypatch):
    lines = [_line(1, "72148")]
    result, calls = _run(monkeypatch, _claim(lines), [1], [], None)
    assert result["verdict"] == "NEEDS_INFO"
    assert result["confidence"] == 1.0
    assert calls["model"] == 0
    assert calls["records"] == 1
    assert result["details"]["issues"][0]["issue_code"] == "MEDICAL_RECORD"

    _claim_id, transitions = _walk(monkeypatch, lines, [1], [], None)
    statuses = [row["to_status"] for row in transitions]
    assert "PENDING_INFO" in statuses
    assert "DENIED" not in statuses
    pending = [row for row in transitions if row["to_status"] == "PENDING_INFO"]
    assert pending[0]["issues"][0]["issue_code"] == "MEDICAL_RECORD"


def test_low_quality_provider_flag_does_not_change_the_verdict(monkeypatch):
    lines = [_line(1, "72148")]
    result, _calls = _run(
        monkeypatch,
        _claim(lines, rating=2, city="Rochester", state="MN"),
        [1],
        _notes(NECESSARY_NOTE),
        _mri_necessary,
    )
    assert result["verdict"] == "NECESSARY"
    assert result["details"]["review_flags"] == ["Low-quality provider: rating 2/5, Rochester, MN."]
