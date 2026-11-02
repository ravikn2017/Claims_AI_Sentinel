"""One graph run per claimant message. The payer service still decides the claim."""

from __future__ import annotations

from chatbot.errors import ChatError
from chatbot.graph.graph_builder import run_turn
from chatbot.store import add_message, add_opening_once, ensure_conversation, has_assistant, list_messages
from chatbot.tools.payer import detail_of, get_claim

SERVICE_ACTOR = {
    "actor_type": "service",
    "actor_id": "chatbot",
    "actor_role": "service",
    "correlation_id": "",
}


def _require_claim(claim_id: str, submitter_id: str, actor: dict) -> dict:
    status, claim = get_claim(claim_id, actor)
    if status == 404:
        raise ChatError(404, "Claim not found")
    if status != 200:
        raise ChatError(503, detail_of(claim) or "Payer service is unavailable")
    if claim.get("submitter_id") != submitter_id:
        raise ChatError(403, "This conversation does not belong to the claim's submitter")
    return claim


def _payload(claim_id: str) -> dict:
    return {"claim_id": claim_id, "messages": list_messages(claim_id)}


def _issue_id(result: dict) -> int | None:
    proposal = result.get("proposal") or {}
    issue_id = proposal.get("issue_id")
    if issue_id is None:
        return None
    return int(issue_id)


def ensure_opening(claim_id: str, submitter_id: str, actor: dict) -> dict:
    claim = _require_claim(claim_id, submitter_id, actor)
    ensure_conversation(claim_id, submitter_id, claim.get("respond_by"))
    if has_assistant(claim_id) or claim.get("status") != "PENDING_INFO":
        return _payload(claim_id)
    result = run_turn(
        {
            "claim_id": claim_id,
            "submitter_id": submitter_id,
            "conversation_id": f"{submitter_id}:{claim_id}",
            "actor": actor,
            "user_text": None,
        }
    )
    add_opening_once(claim_id, (result.get("reply") or "").strip() or "What should I correct on this claim?", _issue_id(result))
    return _payload(claim_id)


def post_message(claim_id: str, submitter_id: str, text: str, actor: dict) -> dict:
    claim = _require_claim(claim_id, submitter_id, actor)
    if claim.get("status") != "PENDING_INFO":
        raise ChatError(409, "This claim is not waiting for information")
    ensure_conversation(claim_id, submitter_id, claim.get("respond_by"))
    result = run_turn(
        {
            "claim_id": claim_id,
            "submitter_id": submitter_id,
            "conversation_id": f"{submitter_id}:{claim_id}",
            "actor": actor,
            "user_text": text.strip(),
        }
    )
    add_message(claim_id, "user", text.strip())
    add_message(claim_id, "assistant", (result.get("reply") or "").strip() or "I could not use that answer.", _issue_id(result))
    return _payload(claim_id)


def add_note(claim_id: str, submitter_id: str, text: str, actor: dict) -> dict:
    claim = _require_claim(claim_id, submitter_id, actor)
    ensure_conversation(claim_id, submitter_id, claim.get("respond_by"))
    add_message(claim_id, "assistant", text.strip())
    return _payload(claim_id)
