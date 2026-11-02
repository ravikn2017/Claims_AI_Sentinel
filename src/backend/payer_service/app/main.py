import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from checks import platform_status  # noqa: E402
from payer_service.app.api import router  # noqa: E402
from payer_service.app.consumer import consume  # noqa: E402
from payer_service.app.relay import relay_loop  # noqa: E402
from payer_service.app.sweeper import sweep_loop  # noqa: E402

PORT = 47111
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(consume(stop)),
        asyncio.create_task(relay_loop(stop)),
        asyncio.create_task(sweep_loop(stop)),
    ]
    yield
    stop.set()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Payer service", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health():
    status = await platform_status()
    code = 200 if status["status"] == "ok" else 503
    return JSONResponse(status_code=code, content=status)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
