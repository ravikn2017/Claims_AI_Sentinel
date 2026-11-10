"""Langfuse traces for debugging. They are not the claim audit record."""

from __future__ import annotations

import logging
import os

log = logging.getLogger("medical_necessity.tracing")

_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")


def langfuse_enabled() -> bool:
    return all(os.environ.get(key) for key in _KEYS)


def langfuse_handler():
    if not langfuse_enabled():
        return None
    from langfuse.langchain import CallbackHandler

    return CallbackHandler()


def run_config(claim_id: str) -> dict:
    config = {
        "run_name": "medical-necessity",
        "metadata": {
            "claim_id": claim_id,
            "conversation_id": claim_id,
            "langfuse_session_id": claim_id,
            "langfuse_user_id": "adjudicator:medical_necessity",
            "langfuse_tags": ["medical-necessity"],
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
