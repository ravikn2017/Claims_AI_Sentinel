"""Fraud detection service. The browser talks to the portal."""

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

from checks import platform_status  # noqa: E402
from fraud_detection.scoring import score_claim  # noqa: E402
from fraud_detection.training import (  # noqa: E402
    TechniqueUnavailable,
    TrainingBusy,
    UnknownTechnique,
    activate,
    report_for,
    train,
    train_if_due,
)

PORT = 47114
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
log = logging.getLogger("fraud_detection")


class ScoreBody(BaseModel):
    claim_id: str
    claim: dict


class SelectBody(BaseModel):
    technique: str


async def _refresh_loop(stop: asyncio.Event) -> None:
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=24 * 60 * 60)
            return
        except asyncio.TimeoutError:
            try:
                await asyncio.to_thread(train_if_due)
            except Exception:
                log.exception("scheduled fraud training failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await asyncio.to_thread(train_if_due)
    except Exception:
        log.exception("startup fraud training failed")
    stop = asyncio.Event()
    task = asyncio.create_task(_refresh_loop(stop))
    yield
    stop.set()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Fraud detection", lifespan=lifespan)


@app.get("/health")
async def health():
    status = await platform_status()
    code = 200 if status["status"] == "ok" else 503
    return JSONResponse(status_code=code, content=status)


@app.get("/model/latest")
def latest_model():
    report = report_for()
    if not report:
        raise HTTPException(status_code=404, detail="No fraud model has been trained yet")
    return report


@app.post("/model/train")
def train_model():
    try:
        return train()
    except TrainingBusy as exc:
        raise HTTPException(status_code=409, detail="A training run is already in progress") from exc
    except Exception as exc:
        log.exception("fraud training failed")
        raise HTTPException(status_code=503, detail="Fraud model training failed") from exc


@app.post("/model/select")
def select_model(body: SelectBody):
    try:
        return activate(body.technique)
    except UnknownTechnique as exc:
        raise HTTPException(status_code=422, detail="Choose one of the four trained techniques") from exc
    except TechniqueUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/score")
def score(body: ScoreBody):
    return score_claim(body.claim, body.claim_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
