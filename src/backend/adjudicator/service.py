"""Start one run per claim attempt, and resume a paused run."""

from __future__ import annotations

import threading

from langgraph.types import Command

from adjudicator.checkpointer import checkpointer
from adjudicator.errors import AdjudicationError
from adjudicator.graph.graph_builder import build_graph
from adjudicator.tasks import thread_id

_graph = None
_lock = threading.Lock()


def get_graph():
    global _graph
    if _graph is None:
        with _lock:
            if _graph is None:
                _graph = build_graph(checkpointer())
    return _graph


def _config(claim_id: str, attempt: int) -> dict:
    return {"configurable": {"thread_id": thread_id(claim_id, attempt)}}


def _invoke(graph, value, config):
    return graph.invoke(value, config, durability="sync")


def start_run(claim_id: str, attempt: int, submission_id: str, correlation_id: str) -> str:
    graph = get_graph()
    config = _config(claim_id, attempt)
    with _lock:
        snapshot = graph.get_state(config)
        if snapshot.created_at is None:
            _invoke(
                graph,
                {
                    "claim_id": claim_id,
                    "attempt": attempt,
                    "submission_id": submission_id,
                    "correlation_id": correlation_id,
                    "status": "RECEIVED",
                },
                config,
            )
            return "started"
        if snapshot.interrupts:
            return "paused"
        if snapshot.next:
            _invoke(graph, None, config)
            return "continued"
        return "finished"


def _resume(claim_id: str, attempt: int, node: str, payload: dict) -> dict:
    graph = get_graph()
    config = _config(claim_id, attempt)
    with _lock:
        snapshot = graph.get_state(config)
        if snapshot.created_at is None:
            raise AdjudicationError(404, "Run not found")
        if not snapshot.interrupts:
            return {"result": "ignored", "status": (snapshot.values or {}).get("status")}
        if node not in snapshot.next:
            waiting = snapshot.next[0] if snapshot.next else "another step"
            raise AdjudicationError(409, f"This run is waiting at {waiting}")
        _invoke(graph, Command(resume=payload), config)
        done = graph.get_state(config)
        return {"result": "resumed", "status": (done.values or {}).get("status")}


def resume_investigation(claim_id: str, attempt: int, outcome: str, notes: str) -> dict:
    if outcome not in {"CLEARED", "CONFIRMED"}:
        raise AdjudicationError(422, "Outcome must be CLEARED or CONFIRMED")
    return _resume(claim_id, attempt, "investigation", {"outcome": outcome, "notes": notes})


def resume_review(claim_id: str, attempt: int, decision: str, allowed_amount: float, reviewer: str, notes: str) -> dict:
    if decision not in {"APPROVED", "DENIED"}:
        raise AdjudicationError(422, "Decision must be APPROVED or DENIED")
    return _resume(
        claim_id,
        attempt,
        "human_review",
        {
            "decision": decision,
            "allowed_amount": allowed_amount,
            "reviewer": reviewer,
            "notes": notes,
        },
    )
