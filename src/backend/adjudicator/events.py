"""Append-only adjudication events and the AdjudicationDecided outbox."""

from __future__ import annotations

import json

from sqlalchemy import text

from adjudicator.db import adjudicator_engine
from adjudicator.tools.payer import run_actor


def _dumps(value) -> str:
    return json.dumps(value)


def record_event(
    claim_id: str,
    attempt: int,
    correlation_id: str,
    event_type: str,
    payload: dict,
    *,
    once: bool = False,
    versions: dict | None = None,
) -> None:
    actor = run_actor(claim_id, attempt)
    with adjudicator_engine().begin() as conn:
        if once:
            params = {
                "claim_id": claim_id,
                "attempt": attempt,
                "event_type": event_type,
            }
            sql = """
                SELECT 1 FROM adjudication.adjudication_event
                WHERE claim_id = :claim_id
                  AND adjudication_attempt = :attempt
                  AND event_type = :event_type
            """
            agent = payload.get("agent")
            if event_type == "AGENT_RESULT" and agent:
                sql += " AND payload->>'agent' = :agent"
                params["agent"] = agent
            if conn.execute(text(sql), params).first():
                return
        conn.execute(
            text(
                """
                INSERT INTO adjudication.adjudication_event (
                    claim_id, adjudication_attempt, correlation_id, actor, event_type, payload, versions
                )
                VALUES (
                    :claim_id, :attempt, :correlation_id, :actor, :event_type,
                    CAST(:payload AS jsonb), CAST(:versions AS jsonb)
                )
                """
            ),
            {
                "claim_id": claim_id,
                "attempt": attempt,
                "correlation_id": correlation_id or None,
                "actor": actor,
                "event_type": event_type,
                "payload": _dumps(payload),
                "versions": _dumps(versions) if versions is not None else None,
            },
        )


def emit_decided(
    claim_id: str,
    attempt: int,
    decision: str,
    allowed_amount: float,
    reasons: list[str],
    correlation_id: str,
) -> None:
    payload = {
        "event": "AdjudicationDecided",
        "claim_id": claim_id,
        "decision": decision,
        "allowed_amount": allowed_amount,
        "reasons": reasons,
        "correlation_id": correlation_id,
    }
    with adjudicator_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO adjudication.outbox (message_id, routing_key, claim_id, payload)
                VALUES (:message_id, 'AdjudicationDecided', :claim_id, CAST(:payload AS jsonb))
                ON CONFLICT (message_id) DO NOTHING
                """
            ),
            {
                "message_id": f"{claim_id}:{attempt}:AdjudicationDecided",
                "claim_id": claim_id,
                "payload": _dumps(payload),
            },
        )
