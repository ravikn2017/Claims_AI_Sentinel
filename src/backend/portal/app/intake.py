"""Accept a submission, store files, and write one pending outbox row."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from contracts.models import ClaimDraft, ClaimSubmitted, DocumentRef, ProfessionalClaim, SubmissionRequest, Submitter
from db_url import document_root
from portal.app.db import portal_engine

MAX_BYTES = 10 * 1024 * 1024


class DuplicateSubmission(Exception):
    def __init__(self, submission_id: str):
        self.submission_id = submission_id


class ShapeError(Exception):
    def __init__(self, message: str):
        self.message = message


def new_submission_id() -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"SUB-{day}-{secrets.randbelow(1_000_000):06d}"


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _exists(submission_id: str) -> bool:
    with portal_engine().connect() as conn:
        found = conn.execute(
            text("SELECT 1 FROM portal.submission_log WHERE submission_id = :submission_id"),
            {"submission_id": submission_id},
        ).first()
    return found is not None


def accept_submission(
    *,
    channel: str,
    submitter_type: str,
    submitter_id: str,
    claim: ProfessionalClaim | None,
    files: list[tuple[str, bytes, str]],
    submission_id: str | None = None,
    extraction_required: bool = False,
) -> str:
    if extraction_required and claim is not None:
        raise ShapeError("An email or PDF submission cannot also include a claim form")
    if not extraction_required and claim is None:
        raise ShapeError("A claim form is required")
    if channel not in {"portal", "email", "api"}:
        raise ShapeError("Unknown channel")
    if submission_id and _exists(submission_id):
        raise DuplicateSubmission(submission_id)

    chosen = submission_id or new_submission_id()
    while not submission_id and _exists(chosen):
        chosen = new_submission_id()

    root = document_root() / chosen
    root.mkdir(parents=True, exist_ok=True)
    documents: list[DocumentRef] = []
    for index, (filename, content, doc_type) in enumerate(files, start=1):
        if len(content) > MAX_BYTES:
            raise ShapeError("File is larger than 10 MB")
        if not filename.lower().endswith(".pdf") and not content.startswith(b"%PDF"):
            raise ShapeError("Only PDF files are accepted")
        safe_name = Path(filename).name or f"document-{index}.pdf"
        target = root / safe_name
        target.write_bytes(content)
        documents.append(
            DocumentRef(
                document_id=f"DOC-{chosen}-{index}",
                doc_type=doc_type,
                content_type="application/pdf",
                storage_uri=target.resolve().as_uri(),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )

    message = ClaimSubmitted(
        schema_version="1.0",
        message_id=uuid4(),
        submission_id=chosen,
        submitted_at=datetime.now(timezone.utc),
        channel=channel,  # type: ignore[arg-type]
        submitter=Submitter(type=submitter_type, id=submitter_id),  # type: ignore[arg-type]
        extraction_required=extraction_required,
        claim=ClaimDraft.from_professional(claim) if claim else None,
        documents=documents,
    )
    body = message.model_dump(mode="json")
    encoded = _canonical(body)
    (root / "message.json").write_bytes(encoded)
    try:
        with portal_engine().begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO portal.submission_log (
                        submission_id, channel, submitter_type, submitter_id,
                        payload_sha256, publish_status
                    )
                    VALUES (
                        :submission_id, :channel, :submitter_type, :submitter_id,
                        :payload_sha256, 'pending'
                    )
                    """
                ),
                {
                    "submission_id": chosen,
                    "channel": channel,
                    "submitter_type": submitter_type,
                    "submitter_id": submitter_id,
                    "payload_sha256": hashlib.sha256(encoded).hexdigest(),
                },
            )
    except IntegrityError as exc:
        raise DuplicateSubmission(chosen) from exc
    return chosen


def parse_request(payload: dict) -> SubmissionRequest:
    try:
        return SubmissionRequest.model_validate(payload)
    except ValidationError as exc:
        raise ShapeError("Submission does not match the claim shape") from exc
