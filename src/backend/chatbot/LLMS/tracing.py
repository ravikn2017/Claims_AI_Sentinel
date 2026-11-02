"""Langfuse traces for debugging. They are not the claim audit record."""

from __future__ import annotations

import logging
import os

log = logging.getLogger("chatbot.tracing")

_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")


def langfuse_enabled() -> bool:
    return all(os.environ.get(key) for key in _KEYS)


def langfuse_handler():
    if not langfuse_enabled():
        return None
    from langfuse.langchain import CallbackHandler

    return CallbackHandler()


def run_config(claim_id: str, conversation_id: str, submitter_id: str) -> dict:
    config = {
        "run_name": "missing-info-chat",
        "metadata": {
            "claim_id": claim_id,
            "conversation_id": conversation_id,
            "langfuse_session_id": conversation_id,
            "langfuse_user_id": submitter_id,
            "langfuse_tags": ["missing-info"],
        },
    }
    handler = langfuse_handler()
    if handler is not None:
        config["callbacks"] = [handler]
    return config


def inquiry_config(member_id: str) -> dict:
    conversation_id = f"inquiry:{member_id}"
    config = {
        "run_name": "member-inquiry",
        "metadata": {
            "member_id": member_id,
            "conversation_id": conversation_id,
            "langfuse_session_id": conversation_id,
            "langfuse_user_id": member_id,
            "langfuse_tags": ["inquiry"],
        },
    }
    handler = langfuse_handler()
    if handler is not None:
        config["callbacks"] = [handler]
    return config


def flush_traces() -> None:
    if not langfuse_enabled():
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        log.warning("Langfuse flush failed", exc_info=True)
