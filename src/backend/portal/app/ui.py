"""Screens the React portal calls: claim list, missing-info chat, ops, and review."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from adjudicator.LLMS.embeddings import EmbeddingFailed
from checks import platform_status
from adjudicator.index import EmptyDocument, index_document, index_seed_documents
from adjudicator.tools.documents import get_medical_policy, search_policy_documents
from db_url import document_root
from portal.app.auth import current_user
from portal.app.db import portal_engine

router = APIRouter()
PAYER = os.environ.get("PAYER_SERVICE_URL", "http://127.0.0.1:47111")
CHATBOT = os.environ.get("CHATBOT_URL", "http://127.0.0.1:47112")
ADJUDICATOR = os.environ.get("ADJUDICATOR_URL", "http://127.0.0.1:47113")
FRAUD = os.environ.get("FRAUD_SERVICE_URL", "http://127.0.0.1:47114")


class ChatText(BaseModel):
    text: str = Field(min_length=1)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1)


class IngestBody(BaseModel):
    doc_type: str
    doc_id: str = Field(min_length=1)
    plan_code: str | None = None
    cpt_codes: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1)


class TechniqueBody(BaseModel):
    technique: str = Field(min_length=1)


class AskBody(BaseModel):
    question: str = Field(min_length=1)
    user_id: str = ""
    role: str = ""


class ReviewDecision(BaseModel):
    decision: str
    allowed_amount: str | None = None
    notes: str = ""


class InvestigationResult(BaseModel):
    outcome: str
    notes: str = ""


def _require(request: Request, *roles: str) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    if user["role"] not in roles:
        raise HTTPException(status_code=403, detail="This action is not available for this role")
    return user


def _actor_id(request: Request) -> str:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user["submitter_id"] or user["user_id"]


def _payer_headers(request: Request) -> dict[str, str]:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return {
        "X-Actor-Type": user["actor_type"],
        "X-Actor-Id": user["submitter_id"] or user["user_id"],
        "X-Actor-Role": user["role"],
        "X-Correlation-ID": request.headers.get("x-correlation-id", ""),
    }


def _jsonable(value):
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _rows(sql: str, params: dict | None = None) -> list[dict]:
    with portal_engine().connect() as conn:
        found = conn.execute(text(sql), params or {}).mappings()
        return [_jsonable(dict(row)) for row in found]


async def _payer(method: str, path: str, request: Request, payload: dict | None = None) -> tuple[int, object]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.request(method, f"{PAYER}{path}", headers=_payer_headers(request), json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Payer service is unavailable") from exc
    try:
        body = response.json()
    except json.JSONDecodeError:
        body = {"detail": response.text}
    return response.status_code, body


def _pass(status: int, body: object) -> JSONResponse:
    return JSONResponse(status_code=status, content=body)


async def _chatbot(method: str, path: str, request: Request, payload: dict | None = None) -> tuple[int, object]:
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.request(
                method,
                f"{CHATBOT}{path}",
                headers=_payer_headers(request),
                params=payload if method == "GET" else None,
                json=None if method == "GET" else payload,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Chatbot is unavailable") from exc
    try:
        body = response.json()
    except json.JSONDecodeError:
        body = {"detail": response.text}
    return response.status_code, body


async def _owned_submitter(claim_id: str, request: Request) -> str:
    user = _require(request, "provider", "member")
    status, record = await _payer("GET", f"/claims/{claim_id}", request)
    if status != 200:
        detail = record.get("detail") if isinstance(record, dict) else "Claim not found"
        if not isinstance(detail, str):
            detail = "Claim not found"
        raise HTTPException(status_code=status, detail=detail)
    submitter_id = user["submitter_id"] or user["user_id"]
    if record.get("submitter_id") != submitter_id:
        raise HTTPException(status_code=403, detail="This claim belongs to another submitter")
    return submitter_id


async def _claim_for_submission(submission_id: str, request: Request) -> tuple[str, dict]:
    status, record = await _payer("GET", f"/submissions/{submission_id}/status", request)
    if status != 200 or not isinstance(record, dict) or not record.get("claim_id"):
        detail = record.get("detail") if isinstance(record, dict) else "Claim not found"
        if not isinstance(detail, str):
            detail = "Claim not found"
        raise HTTPException(status_code=status if status != 200 else 404, detail=detail)
    return str(record["claim_id"]), record


@router.get("/submissions/{submission_id}/draft")
async def claim_draft(submission_id: str, request: Request):
    claim_id, _record = await _claim_for_submission(submission_id, request)
    await _owned_submitter(claim_id, request)
    status, record = await _payer("GET", f"/claims/{claim_id}", request)
    if status != 200 or not isinstance(record, dict):
        return _pass(status, record)
    return {"draft": record.get("draft")}


@router.post("/submissions/{submission_id}/correction")
async def correct_claim(submission_id: str, request: Request):
    claim_id, _record = await _claim_for_submission(submission_id, request)
    submitter_id = await _owned_submitter(claim_id, request)
    payload = await request.json()
    claim = payload.get("claim") if isinstance(payload, dict) else None
    code, result = await _payer(
        "POST",
        f"/claims/{claim_id}/correction",
        request,
        {"claim": claim, "submitter_id": submitter_id},
    )
    return _pass(code, result)


@router.post("/adjudication/{claim_id}/start")
async def start_adjudication(claim_id: str, request: Request):
    _require(request, "reviewer", "investigator", "ops")
    code, result = await _payer("POST", f"/claims/{claim_id}/adjudication-start", request)
    return _pass(code, result)


@router.get("/submissions")
def list_submissions(request: Request):
    user = _require(request, "provider", "member", "reviewer", "investigator", "ops")
    staff = user["role"] in {"reviewer", "investigator", "ops"}
    submitter_id = user["submitter_id"] or user["user_id"]
    scope = "TRUE" if staff else "l.submitter_id = :submitter_id"
    return _rows(
        f"""
        SELECT
            l.submission_id,
            l.channel,
            l.submitter_type,
            l.submitter_id,
            l.publish_status,
            l.created_at,
            c.claim_id,
            CASE
                WHEN c.status IS NOT NULL THEN c.status
                WHEN EXISTS (
                    SELECT 1 FROM claims.intake_error e
                    WHERE e.submission_id = l.submission_id AND e.resolved_at IS NULL
                ) THEN 'FAILED_PROCESSING'
                ELSE 'PROCESSING'
            END AS claim_status,
            EXISTS (
                SELECT 1 FROM claims.claim_status_history h
                WHERE h.claim_id = c.claim_id AND h.to_status = 'PENDING_INFO'
            ) AS had_pending_info
        FROM portal.submission_log l
        LEFT JOIN claims.claim c ON c.submission_id = l.submission_id
        WHERE {scope}
        ORDER BY l.created_at DESC
        """,
        {} if staff else {"submitter_id": submitter_id},
    )


@router.get("/chat/{claim_id}")
async def read_chat(claim_id: str, request: Request):
    submitter_id = await _owned_submitter(claim_id, request)
    code, result = await _chatbot("GET", f"/conversations/{claim_id}", request, {"submitter_id": submitter_id})
    return _pass(code, result)


@router.post("/chat/{claim_id}")
async def post_chat(claim_id: str, body: ChatText, request: Request):
    submitter_id = await _owned_submitter(claim_id, request)
    code, result = await _chatbot(
        "POST",
        f"/conversations/{claim_id}/messages",
        request,
        {"text": body.text, "submitter_id": submitter_id},
    )
    return _pass(code, result)


@router.get("/inquiry")
async def read_inquiry(request: Request):
    user = _require(request, "member")
    member_id = user["submitter_id"] or ""
    if not member_id:
        raise HTTPException(status_code=403, detail="This account is not a member")
    code, result = await _chatbot("GET", f"/inquiries/{member_id}", request)
    return _pass(code, result)


@router.post("/inquiry")
async def post_inquiry_message(body: ChatText, request: Request):
    user = _require(request, "member")
    member_id = user["submitter_id"] or ""
    if not member_id:
        raise HTTPException(status_code=403, detail="This account is not a member")
    code, result = await _chatbot(
        "POST",
        f"/inquiries/{member_id}/messages",
        request,
        {"text": body.text, "submitter_id": member_id},
    )
    return _pass(code, result)


@router.post("/chat/{claim_id}/documents")
async def chat_document(claim_id: str, request: Request):
    submitter_id = await _owned_submitter(claim_id, request)
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(status_code=400, detail="file is required")
    content = await upload.read()
    filename = getattr(upload, "filename", None) or "upload.pdf"
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File is larger than 10 MB")
    if not filename.lower().endswith(".pdf") and not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    status, record = await _payer("GET", f"/claims/{claim_id}", request)
    if status != 200:
        return _pass(status, record)
    folder = document_root() / (record.get("submission_id") or claim_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / Path(filename).name
    target.write_bytes(content)
    document_id = f"DOC-{uuid4().hex[:10]}"
    digest = hashlib.sha256(content).hexdigest()
    code, result = await _payer(
        "POST",
        f"/claims/{claim_id}/documents",
        request,
        {
            "document_id": document_id,
            "doc_type": str(form.get("doc_type") or "medical_record"),
            "storage_uri": target.resolve().as_uri(),
            "sha256": digest,
        },
    )
    if code != 200:
        return _pass(code, result)
    note_code, note = await _chatbot(
        "POST",
        f"/conversations/{claim_id}/notes",
        request,
        {
            "submitter_id": submitter_id,
            "text": "The document is attached. It does not by itself close an open issue.",
        },
    )
    if note_code != 200:
        return _pass(note_code, note)
    return _pass(code, result)


@router.get("/ops/chunks")
def list_chunks(request: Request, doc_type: str | None = None, plan_code: str | None = None, cpt: str | None = None, q: str | None = None):
    _require(request, "ops")
    query = (q or "").strip()
    procedure = (cpt or "").strip()
    plan = (plan_code or "").strip()
    if query:
        if not plan:
            raise HTTPException(status_code=422, detail="A plan is required")
        try:
            return search_policy_documents(plan, query)
        except EmbeddingFailed as exc:
            raise HTTPException(status_code=503, detail="Embedding service is unavailable") from exc
    if procedure:
        return get_medical_policy(procedure)
    clauses = ["1 = 1"]
    params: dict = {}
    if doc_type:
        clauses.append("doc_type = :doc_type")
        params["doc_type"] = doc_type
    if plan:
        clauses.append("plan_code = :plan_code")
        params["plan_code"] = plan
    where = " AND ".join(clauses)
    return _rows(
        f"""
        SELECT id, doc_type, doc_id, plan_code, cpt_codes, section, heading, text,
               (embedding IS NOT NULL) AS embedded
        FROM adjudication.payer_doc_chunk
        WHERE {where}
        ORDER BY doc_id, section
        LIMIT 50
        """,
        params,
    )


def _index_or_http(**document) -> int:
    try:
        return index_document(**document)
    except EmptyDocument as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EmbeddingFailed as exc:
        raise HTTPException(status_code=503, detail="Embedding service is unavailable") from exc


@router.post("/ops/documents")
def ingest_document(body: IngestBody, request: Request):
    _require(request, "ops")
    if body.doc_type not in {"eoc", "medical_policy"}:
        raise HTTPException(status_code=422, detail="doc_type must be eoc or medical_policy")
    if body.doc_type == "eoc" and not body.plan_code:
        raise HTTPException(status_code=422, detail="An evidence of coverage document needs a plan code")
    if body.doc_type == "medical_policy" and not body.cpt_codes:
        raise HTTPException(status_code=422, detail="A medical policy needs a CPT code")
    count = _index_or_http(
        doc_type=body.doc_type,
        doc_id=body.doc_id,
        plan_code=body.plan_code,
        cpt_codes=body.cpt_codes or None,
        text=body.text,
    )
    with portal_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO claims.audit_event
                    (actor_type, actor_id, actor_role, action, reason, details)
                VALUES
                    ('operator', :actor_id, 'ops', 'reference.load', 'Indexed payer documents',
                     CAST(:details AS jsonb))
                """
            ),
            {
                "actor_id": _actor_id(request) or "ops",
                "details": json.dumps({"doc_type": body.doc_type, "doc_id": body.doc_id, "chunks": count}),
            },
        )
    return {"doc_id": body.doc_id, "chunks": count}


@router.post("/ops/documents/reindex")
def reindex_documents(request: Request):
    _require(request, "ops")
    try:
        return index_seed_documents()
    except EmptyDocument as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EmbeddingFailed as exc:
        raise HTTPException(status_code=503, detail="Embedding service is unavailable") from exc


@router.get("/ops/intake-errors")
def list_intake_errors(request: Request):
    _require(request, "ops")
    return _rows(
        """
        SELECT message_id::text AS message_id, submission_id, error_class, error, attempts,
               dead_lettered_at, resolved_at
        FROM claims.intake_error
        ORDER BY dead_lettered_at DESC
        """
    )


@router.post("/ops/intake-errors/{message_id}/replay")
async def replay_intake(message_id: str, body: ReasonBody, request: Request):
    _require(request, "ops")
    from payer_service.dlq import replay

    try:
        await replay(message_id, _actor_id(request), body.reason)
    except SystemExit as exc:
        raise HTTPException(status_code=404, detail="That message is not in the dead-letter queue") from exc
    return {"message_id": message_id, "status": "replayed"}


@router.post("/ops/intake-errors/{message_id}/discard")
async def discard_intake(message_id: str, body: ReasonBody, request: Request):
    _require(request, "ops")
    from payer_service.dlq import discard

    try:
        await discard(message_id, _actor_id(request), body.reason)
    except SystemExit as exc:
        raise HTTPException(status_code=422, detail="A reason is required") from exc
    return {"message_id": message_id, "status": "discarded"}


@router.get("/ops/audit/{claim_id}")
def audit_trail(claim_id: str, request: Request):
    _require(request, "ops", "reviewer", "investigator")
    return _rows(
        """
        SELECT occurred_at, source, summary
        FROM claims.claim_audit_trail
        WHERE claim_id = :claim_id
        ORDER BY occurred_at
        """,
        {"claim_id": claim_id},
    )


@router.get("/ops/events/{claim_id}")
def adjudication_events(claim_id: str, request: Request):
    _require(request, "ops", "reviewer", "investigator")
    return _rows(
        """
        SELECT event_id, event_type, payload, occurred_at, actor, adjudication_attempt
        FROM adjudication.adjudication_event
        WHERE claim_id = :claim_id
        ORDER BY occurred_at, event_id
        """,
        {"claim_id": claim_id},
    )


@router.get("/ops/reference/{kind}")
def reference(kind: str, request: Request, q: str | None = None, plan_code: str | None = None):
    _require(request, "ops")
    if kind == "members":
        return _rows("SELECT member_id, first_name, last_name, dob::text AS dob, gender FROM claims.member ORDER BY member_id LIMIT 100")
    if kind == "policies":
        return _rows(
            """
            SELECT policy_id, member_id, plan_code, group_number, effective_date::text, termination_date::text, status
            FROM claims.policy ORDER BY policy_id LIMIT 100
            """
        )
    if kind == "providers":
        return _rows(
            """
            SELECT provider_id, npi, name, taxonomy_code, network_status, quality_rating, city, state
            FROM claims.provider ORDER BY name LIMIT 100
            """
        )
    if kind == "benefits":
        return _rows(
            """
            SELECT plan_code, cpt_code, benefit_category, is_covered, requires_prior_auth, policy_section
            FROM claims.plan_benefit
            WHERE CAST(:plan_code AS text) IS NULL OR plan_code = :plan_code
            ORDER BY plan_code, cpt_code LIMIT 200
            """,
            {"plan_code": plan_code},
        )
    if kind == "cpt":
        return _rows(
            """
            SELECT code, description, active FROM claims.ref_cpt
            WHERE CAST(:q AS text) IS NULL OR code ILIKE CAST(:like AS text) OR description ILIKE CAST(:like AS text)
            ORDER BY code LIMIT 50
            """,
            {"q": q, "like": f"%{q}%" if q else None},
        )
    if kind == "icd10":
        return _rows(
            """
            SELECT code, description, billable FROM claims.ref_icd10
            WHERE CAST(:q AS text) IS NULL OR code ILIKE CAST(:like AS text) OR description ILIKE CAST(:like AS text)
            ORDER BY code LIMIT 50
            """,
            {"q": q, "like": f"%{q}%" if q else None},
        )
    raise HTTPException(status_code=404, detail="Unknown reference")


def _release_leases(conn) -> None:
    conn.execute(
        text(
            """
            UPDATE adjudication.review_tasks
            SET status = 'OPEN', assignee = NULL, picked_at = NULL
            WHERE status = 'IN_REVIEW' AND picked_at < now() - interval '30 minutes'
            """
        )
    )


@router.get("/review-tasks")
def list_tasks(request: Request, status: str | None = None, task_type: str | None = None):
    _require(request, "reviewer", "investigator", "ops")
    with portal_engine().begin() as conn:
        _release_leases(conn)
        clauses = ["1 = 1"]
        params: dict = {}
        if status:
            clauses.append("t.status = :status")
            params["status"] = status
        if task_type:
            clauses.append("t.task_type = :task_type")
            params["task_type"] = task_type
        rows = conn.execute(
            text(
                f"""
                SELECT t.task_id, t.claim_id, t.summary, t.risk_score, t.status, t.task_type,
                       t.assignee, t.picked_at, t.created_at,
                       c.member_id, c.total_billed, c.service_from, c.service_to,
                       trim(both ' ' FROM concat_ws(' ', m.first_name, m.last_name)) AS member_name,
                       p.name AS provider_name
                FROM adjudication.review_tasks t
                LEFT JOIN claims.claim c ON c.claim_id = t.claim_id
                LEFT JOIN claims.member m ON m.member_id = c.member_id
                LEFT JOIN claims.provider p ON p.provider_id = c.billing_provider_id
                WHERE {' AND '.join(clauses)}
                ORDER BY t.risk_score DESC NULLS LAST, t.created_at
                """
            ),
            params,
        ).mappings()
        return [_jsonable(dict(row)) for row in rows]


@router.get("/review-tasks/{task_id}")
def read_task(task_id: int, request: Request):
    _require(request, "reviewer", "investigator", "ops")
    with portal_engine().begin() as conn:
        _release_leases(conn)
        row = conn.execute(
            text(
                """
                SELECT task_id, claim_id, summary, risk_score, status, task_type, assignee, picked_at, created_at
                FROM adjudication.review_tasks WHERE task_id = :task_id
                """
            ),
            {"task_id": task_id},
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _jsonable(dict(row))


@router.post("/review-tasks/{task_id}/claim")
def claim_task(task_id: int, request: Request):
    user = _require(request, "reviewer", "investigator")
    assignee = _actor_id(request)
    with portal_engine().begin() as conn:
        current = conn.execute(
            text("SELECT task_type FROM adjudication.review_tasks WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).mappings().first()
        if current is None:
            raise HTTPException(status_code=404, detail="Task not found")
        owner = "reviewer" if current["task_type"] == "REVIEW" else "investigator"
        if user["role"] != owner:
            raise HTTPException(status_code=403, detail="This queue belongs to someone else")
        _release_leases(conn)
        updated = conn.execute(
            text(
                """
                UPDATE adjudication.review_tasks
                SET status = 'IN_REVIEW', assignee = :assignee, picked_at = now()
                WHERE task_id = :task_id AND status = 'OPEN'
                RETURNING task_id, claim_id
                """
            ),
            {"task_id": task_id, "assignee": assignee},
        ).mappings().first()
        if updated is None:
            raise HTTPException(status_code=409, detail="Someone else already took this task")
        _event(conn, updated["claim_id"], "REVIEW_PICKED_UP", assignee, {"assignee": assignee, "task_id": task_id})
    return {"task_id": task_id, "assignee": assignee, "status": "IN_REVIEW"}


def _open_assignment(task_id: int, request: Request, task_type: str) -> tuple[str, int]:
    assignee = _actor_id(request)
    with portal_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT claim_id, summary, status, assignee, task_type
                FROM adjudication.review_tasks WHERE task_id = :task_id
                """
            ),
            {"task_id": task_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if row["task_type"] != task_type or row["status"] != "IN_REVIEW" or row["assignee"] != assignee:
            raise HTTPException(status_code=403, detail="Only the assignee of an open task can decide")
        summary = row["summary"]
        if isinstance(summary, str):
            summary = json.loads(summary)
        attempt = summary.get("adjudication_attempt") if isinstance(summary, dict) else None
        if not attempt:
            attempt = conn.execute(
                text(
                    """
                    SELECT count(*) FROM claims.claim_status_history
                    WHERE claim_id = :claim_id AND to_status = 'VALIDATED'
                    """
                ),
                {"claim_id": row["claim_id"]},
            ).scalar_one()
    return str(row["claim_id"]), max(int(attempt), 1)


def _notify_adjudicator(path: str, payload: dict) -> dict:
    try:
        with httpx.Client(timeout=120) as client:
            response = client.post(f"{ADJUDICATOR}{path}", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Adjudicator is unavailable") from exc
    try:
        body = response.json()
    except json.JSONDecodeError:
        body = {"detail": response.text}
    if response.status_code >= 400:
        detail = body.get("detail") if isinstance(body, dict) else "Adjudicator did not accept the decision"
        if not isinstance(detail, str):
            detail = "Adjudicator did not accept the decision"
        raise HTTPException(status_code=response.status_code, detail=detail)
    return body if isinstance(body, dict) else {"result": body}


def _closed_detail(decision: str, result: dict) -> str:
    status = result.get("status")
    if status == "DECIDED":
        word = "Approved" if decision == "APPROVED" else "Denied" if decision == "DENIED" else "Closed"
        return f"{word}. The adjudicator recorded the final decision."
    if status == "RETURNED_TO_CLAIMANT":
        return "The adjudicator sent the claim back."
    if result.get("result") == "ignored":
        return "The adjudicator had already moved past this step."
    return "The adjudicator accepted the decision."


@router.post("/review-tasks/{task_id}/decision")
def decide_task(task_id: int, body: ReviewDecision, request: Request):
    _require(request, "reviewer")
    if body.decision not in {"APPROVED", "DENIED"}:
        raise HTTPException(status_code=422, detail="Decision must be APPROVED or DENIED")
    claim_id, attempt = _open_assignment(task_id, request, "REVIEW")
    try:
        allowed = float(body.allowed_amount) if body.allowed_amount else 0
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Allowed amount must be a number") from exc
    result = _notify_adjudicator(
        f"/adjudications/{claim_id}/{attempt}/review-decision",
        {
            "decision": body.decision,
            "allowed_amount": allowed,
            "reviewer": _actor_id(request),
            "notes": body.notes,
        },
    )
    recorded = _finish_task(
        task_id,
        request,
        "REVIEW",
        "REVIEW_DECIDED",
        {"decision": body.decision, "allowed_amount": body.allowed_amount, "notes": body.notes, "reviewer": _actor_id(request)},
    )
    recorded["claim_status_unchanged"] = False
    recorded["adjudicator"] = result.get("result")
    recorded["detail"] = _closed_detail(body.decision, result)
    return recorded


@router.post("/review-tasks/{task_id}/investigation")
def investigate_task(task_id: int, body: InvestigationResult, request: Request):
    _require(request, "investigator")
    if body.outcome not in {"CLEARED", "CONFIRMED"}:
        raise HTTPException(status_code=422, detail="Outcome must be CLEARED or CONFIRMED")
    claim_id, attempt = _open_assignment(task_id, request, "INVESTIGATION")
    result = _notify_adjudicator(
        f"/adjudications/{claim_id}/{attempt}/investigation-result",
        {"outcome": body.outcome, "notes": body.notes},
    )
    recorded = _finish_task(
        task_id,
        request,
        "INVESTIGATION",
        "INVESTIGATION_RESULT",
        {"outcome": body.outcome, "notes": body.notes, "investigator": _actor_id(request)},
    )
    recorded["claim_status_unchanged"] = result.get("status") not in {"DECIDED", "RETURNED_TO_CLAIMANT"}
    recorded["adjudicator"] = result.get("result")
    recorded["detail"] = _closed_detail(body.outcome, result)
    return recorded


def _finish_task(task_id: int, request: Request, task_type: str, event_type: str, payload: dict) -> dict:
    assignee = _actor_id(request)
    with portal_engine().begin() as conn:
        updated = conn.execute(
            text(
                """
                UPDATE adjudication.review_tasks
                SET status = 'DONE'
                WHERE task_id = :task_id
                  AND status IN ('IN_REVIEW', 'DONE')
                  AND assignee = :assignee
                  AND task_type = :task_type
                RETURNING claim_id
                """
            ),
            {"task_id": task_id, "assignee": assignee, "task_type": task_type},
        ).mappings().first()
        if updated is None:
            raise HTTPException(status_code=403, detail="Only the assignee of an open task can decide")
        _event(conn, updated["claim_id"], event_type, assignee, payload)
    return {
        "task_id": task_id,
        "recorded": True,
        "claim_status_unchanged": True,
        "detail": "Recorded. The claim status changes when the adjudicator resumes the run.",
    }


def _event(conn, claim_id: str, event_type: str, actor: str, payload: dict) -> None:
    attempt = conn.execute(
        text(
            """
            SELECT count(*) FROM claims.claim_status_history
            WHERE claim_id = :claim_id AND to_status = 'VALIDATED'
            """
        ),
        {"claim_id": claim_id},
    ).scalar_one()
    conn.execute(
        text(
            """
            INSERT INTO adjudication.adjudication_event
                (claim_id, adjudication_attempt, actor, event_type, payload)
            VALUES
                (:claim_id, :attempt, :actor, :event_type, CAST(:payload AS jsonb))
            """
        ),
        {
            "claim_id": claim_id,
            "attempt": max(int(attempt), 1),
            "actor": actor,
            "event_type": event_type,
            "payload": json.dumps(payload),
        },
    )


def _refuse(question: str) -> bool:
    lowered = question.lower()
    phrases = ("clear this", "mark this as clear", "mark as clear", "approve this", "deny this", "change the verdict")
    return any(phrase in lowered for phrase in phrases)


@router.get("/fraud/assessments/{claim_id}")
def read_assessment(claim_id: str, request: Request):
    _require(request, "reviewer", "investigator", "ops")
    rows = _rows(
        """
        SELECT claim_id, model_version, risk_score, band, verdict, confidence, narrative, narrative_source, created_at
        FROM fraud.fraud_assessment
        WHERE claim_id = :claim_id
        ORDER BY created_at DESC LIMIT 1
        """,
        {"claim_id": claim_id},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No fraud assessment for this claim yet")
    memo = _rows(
        "SELECT memo_id, body, created_at FROM fraud.referral_memo WHERE claim_id = :claim_id ORDER BY created_at DESC LIMIT 1",
        {"claim_id": claim_id},
    )
    return {"assessment": rows[0], "referral_memo": memo[0] if memo else None}


@router.post("/fraud/assessments/{claim_id}/ask")
def ask_fraud(claim_id: str, body: AskBody, request: Request):
    user = _require(request, "reviewer", "investigator")
    rows = _rows(
        """
        SELECT model_version, risk_score, band, verdict, narrative
        FROM fraud.fraud_assessment WHERE claim_id = :claim_id
        ORDER BY created_at DESC LIMIT 1
        """,
        {"claim_id": claim_id},
    )
    assessment = rows[0] if rows else None
    if _refuse(body.question):
        answer = "Decisions are made on the review form, not in this assistant."
        tools: list[str] = []
    elif assessment is None:
        answer = "There is no fraud assessment for this claim yet. Decisions are made on the review form, not in this assistant."
        tools = []
    else:
        narrative = assessment["narrative"] if isinstance(assessment["narrative"], dict) else {}
        parts = [part for part in (narrative.get("headline"), narrative.get("summary")) if part]
        if assessment["risk_score"] is not None:
            parts.append(f"Stored risk score {assessment['risk_score']} from {assessment['model_version']}.")
        parts.append("Source: fraud.fraud_assessment. This assistant cannot change the verdict.")
        answer = " ".join(parts) if parts else "The stored assessment has no narrative. Source: fraud.fraud_assessment."
        tools = ["get_assessment"]
    with portal_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO fraud.assistant_log (claim_id, user_id, role, question, answer, tools_used)
                VALUES (:claim_id, :user_id, :role, :question, :answer, CAST(:tools AS jsonb))
                """
            ),
            {
                "claim_id": claim_id,
                "user_id": user["user_id"],
                "role": user["role"],
                "question": body.question,
                "answer": answer,
                "tools": json.dumps(tools),
            },
        )
    return {"answer": answer, "tools_used": tools}


async def _fraud(method: str, path: str, request: Request, payload: dict | None = None) -> tuple[int, object]:
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.request(method, f"{FRAUD}{path}", headers=_payer_headers(request), json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Fraud model service is unavailable") from exc
    try:
        body = response.json()
    except json.JSONDecodeError:
        body = {"detail": response.text}
    return response.status_code, body


async def _probe(name: str, base: str) -> dict:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{base}/health")
        elapsed = round((time.perf_counter() - started) * 1000)
        try:
            body = response.json()
        except json.JSONDecodeError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        up = response.status_code == 200 and body.get("status") == "ok"
        return {
            "name": name,
            "status": "ok" if up else "down",
            "postgres": body.get("postgres"),
            "rabbitmq": body.get("rabbitmq"),
            "latency_ms": elapsed,
        }
    except httpx.HTTPError:
        return {"name": name, "status": "down", "postgres": None, "rabbitmq": None, "latency_ms": None}


@router.get("/ops/health")
async def platform_health(request: Request):
    _require(request, "ops")
    started = time.perf_counter()
    own = await platform_status()
    portal = {
        "name": "Portal",
        "status": own["status"],
        "postgres": own["postgres"],
        "rabbitmq": own["rabbitmq"],
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }
    others = await asyncio.gather(
        _probe("Payer", PAYER),
        _probe("Chatbot", CHATBOT),
        _probe("Adjudicator", ADJUDICATOR),
        _probe("Fraud detection", FRAUD),
    )
    services = [portal, *others]
    up = sum(1 for item in services if item["status"] == "ok")
    healthy = up == len(services) and own["postgres"] == "ok" and own["rabbitmq"] == "ok"
    return {
        "checked_at": datetime.now().astimezone().isoformat(),
        "postgres": own["postgres"],
        "rabbitmq": own["rabbitmq"],
        "up": up,
        "total": len(services),
        "status": "ok" if healthy else "error",
        "services": services,
    }


@router.get("/ops/fraud-model")
async def fraud_model(request: Request):
    _require(request, "ops")
    status, body = await _fraud("GET", "/model/latest", request)
    return _pass(status, body)


@router.post("/ops/fraud-model/train")
async def fraud_model_train(request: Request):
    _require(request, "ops")
    status, body = await _fraud("POST", "/model/train", request)
    return _pass(status, body)


@router.post("/ops/fraud-model/select")
async def fraud_model_select(body: TechniqueBody, request: Request):
    _require(request, "ops")
    status, payload = await _fraud("POST", "/model/select", request, {"technique": body.technique})
    return _pass(status, payload)
