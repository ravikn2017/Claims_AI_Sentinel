import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from checks import platform_status  # noqa: E402
from portal.app.auth import router as auth_router  # noqa: E402
from portal.app.intake import DuplicateSubmission, ShapeError, accept_submission, parse_request  # noqa: E402
from portal.app.publisher import publish_loop  # noqa: E402
from portal.app.db import portal_engine  # noqa: E402
from portal.app.ui import router as ui_router  # noqa: E402
from portal.app.watcher import watch_loop  # noqa: E402
from sqlalchemy import text  # noqa: E402

PORT = 47110
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(publish_loop(stop)),
        asyncio.create_task(watch_loop(stop)),
    ]
    yield
    stop.set()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Payer portal", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(ui_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:47117"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    status = await platform_status()
    code = 200 if status["status"] == "ok" else 503
    return JSONResponse(status_code=code, content=status)


async def _files_from_form(form) -> list[tuple[str, bytes, str]]:
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return []
    content = await upload.read()
    if not content:
        return []
    filename = getattr(upload, "filename", None) or "upload.pdf"
    content_type = getattr(upload, "content_type", "") or ""
    if content_type not in {"application/pdf", "application/octet-stream", ""} and not filename.lower().endswith(".pdf"):
        raise ShapeError("Only PDF files are accepted")
    doc_type = str(form.get("doc_type") or "medical_record")
    return [(filename, content, doc_type)]


async def _accept(request: Request, channel: str):
    content_type = request.headers.get("content-type", "")
    files: list[tuple[str, bytes, str]] = []
    if content_type.startswith("multipart/"):
        form = await request.form()
        raw = form.get("payload")
        if raw is None:
            raise HTTPException(status_code=400, detail="payload is required")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="payload is not valid JSON") from exc
        try:
            files = await _files_from_form(form)
        except ShapeError as exc:
            raise HTTPException(status_code=400, detail=exc.message) from exc
    else:
        payload = await request.json()
    try:
        parsed = parse_request(payload)
        submission_id = accept_submission(
            channel=channel,
            submitter_type=parsed.submitter_type,
            submitter_id=parsed.submitter_id,
            claim=parsed.claim,
            files=files,
            submission_id=parsed.submission_id,
            extraction_required=False,
        )
    except ShapeError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except DuplicateSubmission as exc:
        raise HTTPException(status_code=409, detail={"submission_id": exc.submission_id, "error": "duplicate submission_id"}) from exc
    return {"submission_id": submission_id, "publish_status": "pending"}


@app.post("/submissions")
async def create_submission(request: Request):
    return await _accept(request, "portal")


@app.post("/partner/submissions")
async def partner_submission(request: Request):
    return await _accept(request, "api")


@app.get("/submissions/{submission_id}/status")
async def submission_status(submission_id: str):
    with portal_engine().connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM portal.submission_log WHERE submission_id = :submission_id"),
            {"submission_id": submission_id},
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    url = os.environ.get("PAYER_SERVICE_URL", "http://127.0.0.1:47111")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                f"{url}/submissions/{submission_id}/status",
                headers={
                    "X-Actor-Type": "service",
                    "X-Actor-Id": "portal",
                    "X-Actor-Role": "service",
                    "X-Correlation-ID": submission_id,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Payer service is unavailable") from exc
    return JSONResponse(status_code=response.status_code, content=response.json())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
