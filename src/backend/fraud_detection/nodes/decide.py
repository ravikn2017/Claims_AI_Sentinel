"""Code accepts the probability and sets CLEAR or FLAGGED."""

from fraud_detection.scoring import decide
from fraud_detection.state.state import FraudState


def decide_node(state: FraudState) -> dict:
    result = decide(state.get("claim") or {}, state)
    return {"result": result}
