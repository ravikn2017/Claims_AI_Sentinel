"""Adjudicator database. This service owns the adjudication schema."""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from db_url import database_url

_engine: Engine | None = None


def adjudicator_engine() -> Engine:
    global _engine
    if _engine is None:
        engine = create_engine(database_url(), pool_pre_ping=True)

        @event.listens_for(engine, "connect")
        def _register_vector(dbapi_connection, _connection_record) -> None:
            from pgvector.psycopg import register_vector

            register_vector(dbapi_connection)

        _engine = engine
    return _engine
