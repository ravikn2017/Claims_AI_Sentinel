"""Document index. These checks call OpenAI embeddings."""

from __future__ import annotations

from sqlalchemy import text

from adjudicator.db import adjudicator_engine
from adjudicator.index import chunk_markdown, index_seed_documents
from adjudicator.tools.documents import get_medical_policy, search_policy_documents
from db_url import ROOT

COSMETIC = "cosmetic exclusion for upper eyelid surgery when skin blocks the visual field"
BARIATRIC = "bariatric surgery and surgical treatment of obesity are excluded"


def test_sections_are_one_chunk_each():
    chunks = chunk_markdown((ROOT / "data" / "plan_documents" / "SILVER-PPO-01.md").read_text())
    assert [chunk["section"] for chunk in chunks].count("§5.2") == 1
    policy = chunk_markdown((ROOT / "data" / "medical_policies" / "MP-001.md").read_text())
    assert [chunk["section"] for chunk in policy] == ["MP-001.1", "MP-001.2"]


def test_known_section_and_cpt_lookup():
    first = index_seed_documents()
    second = index_seed_documents()
    assert first["documents"] == 5
    assert second["chunks"] == first["chunks"]

    silver = search_policy_documents("SILVER-PPO-01", COSMETIC)
    assert silver[0]["section"] == "§5.2"
    assert silver[0]["embedded"] is True

    bronze = search_policy_documents("BRONZE-HMO-01", BARIATRIC)
    assert bronze[0]["section"] == "§5.3"
    silver_bariatric = search_policy_documents("SILVER-PPO-01", BARIATRIC)
    assert "§5.3" not in [row["section"] for row in silver_bariatric]

    policy = get_medical_policy("72148")
    assert [row["section"] for row in policy] == ["MP-001.1", "MP-001.2"]
    assert all(row["doc_type"] == "medical_policy" for row in policy)
    assert get_medical_policy("99213") == []

    with adjudicator_engine().connect() as conn:
        count = conn.execute(
            text(
                """
                SELECT count(*)
                FROM adjudication.payer_doc_chunk
                WHERE doc_type = 'eoc' AND doc_id = 'SILVER-PPO-01' AND section = '§5.2'
                """
            )
        ).scalar_one()
    assert count == 1
