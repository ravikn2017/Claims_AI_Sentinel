"""Claims adjudicator. The browser talks to the portal. Callbacks resume a paused run."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from adjudicator.consumer import consume  # noqa: E402
from adjudicator.errors import AdjudicationError  # noqa: E402
from adjudicator.relay import relay_loop  # noqa: E402
from adjudicator.service import resume_investigation, resume_review  # noqa: E402
from checks import platform_status  # noqa: E402

PORT = 47113
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")


class InvestigationBody(BaseModel):
    outcome: str
    notes: str = ""


class ReviewBody(BaseModel):
    decision: str
    allowed_amount: float = 0
    reviewer: str = ""
    notes: str = ""


def _call(fn, *args):
    try:
        return fn(*args)
    except AdjudicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(consume(stop)),
        asyncio.create_task(relay_loop(stop)),
    ]
    yield
    stop.set()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Adjudicator", lifespan=lifespan)


@app.get("/health")
async def health():
    status = await platform_status()
    code = 200 if status["status"] == "ok" else 503
    return JSONResponse(status_code=code, content=status)


@app.post("/adjudications/{claim_id}/{attempt}/investigation-result")
def investigation_result(claim_id: str, attempt: int, body: InvestigationBody):
    return _call(resume_investigation, claim_id, attempt, body.outcome, body.notes)


@app.post("/adjudications/{claim_id}/{attempt}/review-decision")
def review_decision(claim_id: str, attempt: int, body: ReviewBody):
    return _call(resume_review, claim_id, attempt, body.decision, body.allowed_amount, body.reviewer, body.notes)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
