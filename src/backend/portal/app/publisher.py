"""Publish pending submission_log rows. A crash after the insert retries the same row."""

from __future__ import annotations

import asyncio
import json
import logging
import os

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from sqlalchemy import text

from db_url import document_root
from portal.app.db import portal_engine

log = logging.getLogger("portal.publisher")


def _pending() -> list[str]:
    with portal_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT submission_id FROM portal.submission_log
                WHERE publish_status = 'pending'
                ORDER BY created_at
                LIMIT 20
                """
            )
        ).scalars()
        return list(rows)


def _mark(submission_id: str, status: str) -> None:
    with portal_engine().begin() as conn:
        if status == "published":
            conn.execute(
                text(
                    """
                    UPDATE portal.submission_log
                    SET publish_status = 'published', published_at = now()
                    WHERE submission_id = :submission_id AND publish_status = 'pending'
                    """
                ),
                {"submission_id": submission_id},
            )
        else:
            conn.execute(
                text(
                    """
                    UPDATE portal.submission_log
                    SET publish_status = 'failed'
                    WHERE submission_id = :submission_id AND publish_status = 'pending'
                    """
                ),
                {"submission_id": submission_id},
            )


async def publish_once(channel) -> int:
    pending = await asyncio.to_thread(_pending)
    if not pending:
        return 0
    exchange = await channel.declare_exchange("claims.events", ExchangeType.TOPIC, durable=True)
    published = 0
    for submission_id in pending:
        path = document_root() / submission_id / "message.json"
        if not path.is_file():
            log.info("missing message file submission_id=%s", submission_id)
            await asyncio.to_thread(_mark, submission_id, "failed")
            continue
        body = path.read_bytes()
        payload = json.loads(body)
        message = Message(
            body,
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type="application/json",
            message_id=str(payload["message_id"]),
            correlation_id=submission_id,
        )
        await exchange.publish(message, routing_key="claim.submitted")
        await asyncio.to_thread(_mark, submission_id, "published")
        log.info("published submission_id=%s", submission_id)
        published += 1
    return published


async def publish_loop(stop: asyncio.Event) -> None:
    connection = await aio_pika.connect(os.environ["RABBITMQ_URL"])
    channel = await connection.channel()
    while not stop.is_set():
        try:
            await publish_once(channel)
        except Exception:
            log.exception("publisher failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except TimeoutError:
            continue
    await connection.close()
