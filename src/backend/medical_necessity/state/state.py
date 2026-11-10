from typing import TypedDict


class MedicalState(TypedDict, total=False):
    claim: dict
    claim_id: str
    attempt: int
    correlation_id: str
    policy_result: dict
    prepared: list
    notes: list
    pending: list
    findings: dict
    attempts: dict
    gate_error: str | None
    retry: bool
    result: dict
