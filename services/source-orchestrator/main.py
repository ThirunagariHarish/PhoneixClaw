import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from shared.graceful_shutdown import shutdown

SERVICE_NAME = "source-orchestrator"
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def _run_orchestrator(service):
    try:
        await service.start()
        await service.run()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Orchestrator error")


_orchestrator = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _orchestrator
    from services.source_orchestrator.src.orchestrator import SourceOrchestrator

    _orchestrator = SourceOrchestrator()
    task = asyncio.create_task(_run_orchestrator(_orchestrator))
    shutdown.register(lambda: _orchestrator.stop())
    logger.info("%s ready", SERVICE_NAME)
    yield
    await shutdown.run_cleanup()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ready", "service": SERVICE_NAME}


@app.get("/debug/workers")
async def debug_workers():
    if not _orchestrator:
        return {"error": "orchestrator not initialized"}
    import time as _time
    workers = {}
    for sid, w in _orchestrator._active_workers.items():
        task = w.get("task")
        workers[sid] = {
            "alive": task is not None and not task.done(),
            "status": w.get("status", "unknown"),
            "done": task.done() if task else True,
        }
    backoff = {}
    for sid, (attempts, ready_at) in _orchestrator._backoff.items():
        backoff[sid] = {
            "attempts": attempts,
            "ready_in_seconds": max(0, round(ready_at - _time.monotonic(), 1)),
        }
    return {
        "active_workers": workers,
        "worker_count": len(workers),
        "backoff": backoff,
        "running": _orchestrator._running,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
