"""One inquiry turn. Reads the payer service and does not change a claim."""

from __future__ import annotations

from chatbot.errors import ChatError
from chatbot.inquiry.graph import run_turn
from chatbot.inquiry.store import add_turn, ensure_conversation, list_messages


def _require_member(member_id: str, actor: dict) -> None:
    if actor.get("actor_role") != "member" or actor.get("actor_id") != member_id:
        raise ChatError(403, "This conversation belongs to another member")


def _payload(member_id: str) -> dict:
    return {"member_id": member_id, "messages": list_messages(member_id)}


def read_inquiry(member_id: str, actor: dict) -> dict:
    _require_member(member_id, actor)
    ensure_conversation(member_id)
    return _payload(member_id)


def post_inquiry(member_id: str, text: str, actor: dict) -> dict:
    _require_member(member_id, actor)
    message = text.strip()
    if not message:
        raise ChatError(400, "Message is empty")
    ensure_conversation(member_id)
    result = run_turn(
        {
            "member_id": member_id,
            "actor": actor,
            "user_text": message,
            "history": list_messages(member_id),
        }
    )
    reply = (result.get("reply") or "").strip() or "I could not answer that from the information on file."
    add_turn(member_id, message, reply)
    return _payload(member_id)
