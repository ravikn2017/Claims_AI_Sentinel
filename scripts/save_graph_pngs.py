"""Save each graph picture once. An existing file is left unchanged."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"
OUT = ROOT / "docs" / "graphs"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def save(name: str, compiled) -> None:
    path = OUT / f"{name}.png"
    if path.exists():
        print(f"left {path.relative_to(ROOT)} as it is")
        return
    compiled.get_graph().draw_mermaid_png(output_file_path=str(path))
    print(f"wrote {path.relative_to(ROOT)}")


def main() -> None:
    from langgraph.checkpoint.memory import MemorySaver

    from adjudicator.graph.graph_builder import build_graph as build_adjudicator
    from chatbot.graph.graph_builder import chat_graph
    from fraud_detection.graph.graph_builder import fraud_graph
    from medical_necessity.graph.graph_builder import medical_graph
    from policy_compliance.graph.graph_builder import policy_graph

    OUT.mkdir(parents=True, exist_ok=True)
    save("adjudicator", build_adjudicator(MemorySaver()))
    save("chatbot", chat_graph)
    save("fraud_detection", fraud_graph)
    save("medical_necessity", medical_graph)
    save("policy_compliance", policy_graph)


if __name__ == "__main__":
    main()
