"""Payer-service HTTP calls. These tools never write the claims database."""

from __future__ import annotations

import os

import httpx

from chatbot.errors import ChatError


def payer_base() -> str:
    return os.environ.get("PAYER_SERVICE_URL", "http://127.0.0.1:47111")


def _headers(actor: dict) -> dict[str, str]:
    return {
        "X-Actor-Type": actor.get("actor_type") or "service",
        "X-Actor-Id": actor.get("actor_id") or "chatbot",
        "X-Actor-Role": actor.get("actor_role") or "service",
        "X-Correlation-ID": actor.get("correlation_id") or "",
    }


def _request(method: str, path: str, actor: dict, payload: dict | None = None) -> tuple[int, object]:
    try:
        response = httpx.request(
            method,
            f"{payer_base()}{path}",
            headers=_headers(actor),
            json=payload,
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise ChatError(503, "Payer service is unavailable") from exc
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text}
    return response.status_code, body


def detail_of(body: object) -> str:
    if not isinstance(body, dict):
        return ""
    detail = body.get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and "status" in detail:
        return f"The claim is {detail['status']}."
    return ""


def get_claim(claim_id: str, actor: dict) -> tuple[int, dict]:
    status, body = _request("GET", f"/claims/{claim_id}", actor)
    return status, body if isinstance(body, dict) else {"detail": body}


def get_open_issues(claim_id: str, actor: dict) -> tuple[int, list]:
    status, body = _request("GET", f"/claims/{claim_id}/issues?status=open", actor)
    if isinstance(body, list):
        return status, body
    return status, []


def post_answer(
    claim_id: str,
    issue_id: int,
    value,
    conversation_id: str,
    claimant_text: str,
    submitter_id: str,
    actor: dict,
) -> tuple[int, dict]:
    status, body = _request(
        "POST",
        f"/claims/{claim_id}/issues/{issue_id}/answers",
        actor,
        {
            "value": value,
            "conversation_id": conversation_id,
            "claimant_text": claimant_text,
            "submitter_id": submitter_id,
        },
    )
    return status, body if isinstance(body, dict) else {"detail": body}
