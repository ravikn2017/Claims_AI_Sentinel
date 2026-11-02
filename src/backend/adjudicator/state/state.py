from typing import TypedDict


class AdjState(TypedDict, total=False):
    claim_id: str
    attempt: int
    correlation_id: str
    submission_id: str
    claim: dict
    schema_ok: bool
    schema_issues: list
    policy_result: dict
    fraud_result: dict
    investigation: dict | None
    med_result: dict | None
    summary: dict | None
    decision: dict | None
    next_step: str
    status: str
