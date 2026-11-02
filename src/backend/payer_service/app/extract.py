"""Document extraction. A deterministic text reader fills the draft.

The ground-check keeps a field only when its quote is in the document and the
value passes a format check. A later model can replace `read_fields` without
changing validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pypdf import PdfReader

from contracts.models import ClaimDraft, ClaimLine
from contracts.npi import npi_is_valid

EXTRACTOR_VERSION = "text-v1"

_LINE_KEY = re.compile(r"^line\.(\d+)\.([a-z_]+)$")


@dataclass
class FieldRead:
    path: str
    value: object
    evidence: str
    page: int
    confirmed: bool


@dataclass
class Extraction:
    doc_class: str
    draft: ClaimDraft
    fields: list[FieldRead]
    unconfirmed: list[tuple[str, str]]


def read_pdf_text(path: Path) -> list[tuple[int, str]]:
    reader = PdfReader(str(path))
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append((index, page.extract_text() or ""))
    if not any(text.strip() for _, text in pages):
        raw = path.read_text(encoding="utf-8", errors="replace")
        return [(1, raw)]
    return pages


def classify(text: str) -> str:
    lowered = text.lower()
    if "itemized bill" in lowered or "itemised bill" in lowered:
        return "itemized_bill"
    if "medical record" in lowered or "progress note" in lowered:
        return "medical_record"
    if "cms-1500" in lowered or "claim form" in lowered or "member_id:" in lowered:
        return "cms1500"
    return "other"


def _normalise_icd(value: str) -> str:
    compact = value.strip().upper().replace(" ", "")
    if "." in compact:
        return compact
    if len(compact) > 3:
        return compact[:3] + "." + compact[3:]
    return compact


def _format_ok(path: str, value: object, *, cpt_codes: set[str], icd10: dict[str, bool]) -> bool:
    if path in {"billing_provider.npi", "rendering_npi"}:
        return isinstance(value, str) and npi_is_valid(value)
    if path.endswith("cpt_code"):
        return isinstance(value, str) and value in cpt_codes
    if path.startswith("diagnosis_codes"):
        return isinstance(value, str) and icd10.get(value) is True
    if path in {"service_from", "service_to", "member.dob"} or path.endswith("service_date"):
        return isinstance(value, date)
    if path in {"total_billed"} or path.endswith("billed_amount"):
        return isinstance(value, Decimal)
    if path.endswith("units"):
        return isinstance(value, int) and value >= 1
    return value not in (None, "")


def parse_lines(pages: list[tuple[int, str]]) -> list[tuple[str, str, str, int]]:
    """Return key, raw value, evidence line, page."""
    found: list[tuple[str, str, str, int]] = []
    for page, text in pages:
        for line in text.splitlines():
            stripped = line.strip()
            if ":" not in stripped:
                continue
            key, raw = stripped.split(":", 1)
            key = key.strip()
            raw = raw.strip()
            if not key or not raw:
                continue
            found.append((key, raw, stripped, page))
    return found


def _coerce(key: str, raw: str) -> tuple[str, object] | None:
    match = _LINE_KEY.match(key)
    if key == "member_id":
        return "member.member_id", raw
    if key == "first_name":
        return "member.first_name", raw
    if key == "last_name":
        return "member.last_name", raw
    if key == "dob":
        return "member.dob", date.fromisoformat(raw)
    if key == "group_number":
        return "group_number", raw
    if key == "billing_npi":
        digits = "".join(character for character in raw if character.isdigit())
        return "billing_provider.npi", digits
    if key == "billing_name":
        return "billing_provider.name", raw
    if key == "rendering_npi":
        digits = "".join(character for character in raw if character.isdigit())
        return "rendering_npi", digits
    if key == "place_of_service":
        return "place_of_service", raw
    if key in {"service_from", "service_to"}:
        return key, date.fromisoformat(raw)
    if key == "diagnosis_codes":
        return "diagnosis_codes", [_normalise_icd(part) for part in raw.split(",") if part.strip()]
    if key == "total_billed":
        return "total_billed", Decimal(raw)
    if match is None:
        return None
    line_no, name = match.group(1), match.group(2)
    path = f"lines[{line_no}].{name}"
    if name == "cpt_code":
        return path, raw.strip()
    if name == "units":
        return path, int(raw)
    if name == "billed_amount":
        return path, Decimal(raw)
    if name == "service_date":
        return path, date.fromisoformat(raw)
    if name == "diagnosis_pointers":
        return path, [int(part) for part in raw.split(",") if part.strip()]
    return None


def read_fields(
    pages: list[tuple[int, str]],
    *,
    cpt_codes: set[str],
    icd10: dict[str, bool],
) -> list[FieldRead]:
    text = "\n".join(page_text for _, page_text in pages)
    fields: list[FieldRead] = []
    for key, raw, evidence, page in parse_lines(pages):
        try:
            coerced = _coerce(key, raw)
        except (ValueError, InvalidOperation):
            coerced = None
        if coerced is None:
            continue
        path, value = coerced
        if path == "diagnosis_codes" and isinstance(value, list):
            for index, code in enumerate(value, start=1):
                code_path = f"diagnosis_codes[{index}]"
                confirmed = evidence in text and _format_ok(code_path, code, cpt_codes=cpt_codes, icd10=icd10)
                fields.append(FieldRead(code_path, code, evidence, page, confirmed))
            continue
        confirmed = evidence in text and _format_ok(path, value, cpt_codes=cpt_codes, icd10=icd10)
        fields.append(FieldRead(path, value, evidence, page, confirmed))
    return fields


def draft_from_fields(fields: list[FieldRead]) -> tuple[ClaimDraft, list[tuple[str, str]]]:
    data: dict = {"claim_type": "professional", "member": {}, "billing_provider": {}, "lines": {}}
    unconfirmed: list[tuple[str, str]] = []
    diagnoses: list[str | None] = []
    for item in fields:
        if not item.confirmed:
            unconfirmed.append((item.path, f"Could not confirm {item.path} from the document."))
        if item.path.startswith("member."):
            data["member"][item.path.split(".", 1)[1]] = item.value
        elif item.path.startswith("billing_provider."):
            data["billing_provider"][item.path.split(".", 1)[1]] = item.value
        elif item.path.startswith("diagnosis_codes["):
            index = int(item.path[item.path.index("[") + 1 : item.path.index("]")])
            while len(diagnoses) < index:
                diagnoses.append(None)
            diagnoses[index - 1] = item.value if isinstance(item.value, str) else None
        elif item.path.startswith("lines["):
            line_no = int(item.path[item.path.index("[") + 1 : item.path.index("]")])
            name = item.path.split(".", 1)[1]
            data["lines"].setdefault(line_no, {"line_no": line_no, "modifiers": []})
            data["lines"][line_no][name] = item.value
        else:
            data[item.path] = item.value
    member = data["member"]
    billing = data["billing_provider"]
    lines = []
    for line_no in sorted(data["lines"]):
        raw_line = data["lines"][line_no]
        if not {"cpt_code", "units", "billed_amount", "service_date", "diagnosis_pointers"} <= raw_line.keys():
            continue
        lines.append(ClaimLine.model_validate(raw_line))
    draft = ClaimDraft(
        member=member if {"member_id", "first_name", "last_name", "dob"} <= member.keys() else None,
        group_number=data.get("group_number"),
        billing_provider=billing if {"npi", "name"} <= billing.keys() else None,
        rendering_npi=data.get("rendering_npi"),
        place_of_service=data.get("place_of_service"),
        service_from=data.get("service_from"),
        service_to=data.get("service_to"),
        diagnosis_codes=[code for code in diagnoses if code],
        lines=lines,
        total_billed=data.get("total_billed"),
    )
    return draft, unconfirmed


def extract_document(
    path: Path,
    *,
    cpt_codes: set[str],
    icd10: dict[str, bool],
    reader=read_fields,
) -> Extraction:
    pages = read_pdf_text(path)
    text = "\n".join(page for _, page in pages)
    doc_class = classify(text)
    if doc_class not in {"cms1500", "itemized_bill"}:
        return Extraction(doc_class, ClaimDraft(), [], [])
    fields = reader(pages, cpt_codes=cpt_codes, icd10=icd10)
    draft, unconfirmed = draft_from_fields(fields)
    return Extraction(doc_class, draft, fields, unconfirmed)


def merge_drafts(drafts: list[ClaimDraft]) -> ClaimDraft:
    merged = ClaimDraft()
    for draft in drafts:
        if merged.member is None and draft.member is not None:
            merged.member = draft.member
        if merged.group_number is None:
            merged.group_number = draft.group_number
        if merged.billing_provider is None and draft.billing_provider is not None:
            merged.billing_provider = draft.billing_provider
        if merged.rendering_npi is None:
            merged.rendering_npi = draft.rendering_npi
        if merged.place_of_service is None:
            merged.place_of_service = draft.place_of_service
        if merged.service_from is None:
            merged.service_from = draft.service_from
        if merged.service_to is None:
            merged.service_to = draft.service_to
        if not merged.diagnosis_codes and draft.diagnosis_codes:
            merged.diagnosis_codes = draft.diagnosis_codes
        if not merged.lines and draft.lines:
            merged.lines = draft.lines
        if merged.total_billed is None:
            merged.total_billed = draft.total_billed
    return merged


def field_result(item: FieldRead) -> dict:
    value = item.value
    if isinstance(value, date | datetime):
        value = value.isoformat()
    elif isinstance(value, Decimal):
        value = format(value, "f")
    return {
        "path": item.path,
        "value": value,
        "evidence": item.evidence,
        "page": item.page,
        "confirmed": item.confirmed,
    }
