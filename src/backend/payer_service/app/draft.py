"""Patch one field of a claim draft. Line numbers follow line_no, not list position."""

from __future__ import annotations

import re

from contracts.models import ClaimDraft

from payer_service.app.errors import FieldRejected

_LINE = re.compile(r"^lines\[(\d+)\]\.(.+)$")
_DX = re.compile(r"^diagnosis_codes\[(\d+)\]$")


def _require_member(data: dict) -> dict:
    if not data.get("member"):
        raise FieldRejected("This claim has no member block to update.")
    return data["member"]


def value_at(draft: ClaimDraft, field_path: str):
    data = draft.model_dump(mode="json")
    line_match = _LINE.match(field_path)
    if line_match:
        line_no = int(line_match.group(1))
        name = line_match.group(2)
        for line in data["lines"]:
            if line["line_no"] == line_no:
                return line.get(name)
        return None
    dx_match = _DX.match(field_path)
    if dx_match:
        index = int(dx_match.group(1)) - 1
        codes = data.get("diagnosis_codes") or []
        if 0 <= index < len(codes):
            return codes[index]
        return None
    if field_path.startswith("member."):
        member = data.get("member") or {}
        return member.get(field_path.split(".", 1)[1])
    if field_path.startswith("billing_provider."):
        billing = data.get("billing_provider") or {}
        return billing.get(field_path.split(".", 1)[1])
    return data.get(field_path)


def patch_draft(draft: ClaimDraft, field_path: str, value) -> ClaimDraft:
    data = draft.model_dump(mode="json")
    line_match = _LINE.match(field_path)
    if line_match:
        line_no = int(line_match.group(1))
        name = line_match.group(2)
        for line in data["lines"]:
            if line["line_no"] == line_no:
                line[name] = value
                break
        else:
            raise FieldRejected(f"Line {line_no} is not on this claim.")
    elif (dx_match := _DX.match(field_path)):
        index = int(dx_match.group(1)) - 1
        codes = list(data.get("diagnosis_codes") or [])
        if index < 0 or index >= len(codes):
            raise FieldRejected("That diagnosis is not on this claim.")
        codes[index] = value
        data["diagnosis_codes"] = codes
    elif field_path.startswith("member."):
        _require_member(data)[field_path.split(".", 1)[1]] = value
    elif field_path.startswith("billing_provider."):
        if not data.get("billing_provider"):
            raise FieldRejected("This claim has no billing provider to update.")
        data["billing_provider"][field_path.split(".", 1)[1]] = value
    elif field_path in {
        "group_number",
        "rendering_npi",
        "place_of_service",
        "service_from",
        "service_to",
        "total_billed",
        "diagnosis_codes",
    }:
        data[field_path] = value
    else:
        raise FieldRejected(f"Field {field_path} cannot be changed through an answer.")
    return ClaimDraft.model_validate(data)
