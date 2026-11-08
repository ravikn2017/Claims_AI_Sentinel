"""Join rules from the adjudicator design. Routing reads the shared result fields."""

from __future__ import annotations

import os
import re
from decimal import Decimal, InvalidOperation

CONFIDENCE_MIN = 0.7
CPT_RE = re.compile(r"^[0-9]{4}[0-9A-Z]$")
ICD_RE = re.compile(r"^[A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?$")

ROUTE_NODES = {
    "medical_necessity": "medical_necessity",
    "return": "return_to_claimant",
    "investigation": "investigation",
    "review": "human_review",
}


def denials_to_review() -> bool:
    return os.environ.get("ROUTE_DENIALS_TO_REVIEW", "false").strip().lower() in {"1", "true", "yes"}


def uncertain(result: dict | None) -> bool:
    if not result:
        return True
    if result.get("error"):
        return True
    try:
        score = float(result.get("confidence"))
    except (TypeError, ValueError):
        return True
    return score < CONFIDENCE_MIN


def _amount(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def schema_issues(claim: dict) -> list[dict]:
    issues: list[dict] = []
    if not claim.get("member_id"):
        issues.append({"field_path": "member_id", "issue_code": "MISSING_FIELD", "message": "Member is required."})
    codes = claim.get("diagnosis_codes") or []
    if not codes:
        issues.append({"field_path": "diagnosis_codes", "issue_code": "MISSING_FIELD", "message": "A diagnosis code is required."})
    else:
        for code in codes:
            if not ICD_RE.match(str(code)):
                issues.append(
                    {
                        "field_path": "diagnosis_codes",
                        "issue_code": "INVALID_CODE",
                        "message": f"Diagnosis code {code} is not a valid ICD-10 code.",
                    }
                )
    lines = claim.get("lines") or []
    if not lines:
        issues.append({"field_path": "lines", "issue_code": "MISSING_FIELD", "message": "At least one claim line is required."})
    for line in lines:
        line_no = line.get("line_no", "")
        cpt = str(line.get("cpt_code") or "")
        if not CPT_RE.match(cpt):
            issues.append(
                {
                    "field_path": f"lines[{line_no}].cpt_code",
                    "issue_code": "INVALID_CODE",
                    "message": f"Line {line_no} needs a valid CPT code.",
                }
            )
        if _amount(line.get("billed_amount")) <= 0:
            issues.append(
                {
                    "field_path": f"lines[{line_no}].billed_amount",
                    "issue_code": "AMOUNT_MISMATCH",
                    "message": f"Line {line_no} amount must be greater than zero.",
                }
            )
    if _amount(claim.get("total_billed")) <= 0:
        issues.append(
            {
                "field_path": "total_billed",
                "issue_code": "AMOUNT_MISMATCH",
                "message": "Total billed amount must be greater than zero.",
            }
        )
    return issues


def join_route(state: dict) -> str:
    policy = state.get("policy_result") or {}
    fraud = state.get("fraud_result") or {}
    if fraud.get("verdict") == "FLAGGED" and not uncertain(fraud):
        return "investigation"
    if uncertain(policy) or uncertain(fraud):
        return "review"
    verdict = policy.get("verdict")
    if verdict == "COVERED":
        return "medical_necessity"
    if verdict == "NOT_COVERED" and denials_to_review():
        return "review"
    if verdict in {"NOT_COVERED", "NEEDS_INFO"}:
        return "return"
    return "review"


def investigation_route(state: dict) -> str:
    outcome = (state.get("investigation") or {}).get("outcome")
    policy = state.get("policy_result") or {}
    if outcome == "CONFIRMED":
        return "review"
    if outcome == "CLEARED" and policy.get("verdict") == "COVERED" and not uncertain(policy):
        return "medical_necessity"
    if outcome == "CLEARED" and policy.get("verdict") == "NOT_COVERED" and denials_to_review():
        return "review"
    if outcome == "CLEARED" and policy.get("verdict") in {"NOT_COVERED", "NEEDS_INFO"}:
        return "return"
    return "review"


def medical_route(state: dict) -> str:
    med = state.get("med_result") or {}
    if uncertain(med):
        return "review"
    if med.get("verdict") == "NEEDS_INFO":
        return "return"
    return "review"


def route_label(state: dict, step: str) -> str:
    policy = state.get("policy_result") or {}
    fraud = state.get("fraud_result") or {}
    med = state.get("med_result") or {}
    investigation = state.get("investigation") or {}
    if investigation.get("outcome") == "CONFIRMED":
        return "investigation_confirmed"
    if investigation.get("outcome") == "CLEARED":
        return f"investigation_cleared_{policy.get('verdict')}"
    if med:
        return f"medical_{med.get('verdict')}"
    if uncertain(policy) or uncertain(fraud):
        return "error_or_low_confidence"
    if fraud.get("verdict") == "FLAGGED":
        return "fraud_flagged"
    return f"{policy.get('verdict')}_{fraud.get('verdict')}_{step}"


def recommendation(state: dict) -> str:
    if (state.get("investigation") or {}).get("outcome") == "CONFIRMED":
        return "deny"
    verdict = (state.get("med_result") or {}).get("verdict")
    if verdict == "NOT_NECESSARY":
        return "deny"
    if verdict == "NECESSARY":
        return "approve"
    return "review"


def risk_score(state: dict) -> float:
    fraud = state.get("fraud_result") or {}
    if fraud.get("verdict") != "FLAGGED":
        return 0
    try:
        return float(fraud.get("confidence") or 0)
    except (TypeError, ValueError):
        return 0


def collected_reasons(state: dict) -> list[str]:
    reasons: list[str] = []
    for key in ("policy_result", "fraud_result", "med_result"):
        for reason in (state.get(key) or {}).get("reasons") or []:
            if reason not in reasons:
                reasons.append(str(reason))
    notes = (state.get("decision") or {}).get("notes")
    if notes and notes not in reasons:
        reasons.append(str(notes))
    return reasons


def issues_of(result: dict) -> list[dict]:
    details = result.get("details") or {}
    found = []
    for item in details.get("issues") or []:
        if isinstance(item, dict) and item.get("field_path") and item.get("issue_code") and item.get("message"):
            found.append(
                {
                    "field_path": item["field_path"],
                    "issue_code": item["issue_code"],
                    "message": item["message"],
                }
            )
    if found:
        return found
    reasons = result.get("reasons") or []
    message = reasons[0] if reasons else "More information is required before this claim can be adjudicated."
    return [{"field_path": "claim", "issue_code": "ADJUDICATION_NEEDS_INFO", "message": message}]
