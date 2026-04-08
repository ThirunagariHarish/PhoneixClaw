"""
Execution service entrypoint — runs the trade intent consumer.
"""
import asyncio
import logging
import os

import redis.asyncio as redis
from fastapi import FastAPI
from prometheus_client import generate_latest
from starlette.responses import Response

from .consumer import TradeIntentConsumer
from .executor import BrokerExecutor
from .risk_chain import RiskCheckChain

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Phoenix Execution Service", version="1.0.0")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_consumer_task = None


@app.get("/health")
async def health():
    return {"status": "ready", "service": "phoenix-execution"}


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")


async def run_consumer():
    global _consumer_task
    r = redis.from_url(REDIS_URL, decode_responses=False)
    chain = RiskCheckChain()
    executor = BrokerExecutor()
    consumer = TradeIntentConsumer(r, chain, executor)
    await consumer.start()


@app.on_event("startup")
async def startup():
    global _consumer_task
    _consumer_task = asyncio.create_task(run_consumer())
    logger.info("Execution service started")


@app.on_event("shutdown")
async def shutdown():
    global _consumer_task
    if _consumer_task:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8020)
