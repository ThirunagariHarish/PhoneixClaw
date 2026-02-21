import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from shared.graceful_shutdown import shutdown
from shared.metrics import create_metrics_route

SERVICE_NAME = "trade-gateway"
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def _run_gateway(service):
    try:
        await service.start()
        await service.run()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Trade gateway error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.trade_gateway.src.gateway import TradeGatewayService

    service = TradeGatewayService()
    task = asyncio.create_task(_run_gateway(service))
    shutdown.register(lambda: service.stop())
    logger.info("%s ready", SERVICE_NAME)
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
    return {"status": "ready", "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8007)
