"""Conversation log. The chatbot service is the only writer."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from chatbot.db import chatbot_engine


def conversation_id_for(submitter_id: str, claim_id: str) -> str:
    return f"{submitter_id}:{claim_id}"


def ensure_conversation(claim_id: str, submitter_id: str, respond_by: datetime | None) -> str:
    conversation_id = conversation_id_for(submitter_id, claim_id)
    with chatbot_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO chatbot.conversation (claim_id, submitter_id, conversation_id, respond_by)
                VALUES (:claim_id, :submitter_id, :conversation_id, :respond_by)
                ON CONFLICT (claim_id) DO NOTHING
                """
            ),
            {
                "claim_id": claim_id,
                "submitter_id": submitter_id,
                "conversation_id": conversation_id,
                "respond_by": respond_by,
            },
        )
    return conversation_id


def list_messages(claim_id: str) -> list[dict]:
    with chatbot_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT role, text AS body, issue_id
                FROM chatbot.message
                WHERE claim_id = :claim_id
                ORDER BY message_id
                """
            ),
            {"claim_id": claim_id},
        ).mappings()
    messages = []
    for row in rows:
        message = {"role": row["role"], "text": row["body"]}
        if row["issue_id"] is not None:
            message["issue_id"] = int(row["issue_id"])
        messages.append(message)
    return messages


def has_assistant(claim_id: str) -> bool:
    with chatbot_engine().connect() as conn:
        found = conn.execute(
            text(
                """
                SELECT 1 FROM chatbot.message
                WHERE claim_id = :claim_id AND role = 'assistant'
                LIMIT 1
                """
            ),
            {"claim_id": claim_id},
        ).first()
    return found is not None


def add_message(claim_id: str, role: str, body: str, issue_id: int | None = None) -> None:
    with chatbot_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO chatbot.message (claim_id, role, text, issue_id)
                VALUES (:claim_id, :role, :body, :issue_id)
                """
            ),
            {"claim_id": claim_id, "role": role, "body": body, "issue_id": issue_id},
        )


def add_opening_once(claim_id: str, body: str, issue_id: int | None) -> bool:
    """Insert the first assistant message. A repeat delivery does not add another."""
    with chatbot_engine().begin() as conn:
        conn.execute(
            text("SELECT claim_id FROM chatbot.conversation WHERE claim_id = :claim_id FOR UPDATE"),
            {"claim_id": claim_id},
        )
        exists = conn.execute(
            text(
                """
                SELECT 1 FROM chatbot.message
                WHERE claim_id = :claim_id AND role = 'assistant'
                LIMIT 1
                """
            ),
            {"claim_id": claim_id},
        ).first()
        if exists is not None:
            return False
        conn.execute(
            text(
                """
                INSERT INTO chatbot.message (claim_id, role, text, issue_id)
                VALUES (:claim_id, 'assistant', :body, :issue_id)
                """
            ),
            {"claim_id": claim_id, "body": body, "issue_id": issue_id},
        )
    return True
