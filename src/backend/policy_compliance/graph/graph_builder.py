from langgraph.graph import END, START, StateGraph

from policy_compliance.LLMS.tracing import flush_traces, run_config
from policy_compliance.nodes.run import (
    after_finalize,
    after_gate,
    after_retrieve,
    after_settle,
    finalize_node,
    gate_node,
    inactive_node,
    propose_node,
    retrieve_node,
    settle_node,
)
from policy_compliance.state.state import PolicyState


def build_graph():
    graph = StateGraph(PolicyState)
    graph.add_node("gate", gate_node)
    graph.add_node("inactive", inactive_node)
    graph.add_node("settle", settle_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("propose", propose_node)
    graph.add_node("finalize", finalize_node)
    graph.add_edge(START, "gate")
    graph.add_conditional_edges("gate", after_gate, {"settle": "settle", "inactive": "inactive"})
    graph.add_edge("inactive", END)
    graph.add_conditional_edges("settle", after_settle, {"retrieve": "retrieve", "finalize": "finalize"})
    graph.add_conditional_edges("retrieve", after_retrieve, {"propose": "propose", "finalize": "finalize"})
    graph.add_edge("propose", "finalize")
    graph.add_conditional_edges("finalize", after_finalize, {"propose": "propose", "done": END})
    return graph.compile()


policy_graph = build_graph()


def run_policy(state: dict) -> dict:
    claim_id = state.get("claim_id") or ""
    try:
        result = policy_graph.invoke(
            {
                "claim": state.get("claim") or {},
                "claim_id": claim_id,
                "correlation_id": state.get("correlation_id") or "",
            },
            run_config(claim_id),
        )
    finally:
        flush_traces()
    return result["result"]
