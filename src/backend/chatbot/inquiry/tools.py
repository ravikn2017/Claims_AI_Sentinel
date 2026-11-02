"""Read-only payer calls. This graph never posts an answer."""

from __future__ import annotations

import os

import httpx

from chatbot.errors import ChatError

_CLAIM_KEYS = ("claim_id", "submission_id", "status", "service_from", "service_to", "total_billed", "open_questions")
_PROVIDER_KEYS = ("provider_id", "npi", "name", "network_status", "city", "state")


def payer_base() -> str:
    return os.environ.get("PAYER_SERVICE_URL", "http://127.0.0.1:47111")


def _headers(actor: dict) -> dict[str, str]:
    return {
        "X-Actor-Type": actor.get("actor_type") or "service",
        "X-Actor-Id": actor.get("actor_id") or "chatbot",
        "X-Actor-Role": actor.get("actor_role") or "service",
        "X-Correlation-ID": actor.get("correlation_id") or "",
    }


def _request(method: str, path: str, actor: dict, params: dict | None = None) -> tuple[int, object]:
    try:
        response = httpx.request(method, f"{payer_base()}{path}", headers=_headers(actor), params=params, timeout=30)
    except httpx.HTTPError as exc:
        raise ChatError(503, "Payer service is unavailable") from exc
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text}
    return response.status_code, body


def _keep(row: object, keys: tuple[str, ...]) -> dict | None:
    if not isinstance(row, dict):
        return None
    return {key: row.get(key) for key in keys}


def member_claims(member_id: str, actor: dict) -> dict:
    status, body = _request("GET", f"/members/{member_id}/claims", actor)
    if status == 404:
        return {"claims": [], "note": "This member is not on file."}
    if status != 200 or not isinstance(body, dict):
        raise ChatError(503, "Payer service is unavailable")
    claims = [_keep(row, _CLAIM_KEYS) for row in body.get("claims") or []]
    return {
        "member_name": body.get("member_name") or "",
        "claims": [row for row in claims if row],
    }


def member_coverage(member_id: str, actor: dict) -> dict:
    status, body = _request("GET", f"/members/{member_id}/coverage", actor)
    if status == 404:
        return {"policies": [], "benefits": [], "note": "This member is not on file."}
    if status != 200 or not isinstance(body, dict):
        raise ChatError(503, "Payer service is unavailable")
    return {
        "member_name": body.get("member_name") or "",
        "policies": body.get("policies") if isinstance(body.get("policies"), list) else [],
        "benefits": body.get("benefits") if isinstance(body.get("benefits"), list) else [],
    }


def find_providers(query: str, actor: dict) -> dict:
    status, body = _request("GET", "/providers", actor, {"q": query})
    if status != 200 or not isinstance(body, dict):
        raise ChatError(503, "Payer service is unavailable")
    providers = [_keep(row, _PROVIDER_KEYS) for row in body.get("providers") or []]
    return {"providers": [row for row in providers if row]}
