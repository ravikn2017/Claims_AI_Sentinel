import os
from pathlib import Path

import aio_pika
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from db_url import database_url

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _postgres_ok() -> None:
    engine = create_engine(database_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    engine.dispose()


async def _rabbitmq_ok() -> None:
    connection = await aio_pika.connect(os.environ["RABBITMQ_URL"])
    await connection.close()


async def platform_status() -> dict:
    status = {"postgres": "ok", "rabbitmq": "ok"}
    try:
        _postgres_ok()
    except Exception:
        status["postgres"] = "down"
    try:
        await _rabbitmq_ok()
    except Exception:
        status["rabbitmq"] = "down"
    status["status"] = "ok" if status["postgres"] == "ok" and status["rabbitmq"] == "ok" else "error"
    return status
