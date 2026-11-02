"""Load payer documents into adjudication.payer_doc_chunk."""

from __future__ import annotations

import re

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam
from sqlalchemy import text as sql_text

from adjudicator.LLMS.embeddings import DIMENSIONS, embed_texts
from adjudicator.db import adjudicator_engine
from db_url import ROOT

HEADING = re.compile(r"^(#{1,3})\s+(.+)$", re.M)
FRONT_MATTER = re.compile(r"^---\r?\n.*?\r?\n---\r?\n", re.S)
CPT_LIST = re.compile(r"[A-Za-z0-9]+")

PLAN_DIR = ROOT / "data" / "plan_documents"
POLICY_DIR = ROOT / "data" / "medical_policies"


class EmptyDocument(Exception):
    """The markdown has no section to index."""


def chunk_markdown(body: str) -> list[dict]:
    text_body = FRONT_MATTER.sub("", body, count=1).strip()
    matches = list(HEADING.finditer(text_body))
    if not matches:
        if not text_body:
            return []
        return [{"section": None, "heading": None, "text": text_body}]
    chunks = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text_body)
        heading = match.group(2).strip()
        section = heading.split()[0].rstrip(".") if heading else None
        chunk_text = text_body[start:end].strip() or heading
        chunks.append({"section": section, "heading": heading, "text": chunk_text})
    return [chunk for chunk in chunks if chunk["text"]]


def _cpt_codes(raw: str) -> list[str]:
    return CPT_LIST.findall(raw)


def _front_matter(body: str) -> dict[str, str]:
    if not body.startswith("---"):
        return {}
    match = FRONT_MATTER.match(body)
    if match is None:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(0).splitlines()[1:-1]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def seed_sources() -> list[dict]:
    documents = []
    for path in sorted(PLAN_DIR.glob("*.md")):
        documents.append(
            {
                "doc_type": "eoc",
                "doc_id": path.stem,
                "plan_code": path.stem,
                "cpt_codes": None,
                "text": path.read_text(),
            }
        )
    for path in sorted(POLICY_DIR.glob("*.md")):
        body = path.read_text()
        fields = _front_matter(body)
        documents.append(
            {
                "doc_type": "medical_policy",
                "doc_id": path.stem,
                "plan_code": None,
                "cpt_codes": _cpt_codes(fields.get("cpt_codes", "")),
                "text": body,
            }
        )
    return documents


def index_document(
    *,
    doc_type: str,
    doc_id: str,
    plan_code: str | None,
    cpt_codes: list[str] | None,
    text: str,
) -> int:
    chunks = chunk_markdown(text)
    if not chunks:
        raise EmptyDocument("Document has no sections")
    if doc_type == "medical_policy" and not cpt_codes:
        raise EmptyDocument("A medical policy needs a CPT code")
    vectors = embed_texts(
        [f"{chunk['heading']}\n{chunk['text']}" if chunk["heading"] else chunk["text"] for chunk in chunks]
    )
    codes = cpt_codes or None
    statement = sql_text(
        """
        INSERT INTO adjudication.payer_doc_chunk
            (doc_type, doc_id, plan_code, cpt_codes, section, heading, text, embedding)
        VALUES
            (:doc_type, :doc_id, :plan_code, :cpt_codes, :section, :heading, :text, :embedding)
        """
    ).bindparams(bindparam("embedding", type_=Vector(DIMENSIONS)))
    with adjudicator_engine().begin() as conn:
        conn.execute(
            sql_text("DELETE FROM adjudication.payer_doc_chunk WHERE doc_type = :doc_type AND doc_id = :doc_id"),
            {"doc_type": doc_type, "doc_id": doc_id},
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            conn.execute(
                statement,
                {
                    "doc_type": doc_type,
                    "doc_id": doc_id,
                    "plan_code": plan_code,
                    "cpt_codes": codes,
                    "section": chunk["section"],
                    "heading": chunk["heading"],
                    "text": chunk["text"],
                    "embedding": vector,
                },
            )
    return len(chunks)


def index_seed_documents() -> dict:
    documents = seed_sources()
    chunks = 0
    for document in documents:
        chunks += index_document(**document)
    return {"documents": len(documents), "chunks": chunks}
