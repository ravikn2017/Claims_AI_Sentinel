"""Embedding model. It proposes a vector. Code keeps it only when the length is 768."""

from __future__ import annotations

import os

from langchain_openai import OpenAIEmbeddings

DIMENSIONS = 768


class EmbeddingFailed(Exception):
    """The embedding model did not return a usable vector."""


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    try:
        vectors = OpenAIEmbeddings(
            model=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
            dimensions=DIMENSIONS,
            api_key=os.environ["OPENAI_API_KEY"],
        ).embed_documents(texts)
    except Exception as exc:
        raise EmbeddingFailed("Embedding service is unavailable") from exc
    if len(vectors) != len(texts) or any(len(vector) != DIMENSIONS for vector in vectors):
        raise EmbeddingFailed("Embedding service returned an unexpected vector")
    return vectors


def embed_query(query: str) -> list[float]:
    vectors = embed_texts([query])
    return vectors[0]
