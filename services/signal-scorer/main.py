import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.graceful_shutdown import shutdown
from services.signal_scorer.src.scorer import SignalScorerService

SERVICE_NAME = "signal-scorer"
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

svc: SignalScorerService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global svc
    svc = SignalScorerService()
    try:
        await svc.start()
        asyncio.create_task(svc.run())
        logger.info("%s ready", SERVICE_NAME)
        yield
    finally:
        if svc:
            await svc.stop()
        await shutdown.run_cleanup()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ready" if svc else "starting",
        "service": SERVICE_NAME,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8013)
