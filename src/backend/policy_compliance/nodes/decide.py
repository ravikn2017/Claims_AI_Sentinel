"""Coverage facts and the decision to keep a model citation."""

from __future__ import annotations

from datetime import date, datetime


def _as_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def coverage_active(policy: dict | None, service_from, service_to) -> bool:
    if not policy or policy.get("status") != "active":
        return False
    effective = _as_date(policy.get("effective_date"))
    start = _as_date(service_from)
    end = _as_date(service_to)
    termination = _as_date(policy.get("termination_date"))
    if effective is None or start is None or end is None:
        return False
    if effective > start:
        return False
    if termination is not None and termination < end:
        return False
    return True


def prepare_line(claim: dict, raw: dict) -> dict:
    codes = list(claim.get("diagnosis_codes") or [])
    diagnoses = []
    for pointer in raw.get("diagnosis_pointers") or []:
        try:
            index = int(pointer) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(codes):
            diagnoses.append(str(codes[index]))
    number = raw.get("prior_auth_number")
    return {
        "line_no": raw.get("line_no"),
        "cpt_code": str(raw.get("cpt_code") or ""),
        "prior_auth_number": str(number).strip() if number else "",
        "diagnoses": diagnoses,
    }


def search_query(line: dict, benefit: dict, network: str | None) -> str:
    section = benefit.get("policy_section") or ""
    cpt = line["cpt_code"]
    if network == "out":
        return f"{section} out-of-network exception for {cpt}".strip()
    if not benefit.get("found"):
        return f"coverage for {cpt}"
    return f"{section} exclusion or exception for {cpt}".strip()


def _benefit_evidence(plan_code: str, cpt: str, section: str | None) -> list[dict]:
    evidence = [{"source": "plan_benefit", "ref": f"{plan_code}/{cpt}"}]
    if section:
        evidence.append({"source": "plan_document", "ref": f"{plan_code} {section}"})
    return evidence


def settle_from_row(line: dict, benefit: dict, network: str | None, plan_code: str) -> dict | None:
    """A covered in-network row is decided here. Exclusions and exceptions are not."""
    if network != "in" or not benefit.get("found") or benefit.get("is_covered") is not True:
        return None
    section = benefit.get("policy_section")
    cpt = line["cpt_code"]
    evidence = _benefit_evidence(plan_code, cpt, section)
    if benefit.get("requires_prior_auth") and not line.get("prior_auth_number"):
        return {
            "line_no": line["line_no"],
            "cpt_code": cpt,
            "status": "needs_info",
            "reason_code": "PRIOR_AUTH_REQUIRED",
            "reasons": [f"Line {line['line_no']} requires prior authorization for {cpt}."],
            "evidence": evidence,
            "confidence": 1.0,
        }
    if line.get("prior_auth_number"):
        reason = f"{cpt} is covered under {section}. Prior authorization {line['prior_auth_number']} is on the line."
    else:
        reason = f"{cpt} is covered under {section}."
    return {
        "line_no": line["line_no"],
        "cpt_code": cpt,
        "status": "covered",
        "reason_code": None,
        "reasons": [reason],
        "evidence": evidence,
        "confidence": 1.0,
    }


def _cited(section: str | None, passages: list[dict]) -> bool:
    if not section:
        return False
    return any(str(item.get("section") or "") == section for item in passages)


def _kept(line: dict, plan_code: str, benefit: dict, status: str, section: str | None, reason_code: str | None, reason: str, confidence: float) -> dict:
    evidence = []
    if benefit.get("found"):
        evidence.append({"source": "plan_benefit", "ref": f"{plan_code}/{line['cpt_code']}"})
    if section:
        evidence.append({"source": "plan_document", "ref": f"{plan_code} {section}"})
    return {
        "line_no": line["line_no"],
        "cpt_code": line["cpt_code"],
        "status": status,
        "reason_code": reason_code,
        "reasons": [reason],
        "evidence": evidence,
        "confidence": confidence,
    }


def accept_proposal(line: dict, benefit: dict, network: str | None, plan_code: str, proposal: dict, passages: list[dict]) -> dict:
    """Keep a proposal only when its section was retrieved, or the row has nothing to cite."""
    if proposal.get("error"):
        return {"action": "retry", "error": str(proposal["error"])}
    section = str(proposal.get("section") or "").strip() or None
    status = proposal.get("status")
    matched = _cited(section, passages)
    explanation = str(proposal.get("explanation") or "").strip()
    cpt = line["cpt_code"]

    if not benefit.get("found"):
        if matched and status in {"covered", "not_covered"}:
            code = None if status == "covered" else "EXCLUDED_SERVICE"
            reason = explanation or f"{cpt} is {status.replace('_', ' ')} under {section}."
            return {"action": "keep", "line": _kept(line, plan_code, benefit, status, section, code, reason, 0.8)}
        reason = explanation or f"Coverage for {cpt} could not be determined."
        return {
            "action": "keep",
            "line": _kept(line, plan_code, benefit, "needs_info", None, "BENEFIT_UNDETERMINED", reason, 0.5),
        }

    if status not in {"covered", "not_covered", "needs_info"} or not matched:
        return {"action": "retry", "error": "The citation was not in the retrieved plan sections."}

    agrees = benefit.get("is_covered") is False and status == "not_covered" and section == benefit.get("policy_section")
    if status == "needs_info":
        code = "BENEFIT_UNDETERMINED"
        reason = explanation or f"Coverage for {cpt} could not be determined."
        confidence = 0.8
    elif status == "not_covered" and network == "out" and benefit.get("is_covered") is True:
        code = "OUT_OF_NETWORK"
        reason = explanation or f"{cpt} is out of network."
        confidence = 0.8
    elif status == "not_covered":
        code = "EXCLUDED_SERVICE"
        reason = explanation or f"{cpt} is excluded under {section}."
        confidence = 1.0 if agrees else 0.8
    else:
        code = None
        reason = explanation or f"{cpt} is covered under {section}."
        confidence = 1.0 if agrees else 0.8
    kept = _kept(line, plan_code, benefit, status, section, code, reason, confidence)
    if status == "not_covered" and not kept["evidence"]:
        return {"action": "retry", "error": "A not-covered line needs evidence."}
    return {"action": "keep", "line": kept}


def _evidence_strings(lines: list[dict]) -> list[str]:
    found = []
    for line in lines:
        for item in line.get("evidence") or []:
            ref = item.get("ref") or ""
            text = f"plan_benefit {ref}" if item.get("source") == "plan_benefit" else str(ref)
            if text and text not in found:
                found.append(text)
    return found


def _details(plan_code: str | None, network: str | None, lines: list[dict], issues: list[dict], missing: list[str]) -> dict:
    return {
        "plan_code": plan_code,
        "network_status": network,
        "covered_lines": [line["line_no"] for line in lines if line.get("status") == "covered"],
        "lines": lines,
        "missing_info": missing,
        "issues": issues,
    }


def error_result(plan_code: str | None, network: str | None, message: str) -> dict:
    return {
        "agent": "policy_compliance",
        "verdict": None,
        "confidence": 0,
        "reasons": [],
        "evidence": [],
        "error": message,
        "details": _details(plan_code, network, [], [], []),
    }


def inactive_result(plan_code: str | None, network: str | None) -> dict:
    return {
        "agent": "policy_compliance",
        "verdict": "NOT_COVERED",
        "confidence": 1.0,
        "reasons": ["The policy is not active for these service dates."],
        "evidence": [],
        "error": None,
        "details": _details(plan_code, network, [], [], []),
    }


def rollup(plan_code: str | None, network: str | None, lines: list[dict]) -> dict:
    issues = []
    missing = []
    statuses = [line.get("status") for line in lines]
    if any(status == "needs_info" for status in statuses):
        verdict = "NEEDS_INFO"
    elif lines and all(status == "not_covered" for status in statuses):
        verdict = "NOT_COVERED"
    else:
        verdict = "COVERED"
    if verdict == "NEEDS_INFO":
        for line in lines:
            if line.get("status") != "needs_info":
                continue
            message = (line.get("reasons") or ["More information is required."])[0]
            missing.append(message)
            field = "prior_auth_number" if line.get("reason_code") == "PRIOR_AUTH_REQUIRED" else "cpt_code"
            issues.append(
                {
                    "field_path": f"lines[{line['line_no']}].{field}",
                    "issue_code": line.get("reason_code") or "BENEFIT_UNDETERMINED",
                    "message": message,
                }
            )
    reasons = []
    for line in lines:
        for reason in line.get("reasons") or []:
            if reason not in reasons:
                reasons.append(reason)
    confidence = min((float(line.get("confidence") or 0) for line in lines), default=0)
    return {
        "agent": "policy_compliance",
        "verdict": verdict,
        "confidence": confidence,
        "reasons": reasons,
        "evidence": _evidence_strings(lines),
        "error": None,
        "details": _details(plan_code, network, lines, issues, missing),
    }
