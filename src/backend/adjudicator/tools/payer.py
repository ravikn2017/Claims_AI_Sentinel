"""Payer-service HTTP calls. The adjudicator never writes claims.*."""

from __future__ import annotations

import os

import httpx

from adjudicator.errors import AdjudicationError


def payer_base() -> str:
    return os.environ.get("PAYER_SERVICE_URL", "http://127.0.0.1:47111")


def run_actor(claim_id: str, attempt: int) -> str:
    return f"adjudicator:run/{claim_id}:{attempt}"


def _headers(claim_id: str, attempt: int, correlation_id: str, actor_id: str | None = None) -> dict[str, str]:
    return {
        "X-Actor-Type": "service",
        "X-Actor-Id": actor_id or run_actor(claim_id, attempt),
        "X-Actor-Role": "adjudicator",
        "X-Correlation-ID": correlation_id or "",
    }


def _request(
    method: str,
    path: str,
    claim_id: str,
    attempt: int,
    correlation_id: str,
    payload: dict | None = None,
    actor_id: str | None = None,
):
    try:
        response = httpx.request(
            method,
            f"{payer_base()}{path}",
            headers=_headers(claim_id, attempt, correlation_id, actor_id),
            json=payload,
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise AdjudicationError(503, "Payer service is unavailable") from exc
    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text}
    return response.status_code, body


def _detail(body: object) -> str:
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, dict) and "status" in detail:
            return str(detail["status"])
    return "Payer service request failed"


def _as_bool(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def get_plan_benefit(plan_code: str, cpt_code: str, correlation_id: str) -> dict:
    """One benefit row. A 404 is a missing row, not a failure."""
    status, body = _request(
        "GET",
        f"/reference/plan-benefits/{plan_code}/{cpt_code}",
        "",
        0,
        correlation_id,
        actor_id="adjudicator:policy_compliance",
    )
    if status == 404:
        return {
            "found": False,
            "plan_code": plan_code,
            "cpt_code": cpt_code,
            "benefit_category": None,
            "is_covered": None,
            "requires_prior_auth": None,
            "policy_section": None,
        }
    if status == 200 and isinstance(body, dict):
        return {
            "found": True,
            "plan_code": body.get("plan_code") or plan_code,
            "cpt_code": body.get("cpt_code") or cpt_code,
            "benefit_category": body.get("benefit_category"),
            "is_covered": _as_bool(body.get("is_covered")),
            "requires_prior_auth": _as_bool(body.get("requires_prior_auth")),
            "policy_section": body.get("policy_section"),
        }
    if status >= 500:
        raise AdjudicationError(503, "Payer service is unavailable")
    raise AdjudicationError(status, _detail(body))


def get_medical_records(claim_id: str, attempt: int, correlation_id: str) -> list[dict]:
    """Text of every medical_record on the claim. The payer service writes the audit row."""
    status, body = _request(
        "GET",
        f"/claims/{claim_id}/medical-records",
        claim_id,
        attempt,
        correlation_id,
        actor_id="adjudicator:medical_necessity",
    )
    if status == 200 and isinstance(body, list):
        records = []
        for row in body:
            if not isinstance(row, dict):
                continue
            records.append(
                {
                    "document_id": str(row.get("document_id") or ""),
                    "received_at": row.get("received_at"),
                    "text": str(row.get("text") or ""),
                }
            )
        return records
    if status == 404:
        raise AdjudicationError(404, "Claim not found")
    if status >= 500:
        raise AdjudicationError(503, "Payer service is unavailable")
    raise AdjudicationError(status if status >= 400 else 502, _detail(body))


def get_claim(claim_id: str, attempt: int, correlation_id: str) -> dict:
    status, body = _request("GET", f"/claims/{claim_id}", claim_id, attempt, correlation_id)
    if status == 200 and isinstance(body, dict):
        return body
    if status == 404:
        raise AdjudicationError(404, "Claim not found")
    if status >= 500:
        raise AdjudicationError(503, "Payer service is unavailable")
    raise AdjudicationError(status, _detail(body))


def request_transition(
    claim_id: str,
    attempt: int,
    from_status: str,
    to_status: str,
    reason_code: str,
    reason: str,
    issues: list[dict] | None,
    correlation_id: str,
) -> str:
    payload = {
        "from_status": from_status,
        "to_status": to_status,
        "actor": run_actor(claim_id, attempt),
        "reason_code": reason_code,
        "reason": reason,
        "idempotency_key": f"{claim_id}:{attempt}:{from_status}->{to_status}",
        "issues": issues or [],
    }
    status, body = _request(
        "POST",
        f"/claims/{claim_id}/transitions",
        claim_id,
        attempt,
        correlation_id,
        payload,
    )
    if status == 200 and isinstance(body, dict):
        return str(body.get("result") or "applied")
    if status == 409 and isinstance(body, dict):
        detail = body.get("detail")
        current = detail.get("status") if isinstance(detail, dict) else None
        if current == to_status:
            return "replayed"
    if status == 404:
        raise AdjudicationError(404, "Claim not found")
    if status == 422:
        raise AdjudicationError(422, _detail(body))
    if status >= 500:
        raise AdjudicationError(503, "Payer service is unavailable")
    raise AdjudicationError(503, _detail(body))
