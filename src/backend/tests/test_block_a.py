"""Block A proof tests that need Postgres. RabbitMQ is used only for the replay path."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from contracts.models import ClaimSubmitted, DocumentRef, SubmissionRequest
from db_url import database_url, document_root
from payer_service.app.consumer import on_message
from payer_service.app.db import payer_engine
from payer_service.app.errors import Conflict
from payer_service.app.extract import read_fields
from payer_service.app.pipeline import prepare_draft, process_message
from payer_service.app.repository import get_claim, transition
from payer_service.dlq import require_reason
from portal.app.db import portal_engine
from portal.app.intake import DuplicateSubmission, accept_submission
from tests.pdf_text import text_pdf

ROOT = Path(__file__).resolve().parents[3]
TODAY = date(2026, 10, 28)


class _Channel:
    def __init__(self):
        self.sent: list[tuple[str, str, dict]] = []

    async def get_exchange(self, name: str):
        self.exchange = name
        return self

    async def publish(self, message, routing_key: str):
        self.sent.append((self.exchange, routing_key, dict(message.headers or {})))


class _Msg:
    def __init__(self, body: bytes, headers: dict | None = None, message_id: str | None = None):
        self.body = body
        self.headers = headers or {}
        self.message_id = message_id or str(uuid4())
        self.correlation_id = None
        self.acked = False

    async def ack(self):
        self.acked = True


def _fixture(name: str) -> SubmissionRequest:
    return SubmissionRequest.model_validate(json.loads((ROOT / "data" / "fixtures" / name).read_text()))


def _submit(name: str, *, suffix: str, pdf: bytes | None = None) -> str:
    request = _fixture(name)
    files = []
    if pdf is not None:
        files.append(("note.pdf", pdf, "medical_record"))
    return accept_submission(
        channel="portal",
        submitter_type=request.submitter_type,
        submitter_id=request.submitter_id,
        claim=request.claim,
        files=files,
        submission_id=f"{request.submission_id or 'SUB'}-{suffix}" if False else f"SUB-TEST-{suffix}",
    )


def _process(submission_id: str) -> str | None:
    body = (document_root() / submission_id / "message.json").read_bytes()
    return process_message(body, payer_engine(), today=TODAY)


def test_duplicate_submission_is_rejected_before_a_second_row():
    submission_id = f"SUB-DUP-{uuid4().hex[:8]}"
    request = _fixture("clean.json")
    accept_submission(
        channel="portal",
        submitter_type=request.submitter_type,
        submitter_id=request.submitter_id,
        claim=request.claim,
        files=[],
        submission_id=submission_id,
    )
    with pytest.raises(DuplicateSubmission):
        accept_submission(
            channel="portal",
            submitter_type=request.submitter_type,
            submitter_id=request.submitter_id,
            claim=request.claim,
            files=[],
            submission_id=submission_id,
        )
    with portal_engine().connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM portal.submission_log WHERE submission_id = :submission_id"),
            {"submission_id": submission_id},
        ).scalar_one()
    assert count == 1


def test_redelivery_creates_one_claim_and_three_outcomes():
    clean_id = _submit("clean.json", suffix=f"clean-{uuid4().hex[:6]}", pdf=text_pdf(["Visit note"]))
    pending_id = _submit("pending.json", suffix=f"pending-{uuid4().hex[:6]}")
    rejected_id = _submit("rejected.json", suffix=f"rejected-{uuid4().hex[:6]}")
    clean_claim = _process(clean_id)
    assert clean_claim is not None
    assert _process(clean_id) is None
    pending_claim = _process(pending_id)
    rejected_claim = _process(rejected_id)
    with payer_engine().connect() as conn:
        rows = {
            row["submission_id"]: row["status"]
            for row in conn.execute(
                text(
                    """
                    SELECT submission_id, status FROM claims.claim
                    WHERE submission_id IN (:clean_id, :pending_id, :rejected_id)
                    """
                ),
                {"clean_id": clean_id, "pending_id": pending_id, "rejected_id": rejected_id},
            ).mappings()
        }
        count = conn.execute(
            text("SELECT count(*) FROM claims.claim WHERE submission_id = :submission_id"),
            {"submission_id": clean_id},
        ).scalar_one()
        lines = conn.execute(
            text("SELECT count(*) FROM claims.claim_line WHERE claim_id = :claim_id"),
            {"claim_id": clean_claim},
        ).scalar_one()
        pending_lines = conn.execute(
            text("SELECT count(*) FROM claims.claim_line WHERE claim_id = :claim_id"),
            {"claim_id": pending_claim},
        ).scalar_one()
        ready = conn.execute(
            text(
                """
                SELECT payload->>'adjudication_attempt' FROM claims.outbox
                WHERE claim_id = :claim_id AND routing_key = 'claim.ready_for_adjudication'
                """
            ),
            {"claim_id": clean_claim},
        ).scalar_one()
    assert count == 1
    assert rows == {clean_id: "VALIDATED", pending_id: "PENDING_INFO", rejected_id: "REJECTED"}
    assert lines == 2
    assert pending_lines == 0
    assert ready == "1"


def test_answer_revalidates_and_a_second_answer_is_rejected():
    submission_id = _submit("pending.json", suffix=f"answer-{uuid4().hex[:6]}")
    claim_id = _process(submission_id)
    with payer_engine().begin() as conn:
        issue_id = conn.execute(
            text(
                """
                SELECT issue_id FROM claims.claim_issue
                WHERE claim_id = :claim_id AND issue_code = 'INVALID_CODE' AND status = 'open'
                """
            ),
            {"claim_id": claim_id},
        ).scalar_one()
        from payer_service.app.repository import answer_issue

        result = answer_issue(
            conn,
            claim_id,
            int(issue_id),
            "83036",
            "PRV-0042:phase6",
            "use 83036",
            "PRV-0042",
            today=TODAY,
        )
    assert result["claim_status"] == "VALIDATED"
    with payer_engine().connect() as conn:
        status = conn.execute(
            text("SELECT status FROM claims.claim WHERE claim_id = :claim_id"),
            {"claim_id": claim_id},
        ).scalar_one()
        amendments = conn.execute(
            text("SELECT count(*) FROM claims.claim_amendment WHERE claim_id = :claim_id"),
            {"claim_id": claim_id},
        ).scalar_one()
        ready = conn.execute(
            text(
                """
                SELECT count(*) FROM claims.outbox
                WHERE claim_id = :claim_id AND routing_key = 'claim.ready_for_adjudication'
                """
            ),
            {"claim_id": claim_id},
        ).scalar_one()
        attempt = conn.execute(
            text(
                """
                SELECT payload->>'adjudication_attempt' FROM claims.outbox
                WHERE claim_id = :claim_id AND routing_key = 'claim.ready_for_adjudication'
                """
            ),
            {"claim_id": claim_id},
        ).scalar_one()
    assert status == "VALIDATED"
    assert amendments == 1
    assert ready == 1
    assert attempt == "1"
    from fastapi import HTTPException
    from payer_service.app.api import AnswerBody, post_answer

    with pytest.raises(HTTPException) as raised:
        post_answer(
            claim_id,
            int(issue_id),
            AnswerBody(value="83036", conversation_id="PRV-0042:again", claimant_text="again", submitter_id="PRV-0042"),
        )
    assert raised.value.status_code == 422


def test_transition_conflict_when_two_callers_race():
    submission_id = _submit("pending.json", suffix=f"race-{uuid4().hex[:6]}")
    claim_id = _process(submission_id)
    with payer_engine().begin() as conn:
        conn.execute(
            text("UPDATE claims.claim SET respond_by = :respond_by WHERE claim_id = :claim_id"),
            {"respond_by": datetime.now(timezone.utc) - timedelta(days=1), "claim_id": claim_id},
        )
    engine = payer_engine()
    holder: dict = {}

    def other():
        with engine.connect() as second:
            tx2 = second.begin()
            try:
                transition(second, claim_id, "PENDING_INFO", "REJECTED", "sweeper", "INFO_TIMEOUT", "deadline")
                tx2.commit()
                holder["result"] = "applied"
            except Conflict as exc:
                tx2.rollback()
                holder["result"] = exc

    import threading

    with engine.connect() as first:
        tx1 = first.begin()
        first.execute(
            text("SELECT status FROM claims.claim WHERE claim_id = :claim_id FOR UPDATE"),
            {"claim_id": claim_id},
        )
        thread = threading.Thread(target=other)
        thread.start()
        threading.Event().wait(0.4)
        transition(first, claim_id, "PENDING_INFO", "REJECTED", "ops:test", "INFO_TIMEOUT", "answer side lost the race")
        tx1.commit()
        thread.join(timeout=5)
    assert isinstance(holder["result"], Conflict)
    with payer_engine().connect() as conn:
        status = conn.execute(
            text("SELECT status FROM claims.claim WHERE claim_id = :claim_id"),
            {"claim_id": claim_id},
        ).scalar_one()
    assert status == "REJECTED"


def test_malformed_message_is_dead_lettered_with_intake_error():
    channel = _Channel()
    message = _Msg(b"not-json", message_id=str(uuid4()))

    async def run():
        await on_message(message, channel)

    asyncio.run(run())
    assert message.acked
    assert channel.sent[0][0] == "claims.dlx"
    with payer_engine().connect() as conn:
        row = conn.execute(
            text("SELECT error_class FROM claims.intake_error WHERE message_id = :message_id"),
            {"message_id": message.message_id},
        ).first()
    assert row is not None


def test_three_transient_failures_then_dlq(monkeypatch):
    def boom(body, engine, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("payer_service.app.consumer.process_message", boom)
    monkeypatch.setattr("payer_service.app.consumer.remember_failure", lambda *args, **kwargs: None)
    channel = _Channel()

    async def deliver(attempt: int):
        message = _Msg(b"{}", {"x-attempt": attempt}, message_id=str(uuid4()))
        await on_message(message, channel)
        return message

    async def run():
        first = await deliver(1)
        second = await deliver(2)
        third = await deliver(3)
        return first, second, third

    first, second, third = asyncio.run(run())
    assert all(message.acked for message in (first, second, third))
    assert [item[1] for item in channel.sent] == [
        "payer.claim_submitted.retry.10s",
        "payer.claim_submitted.retry.60s",
        "payer.claim_submitted",
    ]
    assert channel.sent[-1][0] == "claims.dlx"


def test_replay_without_reason_refuses():
    with pytest.raises(SystemExit) as raised:
        require_reason(None, "ops:ravi")
    assert raised.value.code == 2
    with pytest.raises(SystemExit):
        require_reason("   ", "ops:ravi")


def test_extraction_cache_and_unconfirmed_quote(monkeypatch):
    calls = {"n": 0}

    def counting(pages, *, cpt_codes, icd10):
        calls["n"] += 1
        return read_fields(pages, cpt_codes=cpt_codes, icd10=icd10)

    pdf = text_pdf(
        [
            "CMS-1500 claim form",
            "member_id: MBR-100231",
            "first_name: Jane",
            "last_name: Doe",
            "dob: 1984-03-12",
            "billing_npi: 1234567890",
            "billing_name: Lakeside Family Clinic",
        ]
    )
    path = document_root() / f"extract-{uuid4().hex[:8]}.pdf"
    path.write_bytes(pdf)
    message = ClaimSubmitted(
        schema_version="1.0",
        message_id=uuid4(),
        submission_id=f"SUB-EXT-{uuid4().hex[:8]}",
        submitted_at=datetime.now(timezone.utc),
        channel="email",
        submitter={"type": "provider", "id": "email-drop"},
        extraction_required=True,
        claim=None,
        documents=[
            DocumentRef(
                document_id=f"DOC-{uuid4().hex[:8]}",
                doc_type="claim_form",
                content_type="application/pdf",
                storage_uri=path.resolve().as_uri(),
                sha256=__import__("hashlib").sha256(pdf).hexdigest(),
            )
        ],
    )
    body = message.model_dump_json().encode()
    # prepare twice through process of the same bytes after a submission row exists
    from portal.app.intake import accept_submission as accept

    # The message file is what process_message reads. Write it the way the portal does,
    # but this case is document intake, so call prepare_draft directly.
    draft, unconfirmed = prepare_draft(message, payer_engine(), reader=counting)
    prepare_draft(message, payer_engine(), reader=counting)
    assert calls["n"] == 1
    assert any(path == "billing_provider.npi" for path, _message in unconfirmed)
    assert draft.billing_provider is not None
    del body, accept


def test_append_only_blocks_owner_and_payer_app():
    with payer_engine().connect() as conn:
        row_id = conn.execute(text("SELECT id FROM claims.claim_status_history LIMIT 1")).scalar()
    if row_id is None:
        pytest.skip("no history row")
    with pytest.raises(DBAPIError):
        with payer_engine().begin() as conn:
            conn.execute(
                text("UPDATE claims.claim_status_history SET reason = 'changed' WHERE id = :id"),
                {"id": row_id},
            )
    from sqlalchemy import create_engine

    owner = create_engine(database_url())
    with pytest.raises(DBAPIError):
        with owner.begin() as conn:
            conn.execute(
                text("UPDATE claims.claim_status_history SET reason = 'changed' WHERE id = :id"),
                {"id": row_id},
            )
    owner.dispose()


def test_reference_snapshot_survives_a_later_policy_edit_and_audit_fails_closed():
    submission_id = _submit("clean.json", suffix=f"snap-{uuid4().hex[:6]}")
    claim_id = _process(submission_id)
    with payer_engine().connect() as conn:
        before = conn.execute(
            text("SELECT reference_snapshot FROM claims.claim WHERE claim_id = :claim_id"),
            {"claim_id": claim_id},
        ).scalar_one()
    from sqlalchemy import create_engine

    owner = create_engine(database_url())
    with owner.begin() as conn:
        conn.execute(text("UPDATE claims.policy SET group_number = 'GRP-EDITED' WHERE policy_id = 'POL-100231'"))
    with payer_engine().connect() as conn:
        after = conn.execute(
            text("SELECT reference_snapshot FROM claims.claim WHERE claim_id = :claim_id"),
            {"claim_id": claim_id},
        ).scalar_one()
    with owner.begin() as conn:
        conn.execute(text("UPDATE claims.policy SET group_number = 'GRP-7781' WHERE policy_id = 'POL-100231'"))
    owner.dispose()
    assert before == after
    assert before["policy"]["group_number"] == "GRP-7781"

    def boom(conn, **kwargs):
        raise RuntimeError("audit insert failed")

    with pytest.raises(RuntimeError, match="audit insert failed"):
        with payer_engine().begin() as conn:
            get_claim(conn, claim_id, {"actor_type": "service", "actor_id": "test", "actor_role": "service"}, audit_fn=boom)


def test_audit_trail_orders_the_pending_claim_story():
    submission_id = _submit("pending.json", suffix=f"trail-{uuid4().hex[:6]}")
    claim_id = _process(submission_id)
    with payer_engine().begin() as conn:
        issue_id = conn.execute(
            text("SELECT issue_id FROM claims.claim_issue WHERE claim_id = :claim_id AND status = 'open'"),
            {"claim_id": claim_id},
        ).scalar_one()
        from payer_service.app.repository import answer_issue

        answer_issue(conn, claim_id, int(issue_id), "83036", "PRV-0042:trail", "corrected", "PRV-0042", today=TODAY)
        get_claim(conn, claim_id, {"actor_type": "service", "actor_id": "portal", "actor_role": "service", "correlation_id": submission_id})
        trail = [
            row["source"]
            for row in conn.execute(
                text(
                    """
                    SELECT source FROM claims.claim_audit_trail
                    WHERE claim_id = :claim_id
                    ORDER BY occurred_at, source
                    """
                ),
                {"claim_id": claim_id},
            ).mappings()
        ]
    assert "claim_status_history" in trail
    assert "claim_issue" in trail
    assert "claim_amendment" in trail
    assert trail.index("claim_issue") < trail.index("claim_amendment")


def test_reading_a_claim_writes_an_audit_row():
    submission_id = _submit("clean.json", suffix=f"read-{uuid4().hex[:6]}")
    claim_id = _process(submission_id)
    with payer_engine().begin() as conn:
        before = conn.execute(
            text("SELECT count(*) FROM claims.audit_event WHERE claim_id = :claim_id AND action = 'claim.read'"),
            {"claim_id": claim_id},
        ).scalar_one()
        body = get_claim(
            conn,
            claim_id,
            {"actor_type": "service", "actor_id": "adjudicator", "actor_role": "service", "correlation_id": submission_id},
        )
        after = conn.execute(
            text("SELECT count(*) FROM claims.audit_event WHERE claim_id = :claim_id AND action = 'claim.read'"),
            {"claim_id": claim_id},
        ).scalar_one()
    assert body is not None
    assert after == before + 1
