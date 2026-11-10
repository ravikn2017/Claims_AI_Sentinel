from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from adjudicator.nodes.routing import ROUTE_NODES
from adjudicator.nodes.run import (
    after_investigation,
    after_load,
    after_medical,
    after_route,
    decide,
    fraud_check,
    human_review,
    investigation,
    load_claim,
    medical_necessity,
    policy_check,
    return_to_claimant,
    route_node,
)
from adjudicator.state.state import AdjState

AGENT_RETRY = RetryPolicy(max_attempts=2, initial_interval=0.01)
LOAD_TARGETS = {
    "policy_check": "policy_check",
    "fraud_check": "fraud_check",
    "return_to_claimant": "return_to_claimant",
}
ROUTE_TARGETS = {node: node for node in ROUTE_NODES.values()}


def build_graph(saver):
    graph = StateGraph(AdjState)
    graph.add_node("load_claim", load_claim)
    graph.add_node("policy_check", policy_check, retry_policy=AGENT_RETRY)
    graph.add_node("fraud_check", fraud_check, retry_policy=AGENT_RETRY)
    graph.add_node("route", route_node)
    graph.add_node("investigation", investigation)
    graph.add_node("medical_necessity", medical_necessity, retry_policy=AGENT_RETRY)
    graph.add_node("human_review", human_review)
    graph.add_node("decide", decide)
    graph.add_node("return_to_claimant", return_to_claimant)
    graph.add_edge(START, "load_claim")
    graph.add_conditional_edges("load_claim", after_load, LOAD_TARGETS)
    graph.add_edge(["policy_check", "fraud_check"], "route")
    graph.add_conditional_edges("route", after_route, ROUTE_TARGETS)
    graph.add_conditional_edges("investigation", after_investigation, ROUTE_TARGETS)
    graph.add_conditional_edges("medical_necessity", after_medical, ROUTE_TARGETS)
    graph.add_edge("human_review", "decide")
    graph.add_edge("decide", END)
    graph.add_edge("return_to_claimant", END)
    return graph.compile(checkpointer=saver)
