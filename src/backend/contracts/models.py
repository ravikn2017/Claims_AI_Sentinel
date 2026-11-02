"""Pydantic models for claim.submitted and the three payer outbound events.

Money is a decimal string. Dates are ISO 8601. Timestamps are UTC.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


def _money(value: object) -> Decimal:
    if isinstance(value, float):
        raise ValueError("money must be a decimal string")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("money must be a decimal string")


class Submitter(BaseModel):
    type: Literal["provider", "member"]
    id: str = Field(min_length=1)


class MemberBlock(BaseModel):
    member_id: str = Field(min_length=1)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    dob: date


class BillingProvider(BaseModel):
    npi: str = Field(min_length=1)
    name: str = Field(min_length=1)


class ClaimLine(BaseModel):
    line_no: int = Field(ge=1)
    cpt_code: str = Field(min_length=1)
    modifiers: list[str] = Field(default_factory=list)
    units: int
    billed_amount: Decimal
    service_date: date
    diagnosis_pointers: list[int] = Field(min_length=1)
    prior_auth_number: str | None = None

    @field_validator("billed_amount", mode="before")
    @classmethod
    def parse_amount(cls, value: object) -> Decimal:
        return _money(value)


class ProfessionalClaim(BaseModel):
    """Shape the portal accepts. Business rules are not applied here."""

    claim_type: Literal["professional"]
    member: MemberBlock
    group_number: str | None = None
    billing_provider: BillingProvider
    rendering_npi: str = Field(min_length=1)
    place_of_service: str = Field(min_length=1)
    service_from: date
    service_to: date
    diagnosis_codes: list[str] = Field(min_length=1)
    lines: list[ClaimLine] = Field(min_length=1)
    total_billed: Decimal

    @field_validator("total_billed", mode="before")
    @classmethod
    def parse_total(cls, value: object) -> Decimal:
        return _money(value)


class ClaimDraft(BaseModel):
    """Working copy. Extraction may leave fields empty; intake fills them."""

    claim_type: Literal["professional"] = "professional"
    member: MemberBlock | None = None
    group_number: str | None = None
    billing_provider: BillingProvider | None = None
    rendering_npi: str | None = None
    place_of_service: str | None = None
    service_from: date | None = None
    service_to: date | None = None
    diagnosis_codes: list[str] = Field(default_factory=list)
    lines: list[ClaimLine] = Field(default_factory=list)
    total_billed: Decimal | None = None

    @field_validator("total_billed", mode="before")
    @classmethod
    def parse_total(cls, value: object) -> Decimal | None:
        if value is None or value == "":
            return None
        return _money(value)

    @classmethod
    def from_professional(cls, claim: ProfessionalClaim) -> "ClaimDraft":
        return cls.model_validate(claim.model_dump(mode="json"))


class DocumentRef(BaseModel):
    document_id: str
    doc_type: str
    content_type: str
    storage_uri: str
    sha256: str


class ClaimSubmitted(BaseModel):
    message_type: Literal["claim.submitted"] = "claim.submitted"
    schema_version: str
    message_id: UUID
    submission_id: str
    submitted_at: datetime
    channel: Literal["portal", "email", "api"]
    submitter: Submitter
    extraction_required: bool
    claim: ClaimDraft | None = None
    documents: list[DocumentRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def claim_matches_extraction_flag(self) -> "ClaimSubmitted":
        major = self.schema_version.split(".", 1)[0]
        if major != "1":
            raise ValueError(f"unsupported schema_version {self.schema_version}")
        if not self.extraction_required and self.claim is None:
            raise ValueError("claim is required when extraction_required is false")
        return self


class SubmissionRequest(BaseModel):
    submission_id: str | None = None
    submitter_type: Literal["provider", "member"] = "provider"
    submitter_id: str = Field(min_length=1)
    claim: ProfessionalClaim


class ReadyForAdjudication(BaseModel):
    message_type: Literal["claim.ready_for_adjudication"] = "claim.ready_for_adjudication"
    schema_version: Literal["1.1"] = "1.1"
    message_id: UUID
    claim_id: str
    submission_id: str
    validated_at: datetime
    flags: list[str] = Field(default_factory=list)
    adjudication_attempt: int = Field(ge=1)


class IssuePayload(BaseModel):
    issue_id: int | None = None
    field_path: str
    issue_code: str
    message: str


class InfoRequested(BaseModel):
    message_type: Literal["claim.info_requested"] = "claim.info_requested"
    schema_version: Literal["1.0"] = "1.0"
    message_id: UUID
    claim_id: str
    submission_id: str
    channel: str
    submitter: Submitter
    respond_by: datetime
    issues: list[IssuePayload]


class RejectedEvent(BaseModel):
    message_type: Literal["claim.rejected"] = "claim.rejected"
    schema_version: Literal["1.0"] = "1.0"
    message_id: UUID
    claim_id: str
    submission_id: str
    issues: list[IssuePayload]
