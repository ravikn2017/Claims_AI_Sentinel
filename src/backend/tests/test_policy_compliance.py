"""Policy compliance. Code settles a benefit row. A citation is kept only when search returned it."""

from __future__ import annotations

from uuid import uuid4

from adjudicator.nodes.routing import join_route
from policy_compliance.graph.graph_builder import run_policy
from policy_compliance.nodes.decide import rollup
from policy_compliance.nodes.propose import LineProposal
from adjudicator.service import start_run
from adjudicator.standin import clear_stand_in, set_stand_in
from adjudicator.tools import documents, payer


class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def _row(plan: str, cpt: str, covered: bool, auth: bool, section: str) -> dict:
    return {
        "found": True,
        "plan_code": plan,
        "cpt_code": cpt,
        "benefit_category": "office_visit",
        "is_covered": covered,
        "requires_prior_auth": auth,
        "policy_section": section,
    }


def _claim(plan: str, cpt: str, status: str = "active", prior: str | None = None, line_no: int = 1) -> dict:
    return {
        "member_id": "MBR-1",
        "service_from": "2026-10-20",
        "service_to": "2026-10-20",
        "diagnosis_codes": ["E11.9"],
        "total_billed": "120.00",
        "reference_snapshot": {
            "policy": {
                "plan_code": plan,
                "status": status,
                "effective_date": "2020-01-01",
                "termination_date": "2024-06-01" if status != "active" else None,
            },
            "provider": {"npi": "1234567893", "network_status": "in"},
        },
        "lines": [
            {
                "line_no": line_no,
                "cpt_code": cpt,
                "billed_amount": "120.00",
                "diagnosis_pointers": [1],
                "prior_auth_number": prior,
            }
        ],
    }


def _forbid_model(*_args, **_kwargs):
    raise AssertionError("model called")


def _forbid_search(*_args, **_kwargs):
    raise AssertionError("search called")


def _run(monkeypatch, claim: dict, benefit: dict | None, search=None, propose=None):
    def get_benefit(plan_code: str, cpt_code: str, correlation_id: str) -> dict:
        if benefit is None:
            raise AssertionError("benefit read")
        return benefit

    monkeypatch.setattr(payer, "get_plan_benefit", get_benefit)
    monkeypatch.setattr(documents, "search_policy_documents", search or _forbid_search)
    monkeypatch.setattr("policy_compliance.nodes.propose.propose_line", propose or _forbid_model)
    return run_policy({"claim": claim, "claim_id": "CLM-POL", "correlation_id": "corr-1"})


def test_missing_benefit_is_not_an_error(monkeypatch):
    seen = {}

    def fake(method, url, headers, json=None, timeout=30):
        seen["actor"] = headers["X-Actor-Id"]
        seen["correlation"] = headers["X-Correlation-ID"]
        seen["url"] = url
        return _Response(404, {"detail": "Plan benefit not found"})

    monkeypatch.setattr("adjudicator.tools.payer.httpx.request", fake)
    body = payer.get_plan_benefit("SILVER-PPO-01", "93000", "corr-1")
    assert body["found"] is False
    assert body["plan_code"] == "SILVER-PPO-01"
    assert body["cpt_code"] == "93000"
    assert seen["actor"] == "adjudicator:policy_compliance"
    assert seen["correlation"] == "corr-1"
    assert url_has(seen["url"], "SILVER-PPO-01", "93000")


def url_has(url: str, plan: str, cpt: str) -> bool:
    return f"/reference/plan-benefits/{plan}/{cpt}" in url


def test_benefit_row_is_returned(monkeypatch):
    def fake(method, url, headers, json=None, timeout=30):
        return _Response(
            200,
            {
                "plan_code": "SILVER-PPO-01",
                "cpt_code": "99213",
                "benefit_category": "office_visit",
                "is_covered": True,
                "requires_prior_auth": False,
                "policy_section": "§4.1",
            },
        )

    monkeypatch.setattr("adjudicator.tools.payer.httpx.request", fake)
    body = payer.get_plan_benefit("SILVER-PPO-01", "99213", "corr-1")
    assert body["found"] is True
    assert body["is_covered"] is True
    assert body["policy_section"] == "§4.1"


def test_silver_office_visit_is_covered(monkeypatch):
    result = _run(monkeypatch, _claim("SILVER-PPO-01", "99213"), _row("SILVER-PPO-01", "99213", True, False, "§4.1"))
    assert result["verdict"] == "COVERED"
    assert result["confidence"] == 1.0
    assert result["error"] is None
    assert any("SILVER-PPO-01/99213" in item for item in result["evidence"])


def test_bronze_exclusion_is_not_covered(monkeypatch):
    calls = {"model": 0}

    def search(plan_code, query):
        return [{"section": "§5.3", "heading": "Exclusions", "text": "Bariatric surgery is excluded.", "plan_code": plan_code}]

    def propose(*_args, **_kwargs):
        calls["model"] += 1
        return LineProposal(
            status="not_covered",
            reason_code="EXCLUDED_SERVICE",
            section="§5.3",
            explanation="Bariatric surgery is excluded.",
        )

    result = _run(
        monkeypatch,
        _claim("BRONZE-HMO-01", "43644"),
        _row("BRONZE-HMO-01", "43644", False, False, "§5.3"),
        search,
        propose,
    )
    assert result["verdict"] == "NOT_COVERED"
    assert result["confidence"] == 1.0
    assert result["error"] is None
    assert calls["model"] == 1
    assert any("§5.3" in item for item in result["evidence"])


def test_bad_citation_retries_then_errors(monkeypatch):
    calls = {"model": 0}

    def search(plan_code, query):
        return [{"section": "§5.3", "heading": "Exclusions", "text": "Bariatric surgery is excluded.", "plan_code": plan_code}]

    def propose(*_args, **_kwargs):
        calls["model"] += 1
        return LineProposal(status="not_covered", reason_code="EXCLUDED_SERVICE", section="§9.9", explanation="No")

    result = _run(
        monkeypatch,
        _claim("BRONZE-HMO-01", "43644"),
        _row("BRONZE-HMO-01", "43644", False, False, "§5.3"),
        search,
        propose,
    )
    assert result["error"]
    assert calls["model"] == 2
    clear = {"verdict": "CLEAR", "confidence": 0.95, "error": None}
    assert join_route({"policy_result": result, "fraud_result": clear}) == "review"


def test_inactive_policy_skips_the_model(monkeypatch):
    result = _run(monkeypatch, _claim("SILVER-PPO-01", "99213", status="terminated"), None)
    assert result["verdict"] == "NOT_COVERED"
    assert result["confidence"] == 1.0
    assert result["error"] is None


def test_prior_auth_asks_for_the_number(monkeypatch):
    result = _run(monkeypatch, _claim("SILVER-PPO-01", "72148"), _row("SILVER-PPO-01", "72148", True, True, "§4.3"))
    assert result["verdict"] == "NEEDS_INFO"
    assert result["confidence"] == 1.0
    issue = result["details"]["issues"][0]
    assert issue["field_path"] == "lines[1].prior_auth_number"
    assert issue["issue_code"] == "PRIOR_AUTH_REQUIRED"


def test_bad_citation_does_not_deny(monkeypatch):
    clear_stand_in()
    claim_id = f"CLM-POL-{uuid4().hex[:12]}"
    claim = _claim("BRONZE-HMO-01", "43644")
    claim["claim_id"] = claim_id
    transitions = []

    def get_claim(claim_id: str, attempt: int, correlation_id: str) -> dict:
        return claim

    def request_transition(claim_id, attempt, from_status, to_status, reason_code, reason, issues, correlation_id):
        transitions.append(to_status)
        return "applied"

    def search(plan_code, query):
        return [{"section": "§5.3", "heading": "Exclusions", "text": "Bariatric surgery is excluded.", "plan_code": plan_code}]

    def propose(*_args, **_kwargs):
        return LineProposal(status="not_covered", section="§9.9", explanation="No")

    monkeypatch.setattr(payer, "get_claim", get_claim)
    monkeypatch.setattr(payer, "request_transition", request_transition)
    monkeypatch.setattr(payer, "get_plan_benefit", lambda plan, cpt, correlation: _row(plan, cpt, False, False, "§5.3"))
    monkeypatch.setattr(documents, "search_policy_documents", search)
    monkeypatch.setattr("policy_compliance.nodes.propose.propose_line", propose)
    set_stand_in(
        claim_id,
        "fraud_detection",
        {"verdict": "CLEAR", "confidence": 0.95, "reasons": ["clear"], "evidence": [], "error": None, "details": {}},
    )
    start_run(claim_id, 1, "sub", "corr")
    assert "PENDING_REVIEW" in transitions
    assert "DENIED" not in transitions
    clear_stand_in()


def test_rollup_lists_covered_lines():
    lines = [
        {"line_no": 1, "cpt_code": "99213", "status": "covered", "reason_code": None, "reasons": ["Covered."], "evidence": [], "confidence": 1.0},
        {"line_no": 2, "cpt_code": "97810", "status": "not_covered", "reason_code": "EXCLUDED_SERVICE", "reasons": ["Excluded."], "evidence": [{"source": "plan_document", "ref": "BRONZE-HMO-01 §5.4"}], "confidence": 1.0},
    ]
    result = rollup("BRONZE-HMO-01", "in", lines)
    assert result["verdict"] == "COVERED"
    assert result["details"]["covered_lines"] == [1]
