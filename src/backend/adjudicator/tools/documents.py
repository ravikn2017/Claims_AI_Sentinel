"""Read the payer document index. The embedding model proposes the query vector. Code ranks the rows."""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text

from adjudicator.LLMS.embeddings import DIMENSIONS, embed_query
from adjudicator.db import adjudicator_engine

_COLUMNS = """
    id, doc_type, doc_id, plan_code, cpt_codes, section, heading, text,
    (embedding IS NOT NULL) AS embedded
"""


def _rows(statement, params: dict) -> list[dict]:
    with adjudicator_engine().connect() as conn:
        found = conn.execute(statement, params).mappings()
        return [dict(row) for row in found]


def search_policy_documents(plan_code: str, query: str) -> list[dict]:
    vector = embed_query(query)
    statement = text(
        f"""
        SELECT {_COLUMNS}
        FROM adjudication.payer_doc_chunk
        WHERE doc_type = 'eoc'
          AND plan_code = :plan_code
          AND embedding IS NOT NULL
        ORDER BY embedding <=> :query
        LIMIT 3
        """
    ).bindparams(bindparam("query", type_=Vector(DIMENSIONS)))
    return _rows(statement, {"plan_code": plan_code, "query": vector})


def get_medical_policy(cpt_code: str) -> list[dict]:
    statement = text(
        f"""
        SELECT {_COLUMNS}
        FROM adjudication.payer_doc_chunk
        WHERE doc_type = 'medical_policy'
          AND :cpt = ANY(cpt_codes)
        ORDER BY section
        """
    )
    return _rows(statement, {"cpt": cpt_code})
