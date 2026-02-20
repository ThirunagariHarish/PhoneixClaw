import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.graceful_shutdown import shutdown
from services.api_gateway.src.middleware import JWTMiddleware
from services.auth_service.src.auth import router as auth_router
from services.api_gateway.src.routes.accounts import router as accounts_router
from services.api_gateway.src.routes.sources import router as sources_router
from services.api_gateway.src.routes.mappings import router as mappings_router
from services.api_gateway.src.routes.trades import router as trades_router
from services.api_gateway.src.routes.metrics import router as metrics_router
from services.api_gateway.src.routes.notifications import router as notifications_router
from services.api_gateway.src.routes.system import router as system_router
from services.api_gateway.src.routes.chat import router as chat_router, set_kafka_producer

SERVICE_NAME = "api-gateway"
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


_kafka_producer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _kafka_producer
    try:
        from shared.kafka_utils.producer import KafkaProducerWrapper

        _kafka_producer = KafkaProducerWrapper()
        await _kafka_producer.start()
        set_kafka_producer(_kafka_producer)
        logger.info("Kafka producer initialized for chat")
    except Exception:
        logger.warning("Kafka producer unavailable — chat messages will not be routed to trade pipeline")
    logger.info("%s ready", SERVICE_NAME)
    yield
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
app.include_router(accounts_router)
app.include_router(sources_router)
app.include_router(mappings_router)
app.include_router(trades_router)
app.include_router(metrics_router)
app.include_router(notifications_router)
app.include_router(system_router)
app.include_router(chat_router)


@app.get("/health")
async def health():
    return {"status": "ready", "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8011)
