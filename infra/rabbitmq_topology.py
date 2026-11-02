import asyncio
import os
from pathlib import Path

import aio_pika
from aio_pika import ExchangeType
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


async def declare() -> None:
    connection = await aio_pika.connect(os.environ["RABBITMQ_URL"])
    channel = await connection.channel()

    events = await channel.declare_exchange("claims.events", ExchangeType.TOPIC, durable=True)
    retry = await channel.declare_exchange("claims.retry", ExchangeType.DIRECT, durable=True)
    dlx = await channel.declare_exchange("claims.dlx", ExchangeType.DIRECT, durable=True)

    submitted = await channel.declare_queue(
        "payer.claim_submitted",
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-delivery-limit": 5,
            "x-dead-letter-exchange": "claims.dlx",
            "x-dead-letter-routing-key": "payer.claim_submitted",
        },
    )
    await submitted.bind(events, routing_key="claim.submitted")

    dlq = await channel.declare_queue(
        "payer.claim_submitted.dlq",
        durable=True,
        arguments={"x-queue-type": "quorum"},
    )
    await dlq.bind(dlx, routing_key="payer.claim_submitted")

    for queue_name, ttl in (
        ("payer.claim_submitted.retry.10s", 10000),
        ("payer.claim_submitted.retry.60s", 60000),
    ):
        delay = await channel.declare_queue(
            queue_name,
            durable=True,
            arguments={
                "x-message-ttl": ttl,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": "payer.claim_submitted",
            },
        )
        await delay.bind(retry, routing_key=queue_name)

    info = await channel.declare_queue(
        "chatbot.info_requested",
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-delivery-limit": 5,
            "x-dead-letter-exchange": "claims.dlx",
            "x-dead-letter-routing-key": "chatbot.info_requested",
        },
    )
    await info.bind(events, routing_key="claim.info_requested")

    info_dlq = await channel.declare_queue(
        "chatbot.info_requested.dlq",
        durable=True,
        arguments={"x-queue-type": "quorum"},
    )
    await info_dlq.bind(dlx, routing_key="chatbot.info_requested")

    for queue_name, ttl in (
        ("chatbot.info_requested.retry.10s", 10000),
        ("chatbot.info_requested.retry.60s", 60000),
    ):
        delay = await channel.declare_queue(
            queue_name,
            durable=True,
            arguments={
                "x-message-ttl": ttl,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": "chatbot.info_requested",
            },
        )
        await delay.bind(retry, routing_key=queue_name)

    ready = await channel.declare_queue(
        "adjudicator.ready",
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-delivery-limit": 5,
            "x-dead-letter-exchange": "claims.dlx",
            "x-dead-letter-routing-key": "adjudicator.ready",
        },
    )
    await ready.bind(events, routing_key="claim.ready_for_adjudication")

    ready_dlq = await channel.declare_queue(
        "adjudicator.ready.dlq",
        durable=True,
        arguments={"x-queue-type": "quorum"},
    )
    await ready_dlq.bind(dlx, routing_key="adjudicator.ready")

    for queue_name, ttl in (
        ("adjudicator.ready.retry.10s", 10000),
        ("adjudicator.ready.retry.60s", 60000),
    ):
        delay = await channel.declare_queue(
            queue_name,
            durable=True,
            arguments={
                "x-message-ttl": ttl,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": "adjudicator.ready",
            },
        )
        await delay.bind(retry, routing_key=queue_name)

    await connection.close()
    print("declared claims.events, claims.retry, claims.dlx")
    print("declared payer.claim_submitted, retry.10s, retry.60s, dlq")
    print("declared chatbot.info_requested, retry.10s, retry.60s, dlq")
    print("declared adjudicator.ready, retry.10s, retry.60s, dlq")


if __name__ == "__main__":
    asyncio.run(declare())
