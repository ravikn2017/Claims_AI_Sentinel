"""Policy graph nodes. The model proposes. The next node keeps or drops the citation."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from policy_compliance.nodes import propose
from policy_compliance.nodes.decide import (
    accept_proposal,
    coverage_active,
    error_result,
    inactive_result,
    prepare_line,
    rollup,
    search_query,
    settle_from_row,
)
from adjudicator.tools import documents, payer


def gate_node(state: dict) -> dict:
    claim = state.get("claim") or {}
    snapshot = claim.get("reference_snapshot") or {}
    policy = snapshot.get("policy") or {}
    provider = snapshot.get("provider") or {}
    network = provider.get("network_status")
    if network not in {"in", "out"}:
        network = None
    return {
        "active": coverage_active(policy, claim.get("service_from"), claim.get("service_to")),
        "plan_code": policy.get("plan_code"),
        "network_status": network,
        "attempts": {},
        "proposals": {},
        "passages": {},
        "retry": False,
        "search_error": None,
    }


def after_gate(state: dict) -> str:
    return "settle" if state.get("active") else "inactive"


def inactive_node(state: dict) -> dict:
    return {"result": inactive_result(state.get("plan_code"), state.get("network_status")), "retry": False}


def settle_node(state: dict) -> dict:
    claim = state.get("claim") or {}
    plan_code = state.get("plan_code") or ""
    prepared = []
    pending = []
    for raw in claim.get("lines") or []:
        line = prepare_line(claim, raw)
        benefit = payer.get_plan_benefit(plan_code, line["cpt_code"], state.get("correlation_id") or "")
        decision = settle_from_row(line, benefit, state.get("network_status"), plan_code)
        prepared.append({"line": line, "benefit": benefit, "decision": decision})
        if decision is None:
            pending.append(line["line_no"])
    return {"prepared": prepared, "pending": pending}


def after_settle(state: dict) -> str:
    return "retrieve" if state.get("pending") else "finalize"


def retrieve_node(state: dict) -> dict:
    plan_code = state.get("plan_code") or ""
    by_no = {item["line"]["line_no"]: item for item in state.get("prepared") or []}
    passages = {}
    for line_no in state.get("pending") or []:
        item = by_no[line_no]
        query = search_query(item["line"], item["benefit"], state.get("network_status"))
        try:
            passages[line_no] = documents.search_policy_documents(plan_code, query)
        except Exception as exc:
            return {"passages": passages, "search_error": str(exc)}
    return {"passages": passages, "search_error": None}


def after_retrieve(state: dict) -> str:
    return "finalize" if state.get("search_error") else "propose"


def propose_node(state: dict, config: RunnableConfig) -> dict:
    proposals = dict(state.get("proposals") or {})
    attempts = dict(state.get("attempts") or {})
    by_no = {item["line"]["line_no"]: item for item in state.get("prepared") or []}
    for line_no in state.get("pending") or []:
        item = by_no[line_no]
        try:
            proposal = propose.propose_line(
                item["line"],
                item["benefit"],
                state.get("network_status"),
                state.get("plan_code"),
                (state.get("passages") or {}).get(line_no) or [],
                config,
            )
            proposals[line_no] = proposal.model_dump()
        except Exception as exc:
            proposals[line_no] = {"error": str(exc)}
        attempts[line_no] = int(attempts.get(line_no) or 0) + 1
    return {"proposals": proposals, "attempts": attempts, "retry": False}


def finalize_node(state: dict) -> dict:
    plan_code = state.get("plan_code")
    network = state.get("network_status")
    if state.get("search_error"):
        return {"retry": False, "result": error_result(plan_code, network, "Plan document search is unavailable")}
    prepared = state.get("prepared") or []
    if not prepared:
        return {"retry": False, "result": error_result(plan_code, network, "The claim has no lines.")}
    decisions = []
    retry_lines = []
    failed = None
    attempts = state.get("attempts") or {}
    for item in prepared:
        if item.get("decision") is not None:
            decisions.append(item["decision"])
            continue
        line_no = item["line"]["line_no"]
        proposal = (state.get("proposals") or {}).get(line_no) or {}
        passages = (state.get("passages") or {}).get(line_no) or []
        outcome = accept_proposal(item["line"], item["benefit"], network, plan_code or "", proposal, passages)
        if outcome["action"] == "keep":
            decisions.append(outcome["line"])
            continue
        if int(attempts.get(line_no) or 0) < 2:
            retry_lines.append(line_no)
        else:
            failed = outcome.get("error") or "The citation was not in the retrieved plan sections."
    if failed:
        return {"retry": False, "result": error_result(plan_code, network, failed)}
    if retry_lines:
        return {"pending": retry_lines, "retry": True}
    return {"pending": [], "retry": False, "result": rollup(plan_code, network, decisions)}


def after_finalize(state: dict) -> str:
    return "propose" if state.get("retry") else "done"
