import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from shared.graceful_shutdown import shutdown

SERVICE_NAME = "audit-writer"
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def _run_service(service, name: str):
    try:
        await service.start()
        await service.run()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("%s error", name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.audit_writer.src.raw_message_writer import RawMessageWriterService
    from services.audit_writer.src.writer import AuditWriterService

    audit_svc = AuditWriterService()
    raw_msg_svc = RawMessageWriterService()

    audit_task = asyncio.create_task(_run_service(audit_svc, "audit-writer"))
    raw_msg_task = asyncio.create_task(_run_service(raw_msg_svc, "raw-message-writer"))

    shutdown.register(lambda: audit_svc.stop())
    shutdown.register(lambda: raw_msg_svc.stop())
    logger.info("%s ready (audit + raw-message writers)", SERVICE_NAME)
    yield
    await shutdown.run_cleanup()
    for t in (audit_task, raw_msg_task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ready", "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8012)
