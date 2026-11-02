"""Turn one claim.submitted message into a draft, then one claim row."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from urllib.parse import unquote

from pydantic import ValidationError

from contracts.models import ClaimDraft, ClaimSubmitted
from payer_service.app.errors import DuplicateClaim, PermanentError, TransientError
from payer_service.app.extract import EXTRACTOR_VERSION, extract_document, field_result, merge_drafts, read_fields
from payer_service.app.repository import (
    cached_extraction,
    claim_exists,
    load_reference,
    record_intake_error,
    save_extraction,
    timely_filing_days,
    write_intake,
)
from payer_service.app.rules import validate

def uri_to_path(storage_uri: str) -> Path:
    if storage_uri.startswith("file://"):
        return Path(unquote(storage_uri[len("file://") :]))
    return Path(storage_uri)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_document(storage_uri: str, expected: str) -> Path:
    path = uri_to_path(storage_uri)
    if not path.is_file():
        raise TransientError("document store unreachable")
    actual = file_sha256(path)
    if actual != expected:
        raise PermanentError("sha256 does not match the stored file")
    return path


def parse_contract(body: bytes) -> ClaimSubmitted:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PermanentError("body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise PermanentError("body is not valid JSON")
    try:
        return ClaimSubmitted.model_validate(payload)
    except ValidationError as exc:
        raise PermanentError("message failed the contract schema") from exc


def peek_submission_id(body: bytes) -> str | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        value = payload.get("submission_id")
        return value if isinstance(value, str) else None
    return None


def prepare_draft(message: ClaimSubmitted, engine, *, reader=None) -> tuple[ClaimDraft, list[tuple[str, str]]]:
    if not message.extraction_required:
        for document in message.documents:
            verify_document(document.storage_uri, document.sha256)
        if message.claim is None:
            raise PermanentError("claim is required when extraction_required is false")
        return message.claim, []

    drafts: list[ClaimDraft] = []
    unconfirmed: list[tuple[str, str]] = []
    with engine.connect() as conn:
        reference = load_reference(conn)
    for document in message.documents:
        path = verify_document(document.storage_uri, document.sha256)
        with engine.connect() as conn:
            cached = cached_extraction(conn, document.document_id, document.sha256, EXTRACTOR_VERSION)
        if cached:
            drafts.append(ClaimDraft.model_validate(cached["draft"]))
            unconfirmed.extend(tuple(item) for item in cached.get("unconfirmed", []))
            continue
        extraction = extract_document(
            path,
            cpt_codes=reference.cpt_codes,
            icd10=reference.icd10,
            reader=reader or read_fields,
        )
        result = {
            "draft": extraction.draft.model_dump(mode="json"),
            "unconfirmed": [list(item) for item in extraction.unconfirmed],
            "fields": [field_result(item) for item in extraction.fields],
        }
        with engine.begin() as conn:
            save_extraction(conn, document.document_id, document.sha256, EXTRACTOR_VERSION, extraction.doc_class, result)
        drafts.append(extraction.draft)
        unconfirmed.extend(extraction.unconfirmed)
    if not drafts:
        return ClaimDraft(), unconfirmed
    return merge_drafts(drafts), unconfirmed


def process_message(body: bytes, engine, *, today: date | None = None, reader=None) -> str | None:
    """Write the claim. Returns claim_id, or None when the submission was already stored.

    Raises PermanentError or TransientError. DuplicateClaim is treated as success.
    """
    message = parse_contract(body)
    with engine.connect() as conn:
        if claim_exists(conn, message.submission_id):
            return None
    draft, unconfirmed = prepare_draft(message, engine, reader=reader)
    try:
        with engine.begin() as conn:
            if claim_exists(conn, message.submission_id):
                return None
            reference = load_reference(conn)
            outcome = validate(
                draft,
                reference,
                unconfirmed=unconfirmed,
                today=today,
                timely_days=timely_filing_days(),
            )
            return write_intake(conn, message, draft, outcome)
    except DuplicateClaim:
        return None


def remember_failure(engine, message_id: str | None, body: bytes, error_class: str, error: str, attempts: int) -> None:
    if not message_id:
        return
    try:
        with engine.begin() as conn:
            record_intake_error(conn, message_id, peek_submission_id(body), error_class, error, attempts)
    except Exception:
        return
