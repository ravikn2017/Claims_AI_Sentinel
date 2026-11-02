"""Turn a PDF dropped in the inbox into the same claim.submitted message."""

from __future__ import annotations

import asyncio
import logging
import shutil

from db_url import inbox_dir
from portal.app.intake import ShapeError, accept_submission

log = logging.getLogger("portal.watcher")


def scan_once() -> list[str]:
    inbox = inbox_dir()
    processed = inbox / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for path in sorted(inbox.glob("*.pdf")):
        content = path.read_bytes()
        try:
            submission_id = accept_submission(
                channel="email",
                submitter_type="provider",
                submitter_id="email-drop",
                claim=None,
                files=[(path.name, content, "claim_form")],
                extraction_required=True,
            )
        except ShapeError:
            log.info("skipped inbox file")
            continue
        shutil.move(str(path), processed / path.name)
        log.info("inbox submission_id=%s", submission_id)
        created.append(submission_id)
    return created


async def watch_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(scan_once)
        except Exception:
            log.exception("inbox watcher failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            continue
