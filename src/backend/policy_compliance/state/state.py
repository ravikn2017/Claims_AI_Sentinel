from typing import TypedDict


class PolicyState(TypedDict, total=False):
    claim: dict
    claim_id: str
    correlation_id: str
    active: bool
    plan_code: str | None
    network_status: str | None
    prepared: list
    pending: list
    passages: dict
    proposals: dict
    attempts: dict
    search_error: str | None
    retry: bool
    result: dict
