"""Publish outbox rows. A second publish of the same row is harmless: consumers are idempotent."""

from __future__ import annotations

import asyncio
import json
import logging

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from sqlalchemy import text

from payer_service.app.consumer import os_rabbit
from payer_service.app.db import payer_engine

log = logging.getLogger("payer.relay")


def _pending(limit: int = 50) -> list[dict]:
    with payer_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, message_id::text AS message_id, routing_key, payload
                FROM claims.outbox
                WHERE published_at IS NULL
                ORDER BY id
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings()
        return [dict(row) for row in rows]


def _mark(row_id: int) -> None:
    with payer_engine().begin() as conn:
        conn.execute(
            text("UPDATE claims.outbox SET published_at = now() WHERE id = :id AND published_at IS NULL"),
            {"id": row_id},
        )


async def relay_once(channel) -> int:
    rows = await asyncio.to_thread(_pending)
    if not rows:
        return 0
    exchange = await channel.declare_exchange("claims.events", ExchangeType.TOPIC, durable=True)
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        body = json.dumps(payload).encode()
        message = Message(
            body,
            message_id=str(row["message_id"]),
            correlation_id=str(payload.get("submission_id") or ""),
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type="application/json",
        )
        await exchange.publish(message, routing_key=row["routing_key"])
        await asyncio.to_thread(_mark, row["id"])
        log.info("published message_id=%s claim_id=%s", row["message_id"], payload.get("claim_id"))
    return len(rows)


async def relay_loop(stop: asyncio.Event) -> None:
    connection = await aio_pika.connect(os_rabbit())
    channel = await connection.channel()
    while not stop.is_set():
        try:
            await relay_once(channel)
        except Exception:
            log.exception("outbox relay failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except TimeoutError:
            continue
    await connection.close()
