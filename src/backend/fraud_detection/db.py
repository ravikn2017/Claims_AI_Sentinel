"""Fraud model store. This service owns the fraud schema."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from db_url import database_url

_engine: Engine | None = None


def fraud_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(database_url(), pool_pre_ping=True)
    return _engine
