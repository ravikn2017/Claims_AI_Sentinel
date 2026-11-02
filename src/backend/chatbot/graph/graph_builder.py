from langgraph.graph import END, START, StateGraph

from chatbot.LLMS.tracing import flush_traces, run_config
from chatbot.nodes.act import act_node
from chatbot.nodes.followup import followup_node
from chatbot.nodes.load import load_node
from chatbot.nodes.propose import propose_node
from chatbot.state.state import ChatState


def _after_act(state: ChatState) -> str:
    if state.get("submitted"):
        return "followup"
    return "end"


def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("load", load_node)
    graph.add_node("propose", propose_node)
    graph.add_node("act", act_node)
    graph.add_node("followup", followup_node)
    graph.add_edge(START, "load")
    graph.add_edge("load", "propose")
    graph.add_edge("propose", "act")
    graph.add_conditional_edges("act", _after_act, {"followup": "followup", "end": END})
    graph.add_edge("followup", END)
    return graph.compile()


chat_graph = build_graph()


def run_turn(state: dict) -> dict:
    result = chat_graph.invoke(
        state,
        run_config(state["claim_id"], state["conversation_id"], state["submitter_id"]),
    )
    flush_traces()
    return result
