from langgraph.graph import END, START, StateGraph

from fraud_detection.nodes.decide import decide_node
from fraud_detection.nodes.propose import propose_node
from fraud_detection.state.state import FraudState


def build_graph():
    graph = StateGraph(FraudState)
    graph.add_node("propose", propose_node)
    graph.add_node("decide", decide_node)
    graph.add_edge(START, "propose")
    graph.add_edge("propose", "decide")
    graph.add_edge("decide", END)
    return graph.compile()


fraud_graph = build_graph()


def run_fraud(claim: dict, claim_id: str) -> dict:
    result = fraud_graph.invoke({"claim": claim, "claim_id": claim_id})
    return result["result"]
