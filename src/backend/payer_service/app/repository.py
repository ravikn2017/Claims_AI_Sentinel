"""The only writer of the claims schema, plus the audited reads."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from contracts.models import (
    ClaimDraft,
    ClaimSubmitted,
    InfoRequested,
    IssuePayload,
    ReadyForAdjudication,
    RejectedEvent,
    Submitter,
)
from payer_service.app.draft import patch_draft, value_at
from payer_service.app.errors import Conflict, DuplicateClaim, FieldRejected, NotAllowed
from payer_service.app.rules import (
    Issue,
    MemberRow,
    Outcome,
    PolicyRow,
    ProviderRow,
    Reference,
    signature_of,
    validate,
)

ADJUDICATOR_TRANSITIONS = {
    ("VALIDATED", "IN_ADJUDICATION"),
    ("IN_ADJUDICATION", "PENDING_REVIEW"),
    ("IN_ADJUDICATION", "DENIED"),
    ("IN_ADJUDICATION", "PENDING_INFO"),
    ("PENDING_REVIEW", "APPROVED"),
    ("PENDING_REVIEW", "DENIED"),
}
OPERATOR_TRANSITIONS = ADJUDICATOR_TRANSITIONS | {("PENDING_INFO", "REJECTED")}


def pending_info_days() -> int:
    return int(os.environ.get("PENDING_INFO_DAYS", "14"))


def timely_filing_days() -> int:
    return int(os.environ.get("TIMELY_FILING_DAYS", "365"))


def _dumps(value) -> str:
    return json.dumps(value, default=_json_default)


def _json_default(value):
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(type(value))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_reference(conn: Connection, *, exclude_claim_id: str | None = None) -> Reference:
    reference = Reference()
    for row in conn.execute(
        text("SELECT member_id, first_name, last_name, dob FROM claims.member")
    ).mappings():
        reference.members[row["member_id"]] = MemberRow(
            row["member_id"], row["first_name"], row["last_name"], row["dob"]
        )
    for row in conn.execute(
        text(
            """
            SELECT policy_id, member_id, plan_code, group_number,
                   effective_date, termination_date, status
            FROM claims.policy
            """
        )
    ).mappings():
        reference.policies.append(
            PolicyRow(
                row["policy_id"],
                row["member_id"],
                row["plan_code"],
                row["group_number"],
                row["effective_date"],
                row["termination_date"],
                row["status"],
            )
        )
    for row in conn.execute(
        text(
            """
            SELECT provider_id, npi, name, network_status, quality_rating, city, state
            FROM claims.provider
            """
        )
    ).mappings():
        reference.providers_by_npi[row["npi"]] = ProviderRow(
            row["provider_id"],
            row["npi"],
            row["name"],
            row["network_status"],
            row["quality_rating"],
            row["city"],
            row["state"],
        )
    reference.cpt_codes = set(conn.execute(text("SELECT code FROM claims.ref_cpt WHERE active")).scalars())
    for row in conn.execute(text("SELECT code, billable FROM claims.ref_icd10")).mappings():
        reference.icd10[row["code"]] = bool(row["billable"])
    for row in conn.execute(text("SELECT claim_id, draft FROM claims.claim")).mappings():
        if row["claim_id"] == exclude_claim_id:
            continue
        draft = ClaimDraft.model_validate(row["draft"])
        signature = signature_of(row["claim_id"], draft)
        if signature is not None:
            reference.existing.append(signature)
    return reference


def claim_exists(conn: Connection, submission_id: str) -> bool:
    found = conn.execute(
        text("SELECT 1 FROM claims.claim WHERE submission_id = :submission_id"),
        {"submission_id": submission_id},
    ).first()
    return found is not None


def snapshot_of(outcome: Outcome, read_at: datetime) -> dict:
    def row(value) -> dict | None:
        if value is None:
            return None
        if isinstance(value, MemberRow):
            return {
                "member_id": value.member_id,
                "first_name": value.first_name,
                "last_name": value.last_name,
                "dob": value.dob.isoformat(),
            }
        if isinstance(value, PolicyRow):
            return {
                "policy_id": value.policy_id,
                "member_id": value.member_id,
                "plan_code": value.plan_code,
                "group_number": value.group_number,
                "effective_date": value.effective_date.isoformat(),
                "termination_date": value.termination_date.isoformat() if value.termination_date else None,
                "status": value.status,
            }
        if isinstance(value, ProviderRow):
            return {
                "provider_id": value.provider_id,
                "npi": value.npi,
                "name": value.name,
                "network_status": value.network_status,
                "quality_rating": value.quality_rating,
                "city": value.city,
                "state": value.state,
            }
        return None

    return {
        "read_at": read_at.isoformat(),
        "member": row(outcome.member),
        "policy": row(outcome.policy),
        "provider": row(outcome.provider),
    }


def _insert_issues(conn: Connection, claim_id: str, issues: list[Issue]) -> list[IssuePayload]:
    stored: list[IssuePayload] = []
    for issue in issues:
        if issue.severity == "FLAG":
            continue
        issue_id = conn.execute(
            text(
                """
                INSERT INTO claims.claim_issue (
                    claim_id, field_path, issue_code, severity, message, status
                )
                VALUES (
                    :claim_id, :field_path, :issue_code, :severity, :message, 'open'
                )
                RETURNING issue_id
                """
            ),
            {
                "claim_id": claim_id,
                "field_path": issue.field_path,
                "issue_code": issue.issue_code,
                "severity": issue.severity,
                "message": issue.message,
            },
        ).scalar_one()
        stored.append(
            IssuePayload(
                issue_id=int(issue_id),
                field_path=issue.field_path,
                issue_code=issue.issue_code,
                message=issue.message,
            )
        )
    return stored


def _history(
    conn: Connection,
    claim_id: str,
    from_status: str | None,
    to_status: str,
    actor: str,
    reason_code: str,
    reason: str,
    details: dict,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO claims.claim_status_history (
                claim_id, from_status, to_status, actor, reason_code, reason, details
            )
            VALUES (
                :claim_id, :from_status, :to_status, :actor, :reason_code, :reason,
                CAST(:details AS jsonb)
            )
            """
        ),
        {
            "claim_id": claim_id,
            "from_status": from_status,
            "to_status": to_status,
            "actor": actor,
            "reason_code": reason_code,
            "reason": reason,
            "details": _dumps(details),
        },
    )


def _outbox(conn: Connection, routing_key: str, claim_id: str, payload: dict) -> None:
    conn.execute(
        text(
            """
            INSERT INTO claims.outbox (message_id, routing_key, claim_id, payload)
            VALUES (:message_id, :routing_key, :claim_id, CAST(:payload AS jsonb))
            """
        ),
        {
            "message_id": payload["message_id"],
            "routing_key": routing_key,
            "claim_id": claim_id,
            "payload": _dumps(payload),
        },
    )


def _attempt(conn: Connection, claim_id: str) -> int:
    count = conn.execute(
        text(
            """
            SELECT count(*) FROM claims.claim_status_history
            WHERE claim_id = :claim_id AND to_status = 'VALIDATED'
            """
        ),
        {"claim_id": claim_id},
    ).scalar_one()
    return int(count)


def _emit(conn: Connection, message: ClaimSubmitted, claim_id: str, outcome: Outcome, stored: list[IssuePayload], respond_by: datetime | None) -> None:
    now = _utc_now()
    if outcome.status == "VALIDATED":
        payload = ReadyForAdjudication(
            message_id=uuid4(),
            claim_id=claim_id,
            submission_id=message.submission_id,
            validated_at=now,
            flags=outcome.flags,
            adjudication_attempt=_attempt(conn, claim_id),
        )
        _outbox(conn, "claim.ready_for_adjudication", claim_id, payload.model_dump(mode="json"))
        return
    if outcome.status == "PENDING_INFO":
        asking = [issue for issue in stored if issue.issue_code != "INFO_TIMEOUT"]
        payload = InfoRequested(
            message_id=uuid4(),
            claim_id=claim_id,
            submission_id=message.submission_id,
            channel=message.channel,
            submitter=message.submitter,
            respond_by=respond_by or now,
            issues=[issue for issue in asking if _severity_of(outcome, issue) == "MISSING_INFO"],
        )
        _outbox(conn, "claim.info_requested", claim_id, payload.model_dump(mode="json"))
        return
    payload = RejectedEvent(
        message_id=uuid4(),
        claim_id=claim_id,
        submission_id=message.submission_id,
        issues=stored,
    )
    _outbox(conn, "claim.rejected", claim_id, payload.model_dump(mode="json"))


def _severity_of(outcome: Outcome, issue: IssuePayload) -> str:
    for item in outcome.issues:
        if item.field_path == issue.field_path and item.issue_code == issue.issue_code:
            return item.severity
    return "MISSING_INFO"


def _replace_lines(conn: Connection, claim_id: str, draft: ClaimDraft) -> None:
    conn.execute(text("DELETE FROM claims.claim_line WHERE claim_id = :claim_id"), {"claim_id": claim_id})
    for line in draft.lines:
        conn.execute(
            text(
                """
                INSERT INTO claims.claim_line (
                    claim_id, line_no, cpt_code, modifiers, units, billed_amount,
                    service_date, diagnosis_pointers, prior_auth_number
                )
                VALUES (
                    :claim_id, :line_no, :cpt_code,
                    ARRAY(SELECT jsonb_array_elements_text(CAST(:modifiers AS jsonb))),
                    :units, :billed_amount, :service_date,
                    ARRAY(SELECT jsonb_array_elements_text(CAST(:diagnosis_pointers AS jsonb))::int),
                    :prior_auth_number
                )
                """
            ),
            {
                "claim_id": claim_id,
                "line_no": line.line_no,
                "cpt_code": line.cpt_code,
                "modifiers": _dumps(line.modifiers),
                "units": line.units,
                "billed_amount": line.billed_amount,
                "service_date": line.service_date,
                "diagnosis_pointers": _dumps(line.diagnosis_pointers),
                "prior_auth_number": line.prior_auth_number,
            },
        )


def _new_claim_id() -> str:
    day = _utc_now().strftime("%Y%m%d")
    return f"CLM-{day}-{uuid4().hex[:6].upper()}"


def write_intake(
    conn: Connection,
    message: ClaimSubmitted,
    draft: ClaimDraft,
    outcome: Outcome,
    *,
    today: date | None = None,
) -> str:
    now = _utc_now()
    snap = snapshot_of(outcome, now)
    claim_id = _new_claim_id()
    validated = outcome.status == "VALIDATED"
    respond_by = now + timedelta(days=pending_info_days()) if outcome.status == "PENDING_INFO" else None
    inserted = conn.execute(
        text(
            """
            INSERT INTO claims.claim (
                claim_id, submission_id, member_id, policy_id, billing_provider_id,
                rendering_npi, place_of_service, diagnosis_codes, service_from, service_to,
                total_billed, status, draft, source_message, channel, submitter_type,
                submitter_id, flags, respond_by, reference_snapshot
            )
            VALUES (
                :claim_id, :submission_id, :member_id, :policy_id, :billing_provider_id,
                :rendering_npi, :place_of_service,
                CASE WHEN CAST(:diagnosis_codes AS jsonb) IS NULL THEN NULL
                     ELSE ARRAY(SELECT jsonb_array_elements_text(CAST(:diagnosis_codes AS jsonb)))
                END,
                :service_from, :service_to,
                :total_billed, :status, CAST(:draft AS jsonb), CAST(:source_message AS jsonb),
                :channel, :submitter_type, :submitter_id,
                ARRAY(SELECT jsonb_array_elements_text(CAST(:flags AS jsonb))),
                :respond_by,
                CAST(:reference_snapshot AS jsonb)
            )
            ON CONFLICT (submission_id) DO NOTHING
            RETURNING claim_id
            """
        ),
        {
            "claim_id": claim_id,
            "submission_id": message.submission_id,
            "member_id": outcome.member.member_id if validated and outcome.member else None,
            "policy_id": outcome.policy.policy_id if validated and outcome.policy else None,
            "billing_provider_id": outcome.provider.provider_id if validated and outcome.provider else None,
            "rendering_npi": draft.rendering_npi if validated else None,
            "place_of_service": draft.place_of_service if validated else None,
            "diagnosis_codes": _dumps(draft.diagnosis_codes) if validated else None,
            "service_from": draft.service_from if validated else None,
            "service_to": draft.service_to if validated else None,
            "total_billed": draft.total_billed if validated else None,
            "status": outcome.status,
            "draft": draft.model_dump_json(),
            "source_message": message.model_dump_json(),
            "channel": message.channel,
            "submitter_type": message.submitter.type,
            "submitter_id": message.submitter.id,
            "flags": _dumps(outcome.flags),
            "respond_by": respond_by,
            "reference_snapshot": _dumps(snap),
        },
    ).first()
    if inserted is None:
        raise DuplicateClaim(message.submission_id)
    claim_id = inserted[0]
    for document in message.documents:
        conn.execute(
            text(
                """
                INSERT INTO claims.claim_document (
                    document_id, claim_id, doc_type, storage_uri, sha256
                )
                VALUES (:document_id, :claim_id, :doc_type, :storage_uri, :sha256)
                """
            ),
            {
                "document_id": document.document_id,
                "claim_id": claim_id,
                "doc_type": document.doc_type,
                "storage_uri": document.storage_uri,
                "sha256": document.sha256,
            },
        )
    if validated:
        _replace_lines(conn, claim_id, draft)
    stored = _insert_issues(conn, claim_id, outcome.issues)
    details = {"reference_snapshot": snap}
    _history(conn, claim_id, None, "RECEIVED", "payer_service", "INTAKE", "Submission received", details)
    _history(
        conn,
        claim_id,
        "RECEIVED",
        outcome.status,
        "payer_service",
        outcome.status,
        "Validation finished",
        details,
    )
    _emit(conn, message, claim_id, outcome, stored, respond_by)
    return claim_id


def _lock_claim(conn: Connection, claim_id: str) -> dict:
    row = conn.execute(
        text("SELECT * FROM claims.claim WHERE claim_id = :claim_id FOR UPDATE"),
        {"claim_id": claim_id},
    ).mappings().first()
    if row is None:
        raise Conflict(None)
    return dict(row)


def _seen_idempotency(conn: Connection, claim_id: str, key: str) -> bool:
    found = conn.execute(
        text(
            """
            SELECT 1 FROM claims.claim_status_history
            WHERE claim_id = :claim_id AND details->>'idempotency_key' = :key
            """
        ),
        {"claim_id": claim_id, "key": key},
    ).first()
    return found is not None


def transition(
    conn: Connection,
    claim_id: str,
    from_status: str,
    to_status: str,
    actor: str,
    reason_code: str,
    reason: str,
    *,
    idempotency_key: str | None = None,
    details: dict | None = None,
) -> str:
    if idempotency_key and _seen_idempotency(conn, claim_id, idempotency_key):
        return "replayed"
    updated = conn.execute(
        text(
            """
            UPDATE claims.claim
            SET status = :to_status, version = version + 1
            WHERE claim_id = :claim_id AND status = :from_status
            """
        ),
        {"claim_id": claim_id, "from_status": from_status, "to_status": to_status},
    )
    if updated.rowcount == 0:
        current = conn.execute(
            text("SELECT status FROM claims.claim WHERE claim_id = :claim_id"),
            {"claim_id": claim_id},
        ).scalar()
        raise Conflict(current)
    payload = dict(details or {})
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    _history(conn, claim_id, from_status, to_status, actor, reason_code, reason, payload)
    return "applied"


def allowed_transition(actor: str, from_status: str, to_status: str) -> bool:
    pair = (from_status, to_status)
    if actor.startswith("adjudicator"):
        return pair in ADJUDICATOR_TRANSITIONS
    if actor.startswith("sweeper") or actor.startswith("ops"):
        return pair in OPERATOR_TRANSITIONS
    return False


def apply_transition(
    conn: Connection,
    claim_id: str,
    from_status: str,
    to_status: str,
    actor: str,
    reason_code: str,
    reason: str,
    idempotency_key: str,
    issues: list[dict] | None = None,
) -> str:
    if not reason_code:
        raise NotAllowed("reason_code is required")
    if not allowed_transition(actor, from_status, to_status):
        raise NotAllowed("Transition is not allowed for this caller")
    claim = _lock_claim(conn, claim_id)
    if _seen_idempotency(conn, claim_id, idempotency_key):
        return "replayed"
    if claim["status"] != from_status:
        raise Conflict(claim["status"])
    snap = claim["reference_snapshot"]
    result = transition(
        conn,
        claim_id,
        from_status,
        to_status,
        actor,
        reason_code,
        reason,
        idempotency_key=idempotency_key,
        details={"reference_snapshot": snap},
    )
    if result == "replayed":
        return result
    if to_status == "PENDING_INFO":
        respond_by = _utc_now() + timedelta(days=pending_info_days())
        conn.execute(
            text("UPDATE claims.claim SET respond_by = :respond_by WHERE claim_id = :claim_id"),
            {"respond_by": respond_by, "claim_id": claim_id},
        )
        created: list[IssuePayload] = []
        for issue in issues or []:
            issue_id = conn.execute(
                text(
                    """
                    INSERT INTO claims.claim_issue (
                        claim_id, field_path, issue_code, severity, message, status
                    )
                    VALUES (:claim_id, :field_path, :issue_code, 'MISSING_INFO', :message, 'open')
                    RETURNING issue_id
                    """
                ),
                {
                    "claim_id": claim_id,
                    "field_path": issue["field_path"],
                    "issue_code": issue["issue_code"],
                    "message": issue["message"],
                },
            ).scalar_one()
            created.append(
                IssuePayload(
                    issue_id=int(issue_id),
                    field_path=issue["field_path"],
                    issue_code=issue["issue_code"],
                    message=issue["message"],
                )
            )
        payload = InfoRequested(
            message_id=uuid4(),
            claim_id=claim_id,
            submission_id=claim["submission_id"],
            channel=claim["channel"],
            submitter=Submitter(type=claim["submitter_type"], id=claim["submitter_id"]),
            respond_by=respond_by,
            issues=created,
        )
        _outbox(conn, "claim.info_requested", claim_id, payload.model_dump(mode="json"))
    return result


def _message_from_claim(claim: dict) -> ClaimSubmitted:
    return ClaimSubmitted.model_validate(claim["source_message"])


def answer_issue(
    conn: Connection,
    claim_id: str,
    issue_id: int,
    value,
    conversation_id: str,
    claimant_text: str,
    submitter_id: str,
    *,
    today: date | None = None,
) -> dict:
    claim = _lock_claim(conn, claim_id)
    if claim["submitter_id"] != submitter_id:
        raise NotAllowed("This conversation does not belong to the claim's submitter")
    if not conversation_id.startswith(submitter_id):
        raise NotAllowed("conversation_id must belong to the submitter")
    issue = conn.execute(
        text(
            """
            SELECT issue_id, field_path, issue_code, status
            FROM claims.claim_issue
            WHERE issue_id = :issue_id AND claim_id = :claim_id
            """
        ),
        {"issue_id": issue_id, "claim_id": claim_id},
    ).mappings().first()
    if issue is None:
        raise FieldRejected("Issue not found on this claim")
    if issue["status"] != "open":
        raise FieldRejected("That issue is already closed")
    draft = ClaimDraft.model_validate(claim["draft"])
    old_value = value_at(draft, issue["field_path"])
    updated = patch_draft(draft, issue["field_path"], value)
    reference = load_reference(conn, exclude_claim_id=claim_id)
    outcome = validate(
        updated,
        reference,
        exclude_claim_id=claim_id,
        today=today or date.today(),
        timely_days=timely_filing_days(),
    )
    blocking = [
        item
        for item in outcome.issues
        if item.field_path == issue["field_path"] and item.severity != "FLAG"
    ]
    if blocking:
        raise FieldRejected(blocking[0].message)
    conn.execute(
        text(
            """
            UPDATE claims.claim_issue
            SET status = 'resolved', resolved_at = now()
            WHERE issue_id = :issue_id
            """
        ),
        {"issue_id": issue_id},
    )
    conn.execute(
        text(
            """
            INSERT INTO claims.claim_amendment (
                claim_id, issue_id, field_path, old_value, new_value, source,
                conversation_id, claimant_text
            )
            VALUES (
                :claim_id, :issue_id, :field_path, CAST(:old_value AS jsonb),
                CAST(:new_value AS jsonb), 'chatbot', :conversation_id, :claimant_text
            )
            """
        ),
        {
            "claim_id": claim_id,
            "issue_id": issue_id,
            "field_path": issue["field_path"],
            "old_value": _dumps(old_value),
            "new_value": _dumps(value),
            "conversation_id": conversation_id,
            "claimant_text": claimant_text,
        },
    )
    remaining = conn.execute(
        text(
            """
            SELECT count(*) FROM claims.claim_issue
            WHERE claim_id = :claim_id AND status = 'open'
            """
        ),
        {"claim_id": claim_id},
    ).scalar_one()
    conn.execute(
        text("UPDATE claims.claim SET draft = CAST(:draft AS jsonb) WHERE claim_id = :claim_id"),
        {"draft": updated.model_dump_json(), "claim_id": claim_id},
    )
    if int(remaining) > 0:
        return {"issue_id": issue_id, "status": "resolved", "claim_status": claim["status"]}
    _finish_revalidation(conn, claim, updated, outcome)
    return {"issue_id": issue_id, "status": "resolved", "claim_status": outcome.status}


def _finish_revalidation(conn: Connection, claim: dict, draft: ClaimDraft, outcome: Outcome) -> None:
    claim_id = claim["claim_id"]
    now = _utc_now()
    snap = snapshot_of(outcome, now)
    respond_by = now + timedelta(days=pending_info_days()) if outcome.status == "PENDING_INFO" else None
    validated = outcome.status == "VALIDATED"
    conn.execute(
        text(
            """
            UPDATE claims.claim SET
                member_id = :member_id,
                policy_id = :policy_id,
                billing_provider_id = :billing_provider_id,
                rendering_npi = :rendering_npi,
                place_of_service = :place_of_service,
                diagnosis_codes = CASE WHEN CAST(:diagnosis_codes AS jsonb) IS NULL THEN NULL
                    ELSE ARRAY(SELECT jsonb_array_elements_text(CAST(:diagnosis_codes AS jsonb)))
                END,
                service_from = :service_from,
                service_to = :service_to,
                total_billed = :total_billed,
                flags = ARRAY(SELECT jsonb_array_elements_text(CAST(:flags AS jsonb))),
                respond_by = :respond_by,
                reference_snapshot = CAST(:reference_snapshot AS jsonb)
            WHERE claim_id = :claim_id
            """
        ),
        {
            "claim_id": claim_id,
            "member_id": outcome.member.member_id if validated and outcome.member else claim["member_id"],
            "policy_id": outcome.policy.policy_id if validated and outcome.policy else claim["policy_id"],
            "billing_provider_id": outcome.provider.provider_id if validated and outcome.provider else claim["billing_provider_id"],
            "rendering_npi": draft.rendering_npi if validated else claim["rendering_npi"],
            "place_of_service": draft.place_of_service if validated else claim["place_of_service"],
            "diagnosis_codes": _dumps(draft.diagnosis_codes) if validated else (
                _dumps(list(claim["diagnosis_codes"])) if claim["diagnosis_codes"] is not None else None
            ),
            "service_from": draft.service_from if validated else claim["service_from"],
            "service_to": draft.service_to if validated else claim["service_to"],
            "total_billed": draft.total_billed if validated else claim["total_billed"],
            "flags": _dumps(outcome.flags),
            "respond_by": respond_by,
            "reference_snapshot": _dumps(snap),
        },
    )
    if validated:
        _replace_lines(conn, claim_id, draft)
    stored = _insert_issues(conn, claim_id, outcome.issues)
    message = _message_from_claim(claim)
    transition(
        conn,
        claim_id,
        claim["status"],
        outcome.status,
        "payer_service",
        "REVALIDATION",
        "Revalidated after the last open issue was answered",
        details={"reference_snapshot": snap},
    )
    _emit(conn, message, claim_id, outcome, stored, respond_by)


def start_adjudication(conn: Connection, claim_id: str, actor: dict) -> dict:
    """Republish claim.ready_for_adjudication for the current attempt. Does not change status."""
    if actor.get("actor_role") not in {"reviewer", "investigator", "ops"}:
        raise NotAllowed("Only a reviewer, investigator, or ops user can start adjudication")
    claim = conn.execute(
        text(
            """
            SELECT claim_id, status, submission_id, flags
            FROM claims.claim WHERE claim_id = :claim_id
            """
        ),
        {"claim_id": claim_id},
    ).mappings().first()
    if claim is None:
        raise Conflict(None)
    if claim["status"] != "VALIDATED":
        raise Conflict(claim["status"])
    previous = conn.execute(
        text(
            """
            SELECT payload FROM claims.outbox
            WHERE claim_id = :claim_id AND routing_key = 'claim.ready_for_adjudication'
            ORDER BY id DESC LIMIT 1
            """
        ),
        {"claim_id": claim_id},
    ).mappings().first()
    if previous and previous["payload"]:
        payload = dict(previous["payload"])
        payload["message_id"] = str(uuid4())
        if isinstance(payload.get("validated_at"), datetime):
            payload["validated_at"] = payload["validated_at"].isoformat()
    else:
        attempt = max(_attempt(conn, claim_id), 1)
        payload = ReadyForAdjudication(
            message_id=uuid4(),
            claim_id=claim_id,
            submission_id=claim["submission_id"],
            validated_at=_utc_now(),
            flags=list(claim["flags"] or []),
            adjudication_attempt=attempt,
        ).model_dump(mode="json")
    _outbox(conn, "claim.ready_for_adjudication", claim_id, payload)
    record_audit(
        conn,
        actor_type=actor["actor_type"],
        actor_id=actor["actor_id"],
        actor_role=actor["actor_role"],
        action="adjudication.start",
        claim_id=claim_id,
        submission_id=claim["submission_id"],
        correlation_id=actor.get("correlation_id") or claim["submission_id"],
        details={
            "message_id": str(payload["message_id"]),
            "adjudication_attempt": payload.get("adjudication_attempt"),
        },
    )
    return {
        "claim_id": claim_id,
        "message_id": str(payload["message_id"]),
        "adjudication_attempt": payload.get("adjudication_attempt"),
        "status": "VALIDATED",
    }


def record_audit(
    conn: Connection,
    *,
    actor_type: str,
    actor_id: str,
    actor_role: str,
    action: str,
    claim_id: str | None = None,
    submission_id: str | None = None,
    correlation_id: str | None = None,
    reason: str | None = None,
    details: dict | None = None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO claims.audit_event (
                actor_type, actor_id, actor_role, action, claim_id, submission_id,
                correlation_id, reason, details
            )
            VALUES (
                :actor_type, :actor_id, :actor_role, :action, :claim_id, :submission_id,
                :correlation_id, :reason, CAST(:details AS jsonb)
            )
            """
        ),
        {
            "actor_type": actor_type,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "action": action,
            "claim_id": claim_id,
            "submission_id": submission_id,
            "correlation_id": correlation_id,
            "reason": reason,
            "details": _dumps(details or {}),
        },
    )


def submission_status(conn: Connection, submission_id: str, actor: dict, audit_fn=record_audit) -> dict:
    audit_fn(
        conn,
        actor_type=actor["actor_type"],
        actor_id=actor["actor_id"],
        actor_role=actor["actor_role"],
        action="claim.read",
        submission_id=submission_id,
        correlation_id=actor.get("correlation_id") or submission_id,
        details={"endpoint": "submission.status"},
    )
    claim = conn.execute(
        text(
            """
            SELECT claim_id, status, respond_by FROM claims.claim WHERE submission_id = :submission_id
            """
        ),
        {"submission_id": submission_id},
    ).mappings().first()
    if claim is None:
        error = conn.execute(
            text(
                """
                SELECT 1 FROM claims.intake_error
                WHERE submission_id = :submission_id AND resolved_at IS NULL
                """
            ),
            {"submission_id": submission_id},
        ).first()
        if error:
            return {
                "submission_id": submission_id,
                "state": "FAILED_PROCESSING",
                "status": "FAILED_PROCESSING",
                "claim_id": None,
                "history": [],
                "issues": [],
                "message": "Processing failed. We're looking into it.",
            }
        return {
            "submission_id": submission_id,
            "state": "PROCESSING",
            "status": "PROCESSING",
            "claim_id": None,
            "history": [],
            "issues": [],
            "message": "The claim is still being processed.",
        }
    history = [
        dict(row)
        for row in conn.execute(
            text(
                """
                SELECT from_status, to_status, actor, reason_code, reason, changed_at
                FROM claims.claim_status_history
                WHERE claim_id = :claim_id
                ORDER BY id
                """
            ),
            {"claim_id": claim["claim_id"]},
        ).mappings()
    ]
    issues = open_issues(conn, claim["claim_id"])
    for row in history:
        if isinstance(row["changed_at"], datetime):
            row["changed_at"] = row["changed_at"].isoformat()
    return {
        "submission_id": submission_id,
        "state": claim["status"],
        "status": claim["status"],
        "claim_id": claim["claim_id"],
        "history": history,
        "issues": issues,
        "message": None,
        "respond_by": claim["respond_by"].isoformat() if isinstance(claim["respond_by"], datetime) else claim["respond_by"],
    }


def open_issues(conn: Connection, claim_id: str) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT issue_id, field_path, issue_code, severity, message, status
            FROM claims.claim_issue
            WHERE claim_id = :claim_id AND status = 'open'
            ORDER BY issue_id
            """
        ),
        {"claim_id": claim_id},
    ).mappings()
    return [dict(row) for row in rows]


def get_claim(conn: Connection, claim_id: str, actor: dict, audit_fn=record_audit) -> dict | None:
    audit_fn(
        conn,
        actor_type=actor["actor_type"],
        actor_id=actor["actor_id"],
        actor_role=actor["actor_role"],
        action="claim.read",
        claim_id=claim_id,
        correlation_id=actor.get("correlation_id"),
        details={"endpoint": "claim.read"},
    )
    claim = conn.execute(
        text("SELECT * FROM claims.claim WHERE claim_id = :claim_id"),
        {"claim_id": claim_id},
    ).mappings().first()
    if claim is None:
        return None
    lines = [
        dict(row)
        for row in conn.execute(
            text(
                """
                SELECT line_no, cpt_code, modifiers, units, billed_amount, service_date,
                       diagnosis_pointers, prior_auth_number
                FROM claims.claim_line
                WHERE claim_id = :claim_id
                ORDER BY line_no
                """
            ),
            {"claim_id": claim_id},
        ).mappings()
    ]
    body = dict(claim)
    for key, value in list(body.items()):
        if isinstance(value, datetime | date):
            body[key] = value.isoformat()
        elif isinstance(value, Decimal):
            body[key] = format(value, "f")
    for line in lines:
        if isinstance(line["billed_amount"], Decimal):
            line["billed_amount"] = format(line["billed_amount"], "f")
        if isinstance(line["service_date"], date):
            line["service_date"] = line["service_date"].isoformat()
    body["lines"] = lines
    return body


def list_issues(conn: Connection, claim_id: str, status: str | None, actor: dict, audit_fn=record_audit) -> list[dict]:
    audit_fn(
        conn,
        actor_type=actor["actor_type"],
        actor_id=actor["actor_id"],
        actor_role=actor["actor_role"],
        action="claim.issues.read",
        claim_id=claim_id,
        correlation_id=actor.get("correlation_id"),
        details={"endpoint": "issues.read", "status": status},
    )
    if status:
        rows = conn.execute(
            text(
                """
                SELECT issue_id, field_path, issue_code, severity, message, status
                FROM claims.claim_issue
                WHERE claim_id = :claim_id AND status = :status
                ORDER BY issue_id
                """
            ),
            {"claim_id": claim_id, "status": status},
        ).mappings()
    else:
        rows = conn.execute(
            text(
                """
                SELECT issue_id, field_path, issue_code, severity, message, status
                FROM claims.claim_issue
                WHERE claim_id = :claim_id
                ORDER BY issue_id
                """
            ),
            {"claim_id": claim_id},
        ).mappings()
    return [dict(row) for row in rows]


def cached_extraction(conn: Connection, document_id: str, sha256: str, version: str) -> dict | None:
    row = conn.execute(
        text(
            """
            SELECT result FROM claims.document_extraction
            WHERE document_id = :document_id AND sha256 = :sha256 AND extractor_version = :version
            """
        ),
        {"document_id": document_id, "sha256": sha256, "version": version},
    ).mappings().first()
    if row is None:
        return None
    return row["result"]


def save_extraction(conn: Connection, document_id: str, sha256: str, version: str, doc_class: str, result: dict) -> None:
    conn.execute(
        text(
            """
            INSERT INTO claims.document_extraction (
                document_id, sha256, extractor_version, doc_class, result
            )
            VALUES (:document_id, :sha256, :version, :doc_class, CAST(:result AS jsonb))
            ON CONFLICT (document_id, sha256, extractor_version) DO NOTHING
            """
        ),
        {
            "document_id": document_id,
            "sha256": sha256,
            "version": version,
            "doc_class": doc_class,
            "result": _dumps(result),
        },
    )


def record_intake_error(conn: Connection, message_id: str, submission_id: str | None, error_class: str, error: str, attempts: int) -> None:
    conn.execute(
        text(
            """
            INSERT INTO claims.intake_error (
                message_id, submission_id, error_class, error, attempts
            )
            VALUES (:message_id, :submission_id, :error_class, :error, :attempts)
            ON CONFLICT (message_id) DO NOTHING
            """
        ),
        {
            "message_id": message_id,
            "submission_id": submission_id,
            "error_class": error_class,
            "error": error[:500],
            "attempts": attempts,
        },
    )


def sweep_once(conn: Connection, now: datetime | None = None) -> list[str]:
    moment = now or _utc_now()
    rows = conn.execute(
        text(
            """
            SELECT claim_id, submission_id, source_message
            FROM claims.claim
            WHERE status = 'PENDING_INFO' AND respond_by IS NOT NULL AND respond_by < :now
            FOR UPDATE
            """
        ),
        {"now": moment},
    ).mappings()
    rejected: list[str] = []
    for row in rows:
        try:
            transition(
                conn,
                row["claim_id"],
                "PENDING_INFO",
                "REJECTED",
                "sweeper",
                "INFO_TIMEOUT",
                "No reply before the deadline",
                details={"reference_snapshot": None},
            )
        except Conflict:
            continue
        conn.execute(
            text("UPDATE claims.claim SET respond_by = NULL WHERE claim_id = :claim_id"),
            {"claim_id": row["claim_id"]},
        )
        stored = _insert_issues(
            conn,
            row["claim_id"],
            [Issue("respond_by", "INFO_TIMEOUT", "REJECT", "No reply arrived before the deadline.")],
        )
        message = ClaimSubmitted.model_validate(row["source_message"])
        payload = RejectedEvent(
            message_id=uuid4(),
            claim_id=row["claim_id"],
            submission_id=row["submission_id"],
            issues=stored,
        )
        _outbox(conn, "claim.rejected", row["claim_id"], payload.model_dump(mode="json"))
        del message
        rejected.append(row["claim_id"])
    return rejected


def attach_document(conn: Connection, claim_id: str, document_id: str, doc_type: str, storage_uri: str, sha256: str) -> None:
    _lock_claim(conn, claim_id)
    conn.execute(
        text(
            """
            INSERT INTO claims.claim_document (document_id, claim_id, doc_type, storage_uri, sha256)
            VALUES (:document_id, :claim_id, :doc_type, :storage_uri, :sha256)
            """
        ),
        {
            "document_id": document_id,
            "claim_id": claim_id,
            "doc_type": doc_type,
            "storage_uri": storage_uri,
            "sha256": sha256,
        },
    )


def resolve_intake_error(conn: Connection, message_id: str) -> None:
    conn.execute(
        text("UPDATE claims.intake_error SET resolved_at = now() WHERE message_id = :message_id"),
        {"message_id": message_id},
    )


def _shown(value):
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _member_name(conn: Connection, member_id: str) -> str | None:
    row = conn.execute(
        text("SELECT first_name, last_name FROM claims.member WHERE member_id = :member_id"),
        {"member_id": member_id},
    ).first()
    if row is None:
        return None
    return f"{row[0]} {row[1]}".strip()


def read_member_claims(conn: Connection, member_id: str, actor: dict, audit_fn=record_audit) -> dict | None:
    """Claims this member submitted or that name them. No draft and no provider quality."""
    name = _member_name(conn, member_id)
    if name is None:
        return None
    audit_fn(
        conn,
        actor_type=actor["actor_type"],
        actor_id=actor["actor_id"],
        actor_role=actor["actor_role"],
        action="member.claims.read",
        correlation_id=actor.get("correlation_id"),
        details={"endpoint": "member.claims", "member_id": member_id},
    )
    rows = conn.execute(
        text(
            """
            SELECT claim_id, submission_id, status, service_from, service_to, total_billed
            FROM claims.claim
            WHERE member_id = :member_id OR submitter_id = :member_id
            ORDER BY received_at DESC
            LIMIT 20
            """
        ),
        {"member_id": member_id},
    ).mappings()
    claims = []
    for row in rows:
        claims.append({key: _shown(value) for key, value in dict(row).items()})
    questions: dict[str, list[str]] = {claim["claim_id"]: [] for claim in claims}
    claim_ids = list(questions)
    if claim_ids:
        issues = conn.execute(
            text(
                """
                SELECT claim_id, message
                FROM claims.claim_issue
                WHERE status = 'open' AND claim_id IN :claim_ids
                ORDER BY issue_id
                """
            ).bindparams(bindparam("claim_ids", expanding=True)),
            {"claim_ids": claim_ids},
        ).mappings()
        for issue in issues:
            bucket = questions[issue["claim_id"]]
            if len(bucket) < 5:
                bucket.append(issue["message"])
    for claim in claims:
        claim["open_questions"] = questions[claim["claim_id"]]
    return {"member_id": member_id, "member_name": name, "claims": claims}


def read_member_coverage(conn: Connection, member_id: str, actor: dict, audit_fn=record_audit) -> dict | None:
    name = _member_name(conn, member_id)
    if name is None:
        return None
    audit_fn(
        conn,
        actor_type=actor["actor_type"],
        actor_id=actor["actor_id"],
        actor_role=actor["actor_role"],
        action="member.coverage.read",
        correlation_id=actor.get("correlation_id"),
        details={"endpoint": "member.coverage", "member_id": member_id},
    )
    policies = [
        {key: _shown(value) for key, value in dict(row).items()}
        for row in conn.execute(
            text(
                """
                SELECT policy_id, plan_code, group_number, status, effective_date, termination_date
                FROM claims.policy
                WHERE member_id = :member_id
                ORDER BY effective_date
                """
            ),
            {"member_id": member_id},
        ).mappings()
    ]
    plan_codes = list({row["plan_code"] for row in policies})
    benefits: list[dict] = []
    if plan_codes:
        found = conn.execute(
            text(
                """
                SELECT b.plan_code, b.cpt_code, c.description, b.benefit_category,
                       b.is_covered, b.requires_prior_auth, b.policy_section
                FROM claims.plan_benefit b
                LEFT JOIN claims.ref_cpt c ON c.code = b.cpt_code
                WHERE b.plan_code IN :plan_codes
                ORDER BY b.plan_code, b.cpt_code
                """
            ).bindparams(bindparam("plan_codes", expanding=True)),
            {"plan_codes": plan_codes},
        ).mappings()
        benefits = [dict(row) for row in found]
    return {"member_id": member_id, "member_name": name, "policies": policies, "benefits": benefits}


def search_providers(conn: Connection, query: str, actor: dict, audit_fn=record_audit) -> list[dict]:
    audit_fn(
        conn,
        actor_type=actor["actor_type"],
        actor_id=actor["actor_id"],
        actor_role=actor["actor_role"],
        action="provider.search",
        correlation_id=actor.get("correlation_id"),
        details={"endpoint": "provider.search"},
    )
    needle = query.strip()
    if not needle:
        return []
    like = f"%{needle.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%"
    rows = conn.execute(
        text(
            """
            SELECT provider_id, npi, name, network_status, city, state
            FROM claims.provider
            WHERE npi = :exact
               OR state ILIKE :exact
               OR name ILIKE :like ESCAPE '\\'
               OR city ILIKE :like ESCAPE '\\'
            ORDER BY name
            LIMIT 8
            """
        ),
        {"exact": needle, "like": like},
    ).mappings()
    return [dict(row) for row in rows]
