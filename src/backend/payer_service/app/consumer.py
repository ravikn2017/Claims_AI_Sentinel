"""Consume claim.submitted. Ack only after the claim transaction commits."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

from payer_service.app.db import payer_engine
from payer_service.app.errors import PermanentError, TransientError
from payer_service.app.pipeline import peek_submission_id, process_message, remember_failure

log = logging.getLogger("payer.consumer")

RETRY_10 = "payer.claim_submitted.retry.10s"
RETRY_60 = "payer.claim_submitted.retry.60s"
DLQ_KEY = "payer.claim_submitted"


async def _publish(channel, exchange_name: str, routing_key: str, msg: aio_pika.abc.AbstractIncomingMessage, headers: dict) -> None:
    exchange = await channel.get_exchange(exchange_name)
    outgoing = Message(
        msg.body,
        message_id=msg.message_id,
        correlation_id=msg.correlation_id,
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
        headers=headers,
    )
    await exchange.publish(outgoing, routing_key=routing_key)


async def dead_letter(channel, msg, error: Exception, attempt: int) -> None:
    headers = {
        "x-error-class": type(error).__name__,
        "x-error": str(error)[:500],
        "x-attempts": attempt,
        "x-failed-at": datetime.now(timezone.utc).isoformat(),
        "x-attempt": attempt,
    }
    await _publish(channel, "claims.dlx", DLQ_KEY, msg, headers)
    await asyncio.to_thread(
        remember_failure,
        payer_engine(),
        msg.message_id,
        msg.body,
        type(error).__name__,
        str(error),
        attempt,
    )


async def schedule_retry(channel, msg, attempt: int) -> None:
    routing_key = RETRY_10 if attempt == 2 else RETRY_60
    headers = dict(msg.headers or {})
    headers["x-attempt"] = attempt
    await _publish(channel, "claims.retry", routing_key, msg, headers)


async def on_message(msg: aio_pika.abc.AbstractIncomingMessage, channel) -> None:
    attempt = int((msg.headers or {}).get("x-attempt", 1))
    submission_id = peek_submission_id(msg.body)
    log.info("message_id=%s submission_id=%s attempt=%s", msg.message_id, submission_id, attempt)
    try:
        claim_id = await asyncio.to_thread(process_message, msg.body, payer_engine())
        log.info("ack message_id=%s submission_id=%s claim_id=%s", msg.message_id, submission_id, claim_id)
        await msg.ack()
    except PermanentError as exc:
        log.info("dead-letter message_id=%s submission_id=%s", msg.message_id, submission_id)
        await dead_letter(channel, msg, exc, attempt)
        await msg.ack()
    except (TransientError, Exception) as exc:
        log.info("retry message_id=%s submission_id=%s attempt=%s", msg.message_id, submission_id, attempt)
        if attempt < 3:
            await schedule_retry(channel, msg, attempt + 1)
        else:
            await dead_letter(channel, msg, exc, attempt)
        await msg.ack()


async def consume(stop: asyncio.Event) -> None:
    connection = await aio_pika.connect(os_rabbit())
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)
    await channel.declare_exchange("claims.events", ExchangeType.TOPIC, durable=True)
    await channel.declare_exchange("claims.retry", ExchangeType.DIRECT, durable=True)
    await channel.declare_exchange("claims.dlx", ExchangeType.DIRECT, durable=True)
    queue = await channel.declare_queue(
        "payer.claim_submitted",
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-delivery-limit": 5,
            "x-dead-letter-exchange": "claims.dlx",
            "x-dead-letter-routing-key": "payer.claim_submitted",
        },
    )
    # A timed basic.get cancels the RPC and closes the channel. Block until a
    # message arrives; shutdown cancels this task.
    async with queue.iterator() as incoming:
        async for msg in incoming:
            if stop.is_set():
                break
            await on_message(msg, channel)
    await connection.close()


def os_rabbit() -> str:
    import os

    return os.environ["RABBITMQ_URL"]
