"""Review and investigation tasks. Publishing a task is an insert."""

from __future__ import annotations

import json

from sqlalchemy import text

from adjudicator.db import adjudicator_engine


def thread_id(claim_id: str, attempt: int) -> str:
    return f"{claim_id}:{attempt}"


def ensure_task(claim_id: str, attempt: int, task_type: str, summary: dict, risk: float) -> None:
    body = {**summary, "thread_id": thread_id(claim_id, attempt), "adjudication_attempt": attempt}
    with adjudicator_engine().begin() as conn:
        found = conn.execute(
            text(
                """
                SELECT 1 FROM adjudication.review_tasks
                WHERE claim_id = :claim_id
                  AND task_type = :task_type
                  AND summary->>'thread_id' = :thread_id
                """
            ),
            {"claim_id": claim_id, "task_type": task_type, "thread_id": thread_id(claim_id, attempt)},
        ).first()
        if found:
            return
        conn.execute(
            text(
                """
                INSERT INTO adjudication.review_tasks (claim_id, summary, risk_score, status, task_type)
                VALUES (:claim_id, CAST(:summary AS jsonb), :risk, 'OPEN', :task_type)
                """
            ),
            {
                "claim_id": claim_id,
                "summary": json.dumps(body),
                "risk": risk,
                "task_type": task_type,
            },
        )


def mark_done(claim_id: str, attempt: int, task_type: str) -> None:
    with adjudicator_engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE adjudication.review_tasks
                SET status = 'DONE'
                WHERE claim_id = :claim_id
                  AND task_type = :task_type
                  AND summary->>'thread_id' = :thread_id
                  AND status <> 'DONE'
                """
            ),
            {"claim_id": claim_id, "task_type": task_type, "thread_id": thread_id(claim_id, attempt)},
        )
