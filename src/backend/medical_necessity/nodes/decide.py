"""Line status from verified quotes. The model does not choose the verdict."""

from __future__ import annotations

import re

from adjudicator.index import POLICY_DIR, _front_matter

_LOGIC = re.compile(r"^(any_of|all_of)\(([^)]*)\)$")
_SPACE = re.compile(r"\s+")


def policy_logic(doc_id: str) -> dict | None:
    path = POLICY_DIR / f"{doc_id}.md"
    if not doc_id or not path.is_file():
        return None
    match = _LOGIC.match(_front_matter(path.read_text()).get("logic", "").strip())
    if match is None:
        return None
    criteria = [part.strip() for part in match.group(2).split(",") if part.strip()]
    if not criteria:
        return None
    return {"op": match.group(1), "criteria": criteria}


def policy_from_chunks(chunks: list[dict]) -> dict | None:
    if not chunks:
        return None
    doc_id = str(chunks[0].get("doc_id") or "")
    if not doc_id or any(str(chunk.get("doc_id") or "") != doc_id for chunk in chunks):
        return None
    logic = policy_logic(doc_id)
    if logic is None:
        return None
    by_section = {str(chunk.get("section") or ""): chunk for chunk in chunks}
    criteria = []
    for criterion_id in logic["criteria"]:
        chunk = by_section.get(criterion_id) or {}
        criteria.append(
            {
                "criterion_id": criterion_id,
                "heading": str(chunk.get("heading") or criterion_id),
                "text": str(chunk.get("text") or ""),
            }
        )
    return {"policy_id": doc_id, "op": logic["op"], "criteria": criteria}


def provider_flags(claim: dict) -> list[str]:
    provider = (claim.get("reference_snapshot") or {}).get("provider") or {}
    try:
        score = int(provider.get("quality_rating"))
    except (TypeError, ValueError):
        return []
    if score > 2:
        return []
    city = str(provider.get("city") or "").strip()
    state = str(provider.get("state") or "").strip()
    place = ", ".join(part for part in (city, state) if part)
    if place:
        return [f"Low-quality provider: rating {score}/5, {place}."]
    return [f"Low-quality provider: rating {score}/5."]


def _norm(value: str) -> str:
    return _SPACE.sub(" ", value.casefold()).strip()


def quote_in_note(quote: str | None, document_id: str | None, notes: list[dict]) -> bool:
    if not quote or not document_id:
        return False
    needle = _norm(quote)
    if not needle:
        return False
    for note in notes:
        if str(note.get("document_id") or "") != document_id:
            continue
        if needle in _norm(str(note.get("text") or "")):
            return True
    return False


def _label(criterion: dict) -> str:
    heading = str(criterion.get("heading") or criterion["criterion_id"])
    prefix = str(criterion["criterion_id"])
    if heading.startswith(prefix):
        rest = heading[len(prefix):].strip(" .:-")
        if rest:
            return rest
    return heading


def _public(line_no, cpt: str, policy_id: str | None, status: str, criteria: list[dict]) -> dict:
    return {
        "line_no": line_no,
        "cpt_code": cpt,
        "policy_id": policy_id,
        "status": status,
        "carc": "CO-50" if status == "does_not_meet" else None,
        "criteria": criteria,
    }


def not_applicable_line(item: dict) -> dict:
    line_no = item["line_no"]
    cpt = item["cpt_code"]
    return {
        "line": _public(line_no, cpt, None, "not_applicable", []),
        "reasons": [f"Line {line_no}: {cpt} has no medical policy."],
        "missing": [],
        "confidence": 1.0,
    }


def missing_record_line(item: dict) -> dict:
    line_no = item["line_no"]
    cpt = item["cpt_code"]
    policy = item["policy"]
    criteria = [
        {"criterion_id": row["criterion_id"], "status": "not_documented", "quote": None, "document_id": None}
        for row in policy["criteria"]
    ]
    message = f"Line {line_no} ({cpt}): a medical record is required ({policy['policy_id']})."
    return {
        "line": _public(line_no, cpt, policy["policy_id"], "needs_info", criteria),
        "reasons": [f"Line {line_no}: medical record not attached ({policy['policy_id']})."],
        "missing": [message],
        "confidence": 1.0,
    }


def judge_line(item: dict, finding: dict, notes: list[dict]) -> dict:
    """Keep the line only when every met or not_met quote is in the cited note."""
    if finding.get("error"):
        return {"action": "retry", "error": str(finding["error"])}
    policy = item["policy"]
    by_id = {}
    for row in finding.get("criteria") or []:
        if isinstance(row, dict) and row.get("criterion_id"):
            by_id[str(row["criterion_id"])] = row
    checked = []
    for criterion in policy["criteria"]:
        row = by_id.get(criterion["criterion_id"])
        if row is None:
            return {"action": "retry", "error": "A criterion was not judged."}
        status = row.get("status")
        if status not in {"met", "not_met", "not_documented"}:
            return {"action": "retry", "error": "A criterion status is not valid."}
        quote = str(row.get("quote") or "").strip() or None
        document_id = str(row.get("document_id") or "").strip() or None
        if status in {"met", "not_met"} and not quote_in_note(quote, document_id, notes):
            return {"action": "retry", "error": "A quote is not in the cited note."}
        if status == "not_documented":
            quote = None
            document_id = None
        checked.append(
            {
                "criterion_id": criterion["criterion_id"],
                "status": status,
                "quote": quote,
                "document_id": document_id,
                "label": _label(criterion),
                "text": criterion.get("text") or _label(criterion),
            }
        )
    statuses = [row["status"] for row in checked]
    if policy["op"] == "any_of":
        if any(status == "met" for status in statuses):
            line_status = "meets"
        elif statuses and all(status == "not_met" for status in statuses):
            line_status = "does_not_meet"
        else:
            line_status = "needs_info"
    elif any(status == "not_met" for status in statuses):
        line_status = "does_not_meet"
    elif statuses and all(status == "met" for status in statuses):
        line_status = "meets"
    else:
        line_status = "needs_info"
    line_no = item["line_no"]
    cpt = item["cpt_code"]
    policy_id = policy["policy_id"]
    reasons = []
    missing = []
    if line_status == "meets":
        met = [row["criterion_id"] for row in checked if row["status"] == "met"]
        reasons.append(f"Line {line_no}: {cpt} meets {policy_id} ({', '.join(met)}).")
    elif line_status == "does_not_meet":
        reasons.append(f"Line {line_no}: {cpt} does not meet {policy_id}.")
    else:
        for row in checked:
            if row["status"] != "not_documented":
                continue
            reasons.append(f"Line {line_no}: {row['label']} not documented ({row['criterion_id']}).")
            missing.append(f"Line {line_no} ({cpt}): {row['text']} ({row['criterion_id']})")
    public_criteria = [
        {
            "criterion_id": row["criterion_id"],
            "status": row["status"],
            "quote": row["quote"],
            "document_id": row["document_id"],
        }
        for row in checked
    ]
    return {
        "action": "keep",
        "line": _public(line_no, cpt, policy_id, line_status, public_criteria),
        "reasons": reasons,
        "missing": missing,
        "confidence": 0.8,
    }


def _evidence(lines: list[dict]) -> list[str]:
    found = []
    for line in lines:
        for item in (line.get("line") or {}).get("criteria") or []:
            for key in ("criterion_id", "document_id"):
                value = item.get(key)
                if value and value not in found:
                    found.append(str(value))
    return found


def error_result(message: str, flags: list[str]) -> dict:
    return {
        "agent": "medical_necessity",
        "verdict": None,
        "confidence": 0,
        "reasons": [],
        "evidence": [],
        "error": message,
        "details": {"lines": [], "missing_info": [], "review_flags": flags, "issues": []},
    }


def rollup(decisions: list[dict], flags: list[str]) -> dict:
    lines = [item["line"] for item in decisions]
    statuses = [line.get("status") for line in lines]
    if any(status == "needs_info" for status in statuses):
        verdict = "NEEDS_INFO"
    elif any(status == "does_not_meet" for status in statuses):
        verdict = "NOT_NECESSARY"
    else:
        verdict = "NECESSARY"
    reasons = []
    missing = []
    for item in decisions:
        for reason in item.get("reasons") or []:
            if reason not in reasons:
                reasons.append(reason)
        if verdict == "NEEDS_INFO":
            for message in item.get("missing") or []:
                if message not in missing:
                    missing.append(message)
    issues = [
        {
            "field_path": f"lines[{line['line_no']}].medical_record",
            "issue_code": "MEDICAL_RECORD",
            "message": message,
        }
        for line, message in (
            (item["line"], message)
            for item in decisions
            for message in (item.get("missing") or [])
        )
    ] if verdict == "NEEDS_INFO" else []
    confidence = min((float(item.get("confidence") or 0) for item in decisions), default=0)
    return {
        "agent": "medical_necessity",
        "verdict": verdict,
        "confidence": confidence,
        "reasons": reasons,
        "evidence": _evidence(decisions),
        "error": None,
        "details": {"lines": lines, "missing_info": missing, "review_flags": flags, "issues": issues},
    }
