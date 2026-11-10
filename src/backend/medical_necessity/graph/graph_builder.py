from langgraph.graph import END, START, StateGraph

from medical_necessity.LLMS.tracing import flush_traces, run_config
from medical_necessity.nodes.run import after_finalize, after_gate, evaluate_node, finalize_node, gate_node
from medical_necessity.state.state import MedicalState


def build_graph():
    graph = StateGraph(MedicalState)
    graph.add_node("gate", gate_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("finalize", finalize_node)
    graph.add_edge(START, "gate")
    graph.add_conditional_edges("gate", after_gate, {"evaluate": "evaluate", "finalize": "finalize"})
    graph.add_edge("evaluate", "finalize")
    graph.add_conditional_edges("finalize", after_finalize, {"evaluate": "evaluate", "done": END})
    return graph.compile()


medical_graph = build_graph()


def run_medical(state: dict) -> dict:
    claim_id = state.get("claim_id") or ""
    try:
        result = medical_graph.invoke(
            {
                "claim": state.get("claim") or {},
                "claim_id": claim_id,
                "attempt": int(state.get("attempt") or 1),
                "correlation_id": state.get("correlation_id") or "",
                "policy_result": state.get("policy_result") or {},
            },
            run_config(claim_id),
        )
    finally:
        flush_traces()
    return result["result"]
