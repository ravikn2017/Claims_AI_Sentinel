"""LangGraph checkpoints live in the adjudication schema."""

from __future__ import annotations

import threading

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row

from db_url import database_url

_init_lock = threading.Lock()
_saver: PostgresSaver | None = None


def psycopg_url() -> str:
    url = database_url()
    prefix = "postgresql+psycopg://"
    if url.startswith(prefix):
        return "postgresql://" + url[len(prefix) :]
    return url


def checkpointer() -> PostgresSaver:
    global _saver
    with _init_lock:
        if _saver is None:
            conn = Connection.connect(
                psycopg_url(),
                autocommit=True,
                prepare_threshold=0,
                row_factory=dict_row,
            )
            conn.execute("SET search_path TO adjudication")
            saver = PostgresSaver(conn)
            saver.setup()
            _saver = saver
        return _saver
