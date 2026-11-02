"""Business validation. Every rule runs. A missing input skips that rule.

REJECT beats MISSING_INFO. FLAG never blocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from contracts.models import ClaimDraft
from contracts.npi import npi_is_valid

TIMELY_FILING_DAYS = 365


@dataclass
class Issue:
    field_path: str
    issue_code: str
    severity: str
    message: str


@dataclass
class PolicyRow:
    policy_id: str
    member_id: str
    plan_code: str
    group_number: str | None
    effective_date: date
    termination_date: date | None
    status: str


@dataclass
class MemberRow:
    member_id: str
    first_name: str
    last_name: str
    dob: date


@dataclass
class ProviderRow:
    provider_id: str
    npi: str
    name: str
    network_status: str | None
    quality_rating: int | None
    city: str | None
    state: str | None


@dataclass
class ClaimSignature:
    claim_id: str
    member_id: str | None
    billing_npi: str | None
    service_from: date | None
    service_to: date | None
    lines: tuple[tuple[str, int, str, date], ...]


@dataclass
class Reference:
    members: dict[str, MemberRow] = field(default_factory=dict)
    policies: list[PolicyRow] = field(default_factory=list)
    providers_by_npi: dict[str, ProviderRow] = field(default_factory=dict)
    cpt_codes: set[str] = field(default_factory=set)
    icd10: dict[str, bool] = field(default_factory=dict)
    existing: list[ClaimSignature] = field(default_factory=list)


@dataclass
class Outcome:
    status: str
    issues: list[Issue]
    flags: list[str]
    member: MemberRow | None
    policy: PolicyRow | None
    provider: ProviderRow | None


def _decide(issues: list[Issue]) -> str:
    severities = {issue.severity for issue in issues}
    if "REJECT" in severities:
        return "REJECTED"
    if "MISSING_INFO" in severities:
        return "PENDING_INFO"
    return "VALIDATED"


def _line_path(line_no: int, name: str) -> str:
    return f"lines[{line_no}].{name}"


def _covers(policy: PolicyRow, service_from: date, service_to: date) -> bool:
    if policy.status != "active":
        return False
    if policy.effective_date > service_from:
        return False
    if policy.termination_date is not None and policy.termination_date < service_to:
        return False
    return True


def signature_of(claim_id: str, draft: ClaimDraft) -> ClaimSignature | None:
    current = _signature(draft)
    if current is None:
        return None
    member_id, billing_npi, service_from, service_to, lines = current
    return ClaimSignature(claim_id, member_id, billing_npi, service_from, service_to, lines)


def _signature(draft: ClaimDraft) -> tuple | None:
    member_id = draft.member.member_id if draft.member else None
    billing_npi = draft.billing_provider.npi if draft.billing_provider else None
    if not member_id or not billing_npi or draft.service_from is None or draft.service_to is None:
        return None
    if not draft.lines:
        return None
    lines = tuple(
        sorted(
            (
                line.cpt_code,
                line.units,
                format(line.billed_amount, "f"),
                line.service_date,
            )
            for line in draft.lines
        )
    )
    return (member_id, billing_npi, draft.service_from, draft.service_to, lines)


def validate(
    draft: ClaimDraft,
    reference: Reference,
    *,
    unconfirmed: list[tuple[str, str]] | None = None,
    exclude_claim_id: str | None = None,
    today: date | None = None,
    timely_days: int = TIMELY_FILING_DAYS,
) -> Outcome:
    today = today or date.today()
    issues: list[Issue] = []
    member: MemberRow | None = None
    policy: PolicyRow | None = None
    provider: ProviderRow | None = None

    if draft.member is None or not draft.member.member_id:
        issues.append(Issue("member.member_id", "MISSING_FIELD", "MISSING_INFO", "Member ID is required."))
    if draft.member is None or not draft.member.first_name:
        issues.append(Issue("member.first_name", "MISSING_FIELD", "MISSING_INFO", "Member first name is required."))
    if draft.member is None or not draft.member.last_name:
        issues.append(Issue("member.last_name", "MISSING_FIELD", "MISSING_INFO", "Member last name is required."))
    if draft.member is None or draft.member.dob is None:
        issues.append(Issue("member.dob", "MISSING_FIELD", "MISSING_INFO", "Member date of birth is required."))
    if draft.billing_provider is None or not draft.billing_provider.npi:
        issues.append(Issue("billing_provider.npi", "MISSING_FIELD", "MISSING_INFO", "Billing provider NPI is required."))
    if draft.service_from is None:
        issues.append(Issue("service_from", "MISSING_FIELD", "MISSING_INFO", "Service start date is required."))
    if draft.service_to is None:
        issues.append(Issue("service_to", "MISSING_FIELD", "MISSING_INFO", "Service end date is required."))
    if not draft.diagnosis_codes:
        issues.append(Issue("diagnosis_codes", "MISSING_FIELD", "MISSING_INFO", "At least one diagnosis is required."))
    if not draft.lines:
        issues.append(Issue("lines", "MISSING_FIELD", "MISSING_INFO", "At least one claim line is required."))
    if draft.total_billed is None:
        issues.append(Issue("total_billed", "MISSING_FIELD", "MISSING_INFO", "Total billed amount is required."))

    for line in draft.lines:
        if not line.cpt_code:
            issues.append(Issue(_line_path(line.line_no, "cpt_code"), "MISSING_FIELD", "MISSING_INFO", f"Line {line.line_no} needs a procedure code."))
        if line.units is None:
            issues.append(Issue(_line_path(line.line_no, "units"), "MISSING_FIELD", "MISSING_INFO", f"Line {line.line_no} needs units."))
        if line.billed_amount is None:
            issues.append(Issue(_line_path(line.line_no, "billed_amount"), "MISSING_FIELD", "MISSING_INFO", f"Line {line.line_no} needs an amount."))
        if not line.diagnosis_pointers:
            issues.append(Issue(_line_path(line.line_no, "diagnosis_pointers"), "MISSING_FIELD", "MISSING_INFO", f"Line {line.line_no} needs a diagnosis pointer."))

    for path, message in unconfirmed or []:
        issues.append(Issue(path, "UNCONFIRMED_FIELD", "MISSING_INFO", message))

    if draft.member and draft.member.member_id and draft.member.first_name and draft.member.last_name and draft.member.dob:
        found = reference.members.get(draft.member.member_id)
        if found is None or found.first_name.casefold() != draft.member.first_name.casefold() or found.last_name.casefold() != draft.member.last_name.casefold() or found.dob != draft.member.dob:
            issues.append(
                Issue(
                    "member.member_id",
                    "MEMBER_NOT_MATCHED",
                    "MISSING_INFO",
                    "Member ID was not found, or the name and date of birth do not match.",
                )
            )
        else:
            member = found

    if member is not None and draft.service_from is not None and draft.service_to is not None:
        covering = [
            row
            for row in reference.policies
            if row.member_id == member.member_id and _covers(row, draft.service_from, draft.service_to)
        ]
        group = (draft.group_number or "").strip()
        if not covering:
            issues.append(
                Issue(
                    "service_from",
                    "NO_ACTIVE_COVERAGE",
                    "REJECT",
                    "No policy is active for this member across the service dates.",
                )
            )
        elif len(covering) > 1:
            picked = [row for row in covering if group and row.group_number == group]
            if len(picked) == 1:
                policy = picked[0]
            else:
                issues.append(
                    Issue(
                        "group_number",
                        "POLICY_AMBIGUOUS",
                        "MISSING_INFO",
                        "More than one policy is active. Provide the group number for the plan to use.",
                    )
                )
        else:
            policy = covering[0]
            if group and policy.group_number != group:
                issues.append(
                    Issue(
                        "group_number",
                        "GROUP_MISMATCH",
                        "FLAG",
                        "Group number does not match the active policy.",
                    )
                )

    billing_npi = draft.billing_provider.npi if draft.billing_provider else None
    if billing_npi:
        if not npi_is_valid(billing_npi):
            issues.append(Issue("billing_provider.npi", "INVALID_NPI", "MISSING_INFO", "Billing NPI fails its check digit."))
        else:
            provider = reference.providers_by_npi.get(billing_npi)
            if provider is None:
                issues.append(
                    Issue(
                        "billing_provider.npi",
                        "PROVIDER_NOT_ON_FILE",
                        "REJECT",
                        "Billing NPI is not on file.",
                    )
                )
    if draft.rendering_npi:
        if not npi_is_valid(draft.rendering_npi):
            issues.append(Issue("rendering_npi", "INVALID_NPI", "MISSING_INFO", "Rendering NPI fails its check digit."))

    for code_index, code in enumerate(draft.diagnosis_codes, start=1):
        billable = reference.icd10.get(code)
        if billable is None or not billable:
            issues.append(
                Issue(
                    f"diagnosis_codes[{code_index}]",
                    "INVALID_CODE",
                    "MISSING_INFO",
                    f"Diagnosis {code} is not a billable ICD-10 code.",
                )
            )
    if len(draft.diagnosis_codes) > 12:
        issues.append(
            Issue(
                "diagnosis_codes",
                "INVALID_POINTER",
                "MISSING_INFO",
                "A professional claim can have at most 12 diagnoses.",
            )
        )

    for line in draft.lines:
        if line.cpt_code and line.cpt_code not in reference.cpt_codes:
            issues.append(
                Issue(
                    _line_path(line.line_no, "cpt_code"),
                    "INVALID_CODE",
                    "MISSING_INFO",
                    f"Procedure code {line.cpt_code} is not a valid CPT code.",
                )
            )
        if line.units is not None and line.units < 1:
            issues.append(Issue(_line_path(line.line_no, "units"), "AMOUNT_MISMATCH", "MISSING_INFO", f"Line {line.line_no} units must be at least 1."))
        if line.billed_amount is not None and line.billed_amount <= 0:
            issues.append(Issue(_line_path(line.line_no, "billed_amount"), "AMOUNT_MISMATCH", "MISSING_INFO", f"Line {line.line_no} amount must be greater than zero."))
        if len(line.diagnosis_pointers) > 4:
            issues.append(Issue(_line_path(line.line_no, "diagnosis_pointers"), "INVALID_POINTER", "MISSING_INFO", f"Line {line.line_no} has more than 4 diagnosis pointers."))
        for pointer in line.diagnosis_pointers:
            if pointer < 1 or pointer > len(draft.diagnosis_codes):
                issues.append(
                    Issue(
                        _line_path(line.line_no, "diagnosis_pointers"),
                        "INVALID_POINTER",
                        "MISSING_INFO",
                        f"Line {line.line_no} points at a diagnosis that is not on the claim.",
                    )
                )
                break

    amounts_present = draft.total_billed is not None and draft.lines and all(line.billed_amount is not None for line in draft.lines)
    if amounts_present:
        total = sum((line.billed_amount for line in draft.lines), Decimal("0"))
        if total != draft.total_billed or draft.total_billed <= 0:
            issues.append(
                Issue(
                    "total_billed",
                    "AMOUNT_MISMATCH",
                    "MISSING_INFO",
                    "Line amounts must be greater than zero and sum to the total billed.",
                )
            )

    if draft.service_from is not None and draft.service_to is not None:
        if draft.service_from > draft.service_to or draft.service_from > today or draft.service_to > today:
            issues.append(Issue("service_from", "INVALID_DATE", "MISSING_INFO", "Service dates are out of order or in the future."))
        for line in draft.lines:
            if line.service_date < draft.service_from or line.service_date > draft.service_to or line.service_date > today:
                issues.append(
                    Issue(
                        _line_path(line.line_no, "service_date"),
                        "INVALID_DATE",
                        "MISSING_INFO",
                        f"Line {line.line_no} date is outside the claim dates or in the future.",
                    )
                )
        if (today - draft.service_to).days > timely_days:
            issues.append(
                Issue(
                    "service_to",
                    "TIMELY_FILING",
                    "REJECT",
                    f"The claim was submitted more than {timely_days} days after the service date.",
                )
            )

    current = _signature(draft)
    if current is not None:
        for other in reference.existing:
            if other.claim_id == exclude_claim_id:
                continue
            other_key = (
                other.member_id,
                other.billing_npi,
                other.service_from,
                other.service_to,
                other.lines,
            )
            if other_key == current:
                issues.append(
                    Issue(
                        "lines",
                        "POSSIBLE_DUPLICATE",
                        "FLAG",
                        "Another claim has the same member, provider, dates, and lines.",
                    )
                )
                break

    flags = [issue.issue_code for issue in issues if issue.severity == "FLAG"]
    return Outcome(_decide(issues), issues, flags, member, policy, provider)
