"""The model proposes a probability. It does not set the verdict."""

from fraud_detection.scoring import propose
from fraud_detection.state.state import FraudState


def propose_node(state: FraudState) -> dict:
    return propose(state.get("claim") or {})
