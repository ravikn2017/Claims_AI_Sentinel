"""HTTP API. Every read writes an audit row first and fails if that insert fails."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from payer_service.app.db import payer_engine
from payer_service.app.errors import Conflict, FieldRejected, NotAllowed
from payer_service.app.extract import read_pdf_text
from payer_service.app.pipeline import file_sha256, uri_to_path, verify_document
from payer_service.app.repository import (
    answer_issue,
    apply_transition,
    attach_document,
    get_claim,
    list_issues,
    read_member_claims,
    read_member_coverage,
    search_providers,
    start_adjudication,
    submission_status,
)

router = APIRouter()


class AnswerBody(BaseModel):
    value: object
    conversation_id: str = Field(min_length=1)
    claimant_text: str = ""
    submitter_id: str = Field(min_length=1)


class TransitionIssue(BaseModel):
    field_path: str
    issue_code: str
    message: str


class TransitionBody(BaseModel):
    from_status: str
    to_status: str
    actor: str
    reason_code: str
    reason: str = ""
    idempotency_key: str
    issues: list[TransitionIssue] = Field(default_factory=list)


class DocumentBody(BaseModel):
    document_id: str
    doc_type: str
    storage_uri: str
    sha256: str


def actor_from(request: Request) -> dict:
    return {
        "actor_type": request.headers.get("x-actor-type", "service"),
        "actor_id": request.headers.get("x-actor-id", "portal"),
        "actor_role": request.headers.get("x-actor-role", "service"),
        "correlation_id": request.headers.get("x-correlation-id"),
    }


@router.get("/submissions/{submission_id}/status")
def status(submission_id: str, request: Request):
    with payer_engine().begin() as conn:
        return submission_status(conn, submission_id, actor_from(request))


@router.get("/claims/{claim_id}")
def read_claim(claim_id: str, request: Request):
    with payer_engine().begin() as conn:
        body = get_claim(conn, claim_id, actor_from(request))
    if body is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return body


@router.get("/claims/{claim_id}/issues")
def read_issues(claim_id: str, request: Request, status: str | None = None):
    with payer_engine().begin() as conn:
        found = get_claim(conn, claim_id, {**actor_from(request), "actor_id": actor_from(request)["actor_id"]})
        if found is None:
            raise HTTPException(status_code=404, detail="Claim not found")
        return list_issues(conn, claim_id, status, actor_from(request))


@router.post("/claims/{claim_id}/issues/{issue_id}/answers")
def post_answer(claim_id: str, issue_id: int, body: AnswerBody):
    try:
        with payer_engine().begin() as conn:
            return answer_issue(
                conn,
                claim_id,
                issue_id,
                body.value,
                body.conversation_id,
                body.claimant_text,
                body.submitter_id,
            )
    except FieldRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except NotAllowed as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    except Conflict as exc:
        raise HTTPException(status_code=409, detail={"status": exc.status}) from exc


@router.post("/claims/{claim_id}/adjudication-start")
def post_adjudication_start(claim_id: str, request: Request):
    try:
        with payer_engine().begin() as conn:
            return start_adjudication(conn, claim_id, actor_from(request))
    except NotAllowed as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    except Conflict as exc:
        if exc.status is None:
            raise HTTPException(status_code=404, detail="Claim not found") from exc
        raise HTTPException(status_code=409, detail={"status": exc.status}) from exc


@router.post("/claims/{claim_id}/transitions")
def post_transition(claim_id: str, body: TransitionBody):
    try:
        with payer_engine().begin() as conn:
            result = apply_transition(
                conn,
                claim_id,
                body.from_status,
                body.to_status,
                body.actor,
                body.reason_code,
                body.reason,
                body.idempotency_key,
                [issue.model_dump() for issue in body.issues],
            )
            current = conn.execute(
                __import__("sqlalchemy").text("SELECT status FROM claims.claim WHERE claim_id = :claim_id"),
                {"claim_id": claim_id},
            ).scalar()
        return {"result": result, "status": current}
    except NotAllowed as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except Conflict as exc:
        if exc.status is None:
            raise HTTPException(status_code=404, detail="Claim not found") from exc
        raise HTTPException(status_code=409, detail={"status": exc.status}) from exc


@router.post("/claims/{claim_id}/documents")
def post_document(claim_id: str, body: DocumentBody, request: Request):
    try:
        verify_document(body.storage_uri, body.sha256)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with payer_engine().begin() as conn:
        from payer_service.app.repository import record_audit

        record_audit(
            conn,
            actor_type=actor_from(request)["actor_type"],
            actor_id=actor_from(request)["actor_id"],
            actor_role=actor_from(request)["actor_role"],
            action="document.url_issued",
            claim_id=claim_id,
            correlation_id=actor_from(request).get("correlation_id"),
            details={"endpoint": "documents.attach", "document_id": body.document_id},
        )
        try:
            attach_document(conn, claim_id, body.document_id, body.doc_type, body.storage_uri, body.sha256)
        except Conflict as exc:
            raise HTTPException(status_code=404, detail="Claim not found") from exc
    return {"document_id": body.document_id, "sha256": file_sha256(uri_to_path(body.storage_uri))}


@router.get("/claims/{claim_id}/medical-records")
def medical_records(claim_id: str, request: Request):
    from sqlalchemy import text

    from payer_service.app.repository import record_audit

    actor = actor_from(request)
    with payer_engine().begin() as conn:
        record_audit(
            conn,
            actor_type=actor["actor_type"],
            actor_id=actor["actor_id"],
            actor_role=actor["actor_role"],
            action="claim.medical_records.read",
            claim_id=claim_id,
            correlation_id=actor.get("correlation_id"),
            details={"endpoint": "medical-records"},
        )
        claim = conn.execute(
            text("SELECT 1 FROM claims.claim WHERE claim_id = :claim_id"),
            {"claim_id": claim_id},
        ).first()
        if claim is None:
            raise HTTPException(status_code=404, detail="Claim not found")
        rows = conn.execute(
            text(
                """
                SELECT document_id, storage_uri, uploaded_at
                FROM claims.claim_document
                WHERE claim_id = :claim_id AND doc_type = 'medical_record'
                ORDER BY uploaded_at
                """
            ),
            {"claim_id": claim_id},
        ).mappings()
        records = []
        for row in rows:
            pages = read_pdf_text(uri_to_path(row["storage_uri"]))
            records.append(
                {
                    "document_id": row["document_id"],
                    "received_at": row["uploaded_at"].isoformat(),
                    "text": "\n".join(text for _, text in pages),
                }
            )
    return records


@router.get("/members/{member_id}/claims")
def member_claims(member_id: str, request: Request):
    with payer_engine().begin() as conn:
        body = read_member_claims(conn, member_id, actor_from(request))
    if body is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return body


@router.get("/members/{member_id}/coverage")
def member_coverage(member_id: str, request: Request):
    with payer_engine().begin() as conn:
        body = read_member_coverage(conn, member_id, actor_from(request))
    if body is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return body


@router.get("/providers")
def providers(request: Request, q: str = ""):
    with payer_engine().begin() as conn:
        found = search_providers(conn, q[:80], actor_from(request))
    return {"providers": found}


@router.get("/reference/plan-benefits/{plan_code}")
def plan_benefits(plan_code: str, request: Request):
    return _benefits(plan_code, None, request)


@router.get("/reference/plan-benefits/{plan_code}/{cpt_code}")
def plan_benefit(plan_code: str, cpt_code: str, request: Request):
    rows = _benefits(plan_code, cpt_code, request)
    if not rows:
        raise HTTPException(status_code=404, detail="Plan benefit not found")
    return rows[0]


def _benefits(plan_code: str, cpt_code: str | None, request: Request) -> list[dict]:
    from sqlalchemy import text

    from payer_service.app.repository import record_audit

    actor = actor_from(request)
    with payer_engine().begin() as conn:
        record_audit(
            conn,
            actor_type=actor["actor_type"],
            actor_id=actor["actor_id"],
            actor_role=actor["actor_role"],
            action="reference.plan_benefit.read",
            correlation_id=actor.get("correlation_id"),
            details={"endpoint": "plan-benefits", "plan_code": plan_code, "cpt_code": cpt_code},
        )
        if cpt_code:
            rows = conn.execute(
                text(
                    """
                    SELECT plan_code, cpt_code, benefit_category, is_covered,
                           requires_prior_auth, policy_section
                    FROM claims.plan_benefit
                    WHERE plan_code = :plan_code AND cpt_code = :cpt_code
                    """
                ),
                {"plan_code": plan_code, "cpt_code": cpt_code},
            ).mappings()
        else:
            rows = conn.execute(
                text(
                    """
                    SELECT plan_code, cpt_code, benefit_category, is_covered,
                           requires_prior_auth, policy_section
                    FROM claims.plan_benefit
                    WHERE plan_code = :plan_code
                    ORDER BY cpt_code
                    """
                ),
                {"plan_code": plan_code},
            ).mappings()
        return [dict(row) for row in rows]
