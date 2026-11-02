"""Consume claim.info_requested and open one conversation per claim."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from pydantic import ValidationError

from contracts.models import InfoRequested
from chatbot.errors import ChatError
from chatbot.service import SERVICE_ACTOR, ensure_opening

log = logging.getLogger("chatbot.consumer")

RETRY_10 = "chatbot.info_requested.retry.10s"
RETRY_60 = "chatbot.info_requested.retry.60s"
DLQ_KEY = "chatbot.info_requested"


def open_from_event(body: bytes) -> None:
    try:
        event = InfoRequested.model_validate_json(body)
    except ValidationError as exc:
        raise ChatError(400, "claim.info_requested is not valid") from exc
    log.info("open claim_id=%s", event.claim_id)
    ensure_opening(event.claim_id, event.submitter.id, SERVICE_ACTOR)


async def _publish(channel, exchange_name: str, routing_key: str, msg, headers: dict) -> None:
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


async def schedule_retry(channel, msg, attempt: int) -> None:
    routing_key = RETRY_10 if attempt == 2 else RETRY_60
    headers = dict(msg.headers or {})
    headers["x-attempt"] = attempt
    await _publish(channel, "claims.retry", routing_key, msg, headers)


async def on_message(msg, channel) -> None:
    attempt = int((msg.headers or {}).get("x-attempt", 1))
    try:
        await asyncio.to_thread(open_from_event, msg.body)
        await msg.ack()
    except ChatError as exc:
        log.info("info_requested failed attempt=%s status=%s", attempt, exc.status_code)
        if exc.status_code == 400 or attempt >= 3:
            await dead_letter(channel, msg, exc, attempt)
        else:
            await schedule_retry(channel, msg, attempt + 1)
        await msg.ack()
    except Exception as exc:
        log.exception("info_requested failed attempt=%s", attempt)
        if attempt >= 3:
            await dead_letter(channel, msg, exc, attempt)
        else:
            await schedule_retry(channel, msg, attempt + 1)
        await msg.ack()


async def consume(stop: asyncio.Event) -> None:
    import os

    connection = await aio_pika.connect(os.environ["RABBITMQ_URL"])
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)
    await channel.declare_exchange("claims.events", ExchangeType.TOPIC, durable=True)
    await channel.declare_exchange("claims.retry", ExchangeType.DIRECT, durable=True)
    await channel.declare_exchange("claims.dlx", ExchangeType.DIRECT, durable=True)
    queue = await channel.declare_queue(
        "chatbot.info_requested",
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-delivery-limit": 5,
            "x-dead-letter-exchange": "claims.dlx",
            "x-dead-letter-routing-key": "chatbot.info_requested",
        },
    )
    async with queue.iterator() as incoming:
        async for msg in incoming:
            if stop.is_set():
                break
            await on_message(msg, channel)
    await connection.close()
