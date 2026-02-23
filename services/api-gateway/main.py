import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.api_gateway.src.middleware import JWTMiddleware
from services.api_gateway.src.routes.accounts import router as accounts_router
from services.api_gateway.src.routes.admin import router as admin_router
from services.api_gateway.src.routes.backtest import router as backtest_router
from services.api_gateway.src.routes.chat import router as chat_router
from services.api_gateway.src.routes.chat import set_kafka_producer
from services.api_gateway.src.routes.mappings import router as mappings_router
from services.api_gateway.src.routes.messages import router as messages_router
from services.api_gateway.src.routes.metrics import router as metrics_router
from services.api_gateway.src.routes.notifications import router as notifications_router
from services.api_gateway.src.routes.pipelines import router as pipelines_router
from services.api_gateway.src.routes.positions import router as positions_router
from services.api_gateway.src.routes.sources import router as sources_router
from services.api_gateway.src.routes.system import router as system_router
from services.api_gateway.src.routes.trades import router as trades_router
from services.api_gateway.src.websocket import router as ws_router
from services.api_gateway.src.websocket import run_ws_consumer
from services.auth_service.src.auth import router as auth_router
from shared.graceful_shutdown import shutdown
from shared.metrics import create_metrics_route

SERVICE_NAME = "api-gateway"
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


_kafka_producer = None


async def _run_migrations():
    """Run DB schema creation and any needed migrations."""
    import sqlalchemy as sa

    from shared.models.database import engine, init_db

    await init_db()
    migrations = [
        "ALTER TABLE trades ALTER COLUMN trading_account_id DROP NOT NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(30) NOT NULL DEFAULT 'trader'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE channels ADD COLUMN IF NOT EXISTS guild_id VARCHAR(100)",
        "ALTER TABLE channels ADD COLUMN IF NOT EXISTS guild_name VARCHAR(200)",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            try:
                await conn.execute(sa.text(sql))
            except Exception:
                pass
    logger.info("Database schema ready")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _kafka_producer
    try:
        await _run_migrations()
    except Exception:
        logger.warning("DB migration step skipped (may already be applied)", exc_info=True)
    try:
        from shared.kafka_utils.producer import KafkaProducerWrapper

        _kafka_producer = KafkaProducerWrapper()
        await _kafka_producer.start()
        set_kafka_producer(_kafka_producer)
        logger.info("Kafka producer initialized for chat")
    except Exception:
        logger.warning("Kafka producer unavailable — chat messages will not be routed to trade pipeline")
    import asyncio

    _ws_task = None
    _retention_task = None
    try:
        _ws_task = asyncio.create_task(run_ws_consumer())
        logger.info("WebSocket consumer started")
    except Exception:
        logger.warning("WebSocket consumer not started")

    async def _retention_loop():
        from shared.retention import purge_old_records
        while True:
            await asyncio.sleep(86400)
            try:
                results = await purge_old_records()
                logger.info("Retention purge completed: %s", results)
            except Exception:
                logger.exception("Retention purge failed")

    try:
        _retention_task = asyncio.create_task(_retention_loop())
    except Exception:
        pass
    logger.info("%s ready", SERVICE_NAME)
    yield
    if _retention_task:
        _retention_task.cancel()
    if _ws_task:
        _ws_task.cancel()
    if _kafka_producer:
        await _kafka_producer.stop()
    await shutdown.run_cleanup()


app = FastAPI(title="Phoenix Trade Bot API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(JWTMiddleware)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(accounts_router)
app.include_router(backtest_router)
app.include_router(sources_router)
app.include_router(pipelines_router)
app.include_router(mappings_router)
app.include_router(trades_router)
app.include_router(positions_router)
app.include_router(metrics_router)
app.include_router(notifications_router)
app.include_router(system_router)
app.include_router(chat_router)
app.include_router(messages_router)
app.include_router(ws_router)


create_metrics_route(app)


@app.get("/health")
async def health():
    return {"status": "ready", "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8011)
