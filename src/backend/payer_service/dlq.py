"""Inspect and replay the payer dead-letter queue. Replay requires an actor and a reason."""

from __future__ import annotations

import argparse
import asyncio
import os

import aio_pika
from aio_pika import DeliveryMode, Message

from payer_service.app.db import payer_engine
from payer_service.app.repository import record_audit, resolve_intake_error

QUEUE = "payer.claim_submitted.dlq"
TARGET = "payer.claim_submitted"


def require_reason(reason: str | None, actor: str | None) -> tuple[str, str]:
    if not actor or not actor.strip() or not reason or not reason.strip():
        raise SystemExit(2)
    return actor.strip(), reason.strip()


async def _hold(channel) -> list:
    queue = await channel.declare_queue(QUEUE, durable=True, passive=True)
    held = []
    while True:
        message = await queue.get(timeout=0.2, fail=False)
        if message is None:
            break
        held.append(message)
    return held


async def inspect() -> list[dict]:
    connection = await aio_pika.connect(os.environ["RABBITMQ_URL"])
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=100)
    held = await _hold(channel)
    rows = []
    for message in held:
        rows.append(
            {
                "message_id": message.message_id,
                "headers": {str(key): value for key, value in (message.headers or {}).items()},
            }
        )
        await message.nack(requeue=True)
    await connection.close()
    return rows


async def discard(message_id: str, actor: str | None, reason: str | None) -> None:
    """Drop one dead-lettered message and mark its intake_error resolved."""
    actor, reason = require_reason(reason, actor)
    connection = await aio_pika.connect(os.environ["RABBITMQ_URL"])
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=100)
    held = await _hold(channel)
    found = None
    for message in held:
        if message.message_id == message_id:
            found = message
        else:
            await message.nack(requeue=True)
    if found is not None:
        await found.ack()
    await connection.close()
    with payer_engine().begin() as conn:
        resolve_intake_error(conn, message_id)
        record_audit(
            conn,
            actor_type="operator",
            actor_id=actor,
            actor_role="ops",
            action="dlq_discard",
            reason=reason,
            details={"message_id": message_id, "queue_message_acked": found is not None},
        )


async def replay(message_id: str, actor: str | None, reason: str | None) -> None:
    actor, reason = require_reason(reason, actor)
    connection = await aio_pika.connect(os.environ["RABBITMQ_URL"])
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=100)
    held = await _hold(channel)
    found = None
    for message in held:
        if message.message_id == message_id:
            found = message
        else:
            await message.nack(requeue=True)
    if found is None:
        await connection.close()
        raise SystemExit(1)
    outgoing = Message(
        found.body,
        message_id=found.message_id,
        correlation_id=found.correlation_id,
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
        headers={"x-attempt": 1},
    )
    await channel.default_exchange.publish(outgoing, routing_key=TARGET)
    await found.ack()
    await connection.close()
    with payer_engine().begin() as conn:
        resolve_intake_error(conn, message_id)
        record_audit(
            conn,
            actor_type="operator",
            actor_id=actor,
            actor_role="ops",
            action="dlq_replay",
            reason=reason,
            details={"message_id": message_id, "attempts_reset": 1},
        )


def main_inspect() -> None:
    rows = asyncio.run(inspect())
    for row in rows:
        print(row["message_id"], row["headers"])
    if not rows:
        print("dlq empty")


def main_replay() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    asyncio.run(replay(args.message_id, args.actor, args.reason))
    print("replayed", args.message_id)
