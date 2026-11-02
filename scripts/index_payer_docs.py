"""Index the synthetic plan documents and medical policies."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "src" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from adjudicator.index import index_seed_documents  # noqa: E402


def main() -> None:
    result = index_seed_documents()
    print(f"Indexed {result['documents']} documents, {result['chunks']} sections.")


if __name__ == "__main__":
    main()
