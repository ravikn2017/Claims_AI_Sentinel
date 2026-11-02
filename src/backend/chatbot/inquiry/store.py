"""Inquiry log. Separate from the claim conversation."""

from __future__ import annotations

from sqlalchemy import text

from chatbot.db import chatbot_engine


def ensure_conversation(member_id: str) -> None:
    with chatbot_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO chatbot.inquiry_conversation (member_id)
                VALUES (:member_id)
                ON CONFLICT (member_id) DO NOTHING
                """
            ),
            {"member_id": member_id},
        )


def list_messages(member_id: str) -> list[dict]:
    with chatbot_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT role, text AS body
                FROM chatbot.inquiry_message
                WHERE member_id = :member_id
                ORDER BY message_id
                """
            ),
            {"member_id": member_id},
        ).mappings()
    return [{"role": row["role"], "text": row["body"]} for row in rows]


def add_turn(member_id: str, user_text: str, reply: str) -> None:
    with chatbot_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO chatbot.inquiry_message (member_id, role, text)
                VALUES (:member_id, 'user', :user_text), (:member_id, 'assistant', :reply)
                """
            ),
            {"member_id": member_id, "user_text": user_text, "reply": reply},
        )
