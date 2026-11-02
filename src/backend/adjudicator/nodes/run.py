"""Graph nodes. Stand-ins propose a result. These functions decide the next status."""

from __future__ import annotations

from langgraph.types import interrupt

from adjudicator.events import emit_decided, record_event
from adjudicator.nodes.routing import (
    ROUTE_NODES,
    collected_reasons,
    investigation_route,
    issues_of,
    join_route,
    medical_route,
    recommendation,
    risk_score,
    route_label,
    schema_issues,
)
from policy_compliance.graph.graph_builder import run_policy
from adjudicator.standin import result_for, scripted_result
from adjudicator.tasks import ensure_task, mark_done
from adjudicator.tools import payer

VERSIONS = {"source": "stand-in"}
POLICY_VERSIONS = {"source": "policy_compliance"}


def _ids(state: dict) -> tuple[str, int, str]:
    return state["claim_id"], int(state["attempt"]), state.get("correlation_id") or ""


def _stand_in(state: dict, agent: str) -> dict:
    last: Exception | None = None
    for _attempt in range(2):
        try:
            return result_for(state["claim_id"], agent)
        except Exception as exc:
            last = exc
    return {
        "agent": agent,
        "verdict": None,
        "confidence": 0,
        "reasons": [],
        "evidence": [],
        "error": str(last),
        "details": {},
    }


def _agent(state: dict, agent: str, field: str) -> dict:
    claim_id, attempt, correlation_id = _ids(state)
    result = _stand_in(state, agent)
    record_event(
        claim_id,
        attempt,
        correlation_id,
        "AGENT_RESULT",
        result,
        once=True,
        versions=VERSIONS,
    )
    return {field: result}


def load_claim(state: dict) -> dict:
    claim_id, attempt, correlation_id = _ids(state)
    claim = payer.get_claim(claim_id, attempt, correlation_id)
    record_event(
        claim_id,
        attempt,
        correlation_id,
        "RUN_STARTED",
        {"adjudication_attempt": attempt, "submission_id": state.get("submission_id"), "trigger": "claim.ready_for_adjudication"},
        once=True,
    )
    payer.request_transition(
        claim_id,
        attempt,
        "VALIDATED",
        "IN_ADJUDICATION",
        "ADJUDICATION_STARTED",
        "Adjudication started",
        None,
        correlation_id,
    )
    issues = schema_issues(claim)
    return {
        "claim": claim,
        "schema_ok": not issues,
        "schema_issues": issues,
        "status": "CHECKS_RUNNING" if not issues else "CHECKS_FAILED",
    }


def after_load(state: dict) -> str | list[str]:
    if state.get("schema_ok"):
        return ["policy_check", "fraud_check"]
    return "return_to_claimant"


def policy_check(state: dict) -> dict:
    claim_id, attempt, correlation_id = _ids(state)
    scripted = scripted_result(claim_id, "policy_compliance")
    if scripted is not None:
        result = scripted
        versions = VERSIONS
    else:
        result = run_policy(state)
        versions = POLICY_VERSIONS
    record_event(
        claim_id,
        attempt,
        correlation_id,
        "AGENT_RESULT",
        result,
        once=True,
        versions=versions,
    )
    return {"policy_result": result}


def fraud_check(state: dict) -> dict:
    return _agent(state, "fraud_detection", "fraud_result")


def route_node(state: dict) -> dict:
    claim_id, attempt, correlation_id = _ids(state)
    step = join_route(state)
    record_event(
        claim_id,
        attempt,
        correlation_id,
        "ROUTED",
        {"rule": route_label(state, step), "next_step": step},
    )
    return {"next_step": step, "status": "ROUTED"}


def after_route(state: dict) -> str:
    return ROUTE_NODES[state["next_step"]]


def investigation(state: dict) -> dict:
    claim_id, attempt, correlation_id = _ids(state)
    summary = {
        "kind": "investigation",
        "policy_result": state.get("policy_result"),
        "fraud_result": state.get("fraud_result"),
        "recommendation": "deny",
        "risk_score": risk_score(state),
    }
    ensure_task(claim_id, attempt, "INVESTIGATION", summary, risk_score(state))
    record_event(claim_id, attempt, correlation_id, "INVESTIGATION_REQUESTED", summary, once=True)
    payload = interrupt({"task_type": "INVESTIGATION", "claim_id": claim_id, "attempt": attempt})
    if not isinstance(payload, dict):
        payload = {"outcome": payload, "notes": ""}
    record_event(
        claim_id,
        attempt,
        correlation_id,
        "INVESTIGATION_RESULT",
        {"outcome": payload.get("outcome"), "notes": payload.get("notes") or ""},
        once=True,
    )
    updated = {**state, "investigation": payload}
    step = investigation_route(updated)
    record_event(
        claim_id,
        attempt,
        correlation_id,
        "ROUTED",
        {"rule": route_label(updated, step), "next_step": step},
    )
    return {"investigation": payload, "next_step": step, "status": "ROUTED"}


def after_investigation(state: dict) -> str:
    return after_route(state)


def medical_necessity(state: dict) -> dict:
    claim_id, attempt, correlation_id = _ids(state)
    result = _agent(state, "medical_necessity", "med_result")
    updated = {**state, **result}
    step = medical_route(updated)
    record_event(
        claim_id,
        attempt,
        correlation_id,
        "ROUTED",
        {"rule": route_label(updated, step), "next_step": step},
    )
    return {**result, "next_step": step, "status": "MED_NECESSITY_RUNNING"}


def after_medical(state: dict) -> str:
    return after_route(state)


def _review_summary(state: dict) -> dict:
    return {
        "policy_result": state.get("policy_result"),
        "fraud_result": state.get("fraud_result"),
        "med_result": state.get("med_result"),
        "investigation": state.get("investigation"),
        "recommendation": recommendation(state),
        "risk_score": risk_score(state),
        "reasons": collected_reasons(state),
    }


def human_review(state: dict) -> dict:
    claim_id, attempt, correlation_id = _ids(state)
    summary = _review_summary(state)
    ensure_task(claim_id, attempt, "REVIEW", summary, risk_score(state))
    payer.request_transition(
        claim_id,
        attempt,
        "IN_ADJUDICATION",
        "PENDING_REVIEW",
        "ADJUDICATION_NEEDS_REVIEW",
        "A reviewer decides this claim",
        None,
        correlation_id,
    )
    record_event(claim_id, attempt, correlation_id, "REVIEW_REQUESTED", summary, once=True)
    payload = interrupt({"task_type": "REVIEW", "claim_id": claim_id, "attempt": attempt, "summary": summary})
    if not isinstance(payload, dict):
        payload = {"decision": payload}
    record_event(
        claim_id,
        attempt,
        correlation_id,
        "REVIEW_DECIDED",
        {
            "decision": payload.get("decision"),
            "allowed_amount": payload.get("allowed_amount") or 0,
            "reviewer": payload.get("reviewer") or "",
            "notes": payload.get("notes") or "",
        },
        once=True,
    )
    mark_done(claim_id, attempt, "REVIEW")
    return {"summary": summary, "decision": payload, "status": "AWAITING_REVIEW"}


def decide(state: dict) -> dict:
    claim_id, attempt, correlation_id = _ids(state)
    decision = state.get("decision") or {}
    to_status = decision.get("decision")
    allowed = float(decision.get("allowed_amount") or 0)
    reasons = collected_reasons(state)
    payer.request_transition(
        claim_id,
        attempt,
        "PENDING_REVIEW",
        to_status,
        "REVIEW_APPROVED" if to_status == "APPROVED" else "REVIEW_DENIED",
        decision.get("notes") or "Reviewer decision",
        None,
        correlation_id,
    )
    emit_decided(claim_id, attempt, to_status, allowed, reasons, correlation_id)
    record_event(
        claim_id,
        attempt,
        correlation_id,
        "DECIDED",
        {"decision": to_status, "allowed_amount": allowed, "reasons": reasons},
        once=True,
    )
    return {"status": "DECIDED"}


def return_to_claimant(state: dict) -> dict:
    claim_id, attempt, correlation_id = _ids(state)
    policy = state.get("policy_result") or {}
    med = state.get("med_result") or {}
    if not state.get("schema_ok", True):
        issues = state.get("schema_issues") or issues_of({})
        reason = issues[0]["message"]
        code = "SCHEMA_CHECK_FAILED"
        kind = "PENDING_INFO"
    elif med.get("verdict") == "NEEDS_INFO" or policy.get("verdict") == "NEEDS_INFO":
        source = med if med.get("verdict") == "NEEDS_INFO" else policy
        issues = issues_of(source)
        reason = issues[0]["message"]
        code = "ADJUDICATION_NEEDS_INFO"
        kind = "PENDING_INFO"
    else:
        issues = None
        reasons = list(policy.get("reasons") or []) or ["The service is not covered."]
        reason = reasons[0]
        code = "NOT_COVERED"
        kind = "DENIED"
    if kind == "PENDING_INFO":
        payer.request_transition(
            claim_id,
            attempt,
            "IN_ADJUDICATION",
            "PENDING_INFO",
            code,
            reason,
            issues,
            correlation_id,
        )
        record_event(
            claim_id,
            attempt,
            correlation_id,
            "RETURNED_TO_CLAIMANT",
            {"outcome": "PENDING_INFO", "reason_code": code, "reasons": [reason], "issues": issues},
            once=True,
        )
        return {"status": "RETURNED_TO_CLAIMANT"}
    payer.request_transition(
        claim_id,
        attempt,
        "IN_ADJUDICATION",
        "DENIED",
        code,
        reason,
        None,
        correlation_id,
    )
    emit_decided(claim_id, attempt, "DENIED", 0.0, reasons, correlation_id)
    record_event(
        claim_id,
        attempt,
        correlation_id,
        "RETURNED_TO_CLAIMANT",
        {"outcome": "DENIED", "reason_code": code, "reasons": reasons},
        once=True,
    )
    return {"status": "RETURNED_TO_CLAIMANT", "decision": {"decision": "DENIED", "allowed_amount": 0, "reasons": reasons}}
