"""Reject PENDING_INFO claims that are past their reply deadline."""

from __future__ import annotations

import asyncio
import logging
import os

from payer_service.app.db import payer_engine
from payer_service.app.repository import sweep_once

log = logging.getLogger("payer.sweeper")


def run_sweep() -> list[str]:
    with payer_engine().begin() as conn:
        rejected = sweep_once(conn)
    for claim_id in rejected:
        log.info("info timeout claim_id=%s", claim_id)
    return rejected


async def sweep_loop(stop: asyncio.Event) -> None:
    interval = int(os.environ.get("SWEEPER_INTERVAL_SECONDS", "900"))
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_sweep)
        except Exception:
            log.exception("sweeper failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue
