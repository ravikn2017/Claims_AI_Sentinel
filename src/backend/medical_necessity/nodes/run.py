"""Medical necessity nodes. The model proposes a quote. The next node keeps or drops it."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from adjudicator.tools import documents, payer
from medical_necessity.nodes import propose
from medical_necessity.nodes.decide import (
    error_result,
    judge_line,
    missing_record_line,
    not_applicable_line,
    policy_from_chunks,
    provider_flags,
    rollup,
)


def _line_no(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def gate_node(state: dict) -> dict:
    claim = state.get("claim") or {}
    details = (state.get("policy_result") or {}).get("details") or {}
    flags = provider_flags(claim)
    if "covered_lines" not in details:
        return _stopped("Policy did not list covered lines.", flags)
    covered = {_line_no(number) for number in details.get("covered_lines") or []}
    covered.discard(None)
    if not covered:
        return _stopped("No covered lines to judge.", flags)
    by_no = {}
    for raw in claim.get("lines") or []:
        number = _line_no(raw.get("line_no"))
        if number is not None:
            by_no[number] = raw
    if not covered <= set(by_no):
        return _stopped("A covered line is not on the claim.", flags)
    prepared = []
    try:
        for number in sorted(covered):
            raw = by_no[number]
            cpt = str(raw.get("cpt_code") or "")
            chunks = documents.get_medical_policy(cpt)
            item = {"line_no": number, "cpt_code": cpt, "policy": None, "preset": None}
            if not chunks:
                item["preset"] = "not_applicable"
            else:
                policy = policy_from_chunks(chunks)
                if policy is None:
                    return _stopped("Medical policy logic is unreadable.", flags)
                item["policy"] = policy
            prepared.append(item)
        notes = []
        if any(item["policy"] for item in prepared):
            notes = payer.get_medical_records(
                state.get("claim_id") or "",
                int(state.get("attempt") or 1),
                state.get("correlation_id") or "",
            )
            if not notes:
                for item in prepared:
                    if item["policy"]:
                        item["preset"] = "needs_info"
    except Exception as exc:
        return _stopped(str(exc), flags)
    pending = [item["line_no"] for item in prepared if item["preset"] is None]
    return {
        "prepared": prepared,
        "notes": notes,
        "pending": pending,
        "findings": {},
        "attempts": {},
        "gate_error": None,
        "retry": False,
    }


def _stopped(message: str, flags: list[str]) -> dict:
    return {
        "prepared": [],
        "notes": [],
        "pending": [],
        "findings": {},
        "attempts": {},
        "gate_error": message,
        "retry": False,
        "result": error_result(message, flags),
    }


def after_gate(state: dict) -> str:
    if state.get("gate_error") or not state.get("pending"):
        return "finalize"
    return "evaluate"


def evaluate_node(state: dict, config: RunnableConfig) -> dict:
    findings = dict(state.get("findings") or {})
    attempts = dict(state.get("attempts") or {})
    by_no = {item["line_no"]: item for item in state.get("prepared") or []}
    notes = state.get("notes") or []
    diagnoses = (state.get("claim") or {}).get("diagnosis_codes") or []
    for line_no in state.get("pending") or []:
        item = by_no[line_no]
        try:
            proposal = propose.propose_line(item, item["policy"], diagnoses, notes, config)
            findings[line_no] = proposal.model_dump()
        except Exception as exc:
            findings[line_no] = {"error": str(exc)}
        attempts[line_no] = int(attempts.get(line_no) or 0) + 1
    return {"findings": findings, "attempts": attempts, "retry": False}


def finalize_node(state: dict) -> dict:
    claim = state.get("claim") or {}
    flags = provider_flags(claim)
    if state.get("gate_error"):
        return {"retry": False, "result": state.get("result") or error_result(state["gate_error"], flags)}
    prepared = state.get("prepared") or []
    if not prepared:
        return {"retry": False, "result": error_result("No covered lines to judge.", flags)}
    decisions = []
    retry_lines = []
    failed = None
    attempts = state.get("attempts") or {}
    findings = state.get("findings") or {}
    notes = state.get("notes") or []
    for item in prepared:
        if item.get("preset") == "not_applicable":
            decisions.append(not_applicable_line(item))
            continue
        if item.get("preset") == "needs_info":
            decisions.append(missing_record_line(item))
            continue
        outcome = judge_line(item, findings.get(item["line_no"]) or {}, notes)
        if outcome["action"] == "keep":
            decisions.append(outcome)
            continue
        if int(attempts.get(item["line_no"]) or 0) < 2:
            retry_lines.append(item["line_no"])
        else:
            failed = outcome.get("error") or "A quote is not in the cited note."
    if failed:
        return {"retry": False, "result": error_result(failed, flags)}
    if retry_lines:
        return {"pending": retry_lines, "retry": True}
    return {"pending": [], "retry": False, "result": rollup(decisions, flags)}


def after_finalize(state: dict) -> str:
    return "evaluate" if state.get("retry") else "done"
