import asyncio
import logging
import sys
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from shared.graceful_shutdown import shutdown
from shared.metrics import create_metrics_route

SERVICE_NAME = "notification-service"
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def _persist_notification(event: dict, title: str, body: str, priority: str = "NORMAL"):
    """Write notification to the notification_log table."""
    try:
        from shared.models.database import AsyncSessionLocal
        from shared.models.trade import NotificationLog

        user_id = event.get("user_id")
        if not user_id:
            return

        async with AsyncSessionLocal() as session:
            record = NotificationLog(
                user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
                notification_type=event.get("status", "INFO"),
                channel="dashboard",
                priority=priority,
                title=title,
                body=body,
                status="SENT",
            )
            session.add(record)
            await session.commit()
    except Exception:
        logger.exception("Failed to persist notification")


async def _run_notification_service(service):
    import itertools
    for attempt in itertools.count(1):
        try:
            await service.start()
            logger.info("Notification service connected to Kafka (attempt %d)", attempt)
            await service.run()
            break
        except asyncio.CancelledError:
            break
        except Exception:
            delay = min(5 * (2 ** (attempt - 1)), 60)
            logger.exception(
                "Notification service startup failed (attempt %d), retrying in %ds",
                attempt, delay,
            )
            await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.notification_service.src.notification import NotificationService

    service = NotificationService()

    async def _log_handler(message: str, event: dict):
        status = event.get("status", "INFO")
        ticker = event.get("ticker", "")
        action = event.get("action", "")
        priority = "HIGH" if status in ("ERROR", "REJECTED") else "NORMAL"
        title = f"{status}: {action} {ticker}"
        body = message
        await _persist_notification(event, title, body, priority)
        logger.info("Notification: %s", message)

    service.register_handler("log", _log_handler)

    from services.notification_service.src.daily_report import run_daily_report_scheduler

    task = asyncio.create_task(_run_notification_service(service))
    report_task = asyncio.create_task(run_daily_report_scheduler())
    shutdown.register(lambda: service.stop())
    logger.info("%s ready (daily report scheduler started)", SERVICE_NAME)
    yield
    await shutdown.run_cleanup()
    report_task.cancel()
    task.cancel()
    for t in (task, report_task):
        try:
            await t
        except asyncio.CancelledError:
            pass


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


create_metrics_route(app)


@app.get("/health")
async def health():
    return {"status": "ready", "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010)
