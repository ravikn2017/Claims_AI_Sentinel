from typing import TypedDict


class FraudState(TypedDict, total=False):
    claim: dict
    claim_id: str
    features: dict
    probability: float
    model_version: str
    technique: str
    thresholds: dict
    rule_hits: list
    error: str | None
    result: dict
