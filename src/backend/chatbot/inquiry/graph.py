from langgraph.graph import END, START, StateGraph

from chatbot.LLMS.tracing import flush_traces, inquiry_config
from chatbot.inquiry.nodes import fetch_node, propose_node, reply_node
from chatbot.inquiry.state import InquiryState


def build_graph():
    graph = StateGraph(InquiryState)
    graph.add_node("propose", propose_node)
    graph.add_node("fetch", fetch_node)
    graph.add_node("reply", reply_node)
    graph.add_edge(START, "propose")
    graph.add_edge("propose", "fetch")
    graph.add_edge("fetch", "reply")
    graph.add_edge("reply", END)
    return graph.compile()


inquiry_graph = build_graph()


def run_turn(state: dict) -> dict:
    result = inquiry_graph.invoke(state, inquiry_config(state["member_id"]))
    flush_traces()
    return result
