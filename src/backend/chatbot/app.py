"""Missing-info chatbot. The browser talks to the portal, which calls this service."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from checks import platform_status  # noqa: E402
from chatbot.consumer import consume  # noqa: E402
from chatbot.errors import ChatError  # noqa: E402
from chatbot.inquiry.service import post_inquiry, read_inquiry  # noqa: E402
from chatbot.service import add_note, ensure_opening, post_message  # noqa: E402

PORT = 47112
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")


class TextBody(BaseModel):
    text: str = Field(min_length=1)
    submitter_id: str = Field(min_length=1)


def _actor(request: Request) -> dict:
    return {
        "actor_type": request.headers.get("x-actor-type", "service"),
        "actor_id": request.headers.get("x-actor-id", "chatbot"),
        "actor_role": request.headers.get("x-actor-role", "service"),
        "correlation_id": request.headers.get("x-correlation-id") or "",
    }


def _call(fn, *args):
    try:
        return fn(*args)
    except ChatError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    task = asyncio.create_task(consume(stop))
    yield
    stop.set()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Chatbot", lifespan=lifespan)


@app.get("/health")
async def health():
    status = await platform_status()
    code = 200 if status["status"] == "ok" else 503
    return JSONResponse(status_code=code, content=status)


@app.get("/conversations/{claim_id}")
def read_conversation(claim_id: str, submitter_id: str, request: Request):
    return _call(ensure_opening, claim_id, submitter_id, _actor(request))


@app.post("/conversations/{claim_id}/messages")
def write_message(claim_id: str, body: TextBody, request: Request):
    return _call(post_message, claim_id, body.submitter_id, body.text, _actor(request))


@app.post("/conversations/{claim_id}/notes")
def write_note(claim_id: str, body: TextBody, request: Request):
    return _call(add_note, claim_id, body.submitter_id, body.text, _actor(request))


@app.get("/inquiries/{member_id}")
def read_member_inquiry(member_id: str, request: Request):
    return _call(read_inquiry, member_id, _actor(request))


@app.post("/inquiries/{member_id}/messages")
def write_member_inquiry(member_id: str, body: TextBody, request: Request):
    if body.submitter_id != member_id:
        raise HTTPException(status_code=403, detail="This conversation belongs to another member")
    return _call(post_inquiry, member_id, body.text, _actor(request))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
