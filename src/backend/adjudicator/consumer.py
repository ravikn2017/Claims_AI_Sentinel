"""Consume claim.ready_for_adjudication. Ack after the run has a checkpoint."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from pydantic import ValidationError

from adjudicator.errors import AdjudicationError
from adjudicator.service import start_run
from contracts.models import ReadyForAdjudication

log = logging.getLogger("adjudicator.consumer")

QUEUE = "adjudicator.ready"
RETRY_10 = "adjudicator.ready.retry.10s"
RETRY_60 = "adjudicator.ready.retry.60s"
DLQ_KEY = "adjudicator.ready"


def handle_body(body: bytes, correlation_id: str | None) -> None:
    try:
        event = ReadyForAdjudication.model_validate_json(body)
    except ValidationError as exc:
        raise AdjudicationError(400, "claim.ready_for_adjudication is not valid") from exc
    log.info("start claim_id=%s attempt=%s", event.claim_id, event.adjudication_attempt)
    start_run(
        event.claim_id,
        event.adjudication_attempt,
        event.submission_id,
        correlation_id or str(event.message_id),
    )


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
        await asyncio.to_thread(handle_body, msg.body, msg.correlation_id)
        await msg.ack()
    except AdjudicationError as exc:
        log.info("ready failed attempt=%s status=%s", attempt, exc.status_code)
        if exc.status_code in {400, 404, 422} or attempt >= 3:
            await dead_letter(channel, msg, exc, attempt)
        else:
            await schedule_retry(channel, msg, attempt + 1)
        await msg.ack()
    except Exception as exc:
        log.exception("ready failed attempt=%s", attempt)
        if attempt >= 3:
            await dead_letter(channel, msg, exc, attempt)
        else:
            await schedule_retry(channel, msg, attempt + 1)
        await msg.ack()


def _queue_args(dlx_key: str) -> dict:
    return {
        "x-queue-type": "quorum",
        "x-delivery-limit": 5,
        "x-dead-letter-exchange": "claims.dlx",
        "x-dead-letter-routing-key": dlx_key,
    }


async def consume(stop: asyncio.Event) -> None:
    connection = await aio_pika.connect(os.environ["RABBITMQ_URL"])
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)
    events = await channel.declare_exchange("claims.events", ExchangeType.TOPIC, durable=True)
    retry = await channel.declare_exchange("claims.retry", ExchangeType.DIRECT, durable=True)
    dlx = await channel.declare_exchange("claims.dlx", ExchangeType.DIRECT, durable=True)
    queue = await channel.declare_queue(QUEUE, durable=True, arguments=_queue_args(DLQ_KEY))
    await queue.bind(events, routing_key="claim.ready_for_adjudication")
    dead = await channel.declare_queue(
        "adjudicator.ready.dlq",
        durable=True,
        arguments={"x-queue-type": "quorum"},
    )
    await dead.bind(dlx, routing_key=DLQ_KEY)
    for queue_name, ttl in ((RETRY_10, 10000), (RETRY_60, 60000)):
        delay = await channel.declare_queue(
            queue_name,
            durable=True,
            arguments={
                "x-message-ttl": ttl,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": QUEUE,
            },
        )
        await delay.bind(retry, routing_key=queue_name)
    async with queue.iterator() as incoming:
        async for msg in incoming:
            if stop.is_set():
                break
            await on_message(msg, channel)
    await connection.close()
