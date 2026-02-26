import asyncio
import itertools
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from shared.graceful_shutdown import shutdown
from shared.metrics import create_metrics_route

SERVICE_NAME = "trade-executor"
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

_healthy = False
_dry_run_mode = False


async def _run_executor(service):
    global _healthy, _dry_run_mode
    for attempt in itertools.count(1):
        try:
            await service.start()
            _healthy = True
            _dry_run_mode = service._dry_run
            logger.info("Trade executor connected to Kafka (attempt %d)", attempt)
            await service.run()
            break
        except asyncio.CancelledError:
            break
        except Exception:
            _healthy = False
            delay = min(5 * (2 ** (attempt - 1)), 60)
            logger.exception(
                "Trade executor startup failed (attempt %d), retrying in %ds",
                attempt, delay,
            )
            await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.trade_executor.src.executor import TradeExecutorService

    service = TradeExecutorService()
    task = asyncio.create_task(_run_executor(service))
    shutdown.register(lambda: service.stop())
    logger.info("%s starting", SERVICE_NAME)
    yield
    await shutdown.run_cleanup()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


create_metrics_route(app)


@app.get("/health")
async def health():
    if _healthy:
        return {
            "status": "ready",
            "service": SERVICE_NAME,
            "kafka_connected": True,
            "dry_run_mode": _dry_run_mode,
        }
    return JSONResponse(
        status_code=503,
        content={
            "status": "starting",
            "service": SERVICE_NAME,
            "kafka_connected": False,
            "dry_run_mode": _dry_run_mode,
        },
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8008)
