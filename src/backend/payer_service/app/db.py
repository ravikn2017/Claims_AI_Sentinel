from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from db_url import payer_database_url

_engine: Engine | None = None


def payer_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(payer_database_url(), pool_pre_ping=True)
    return _engine
