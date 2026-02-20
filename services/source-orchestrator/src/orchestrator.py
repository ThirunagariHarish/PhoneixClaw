import asyncio
import logging

from sqlalchemy import select

from shared.models.database import AsyncSessionLocal
from shared.models.trade import DataSource

logger = logging.getLogger(__name__)

class SourceOrchestrator:
    def __init__(self):
        self._active_workers: dict[str, dict] = {}
        self._running = False

    async def start(self):
        self._running = True
        logger.info("Source orchestrator started")

    async def stop(self):
        self._running = False
        for source_id, worker in self._active_workers.items():
            logger.info("Stopping worker for source %s", source_id)
        self._active_workers.clear()
        logger.info("Source orchestrator stopped")

    async def reconcile(self):
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(DataSource).where(DataSource.enabled.is_(True)))
            sources = result.scalars().all()

        desired = {str(s.id) for s in sources}
        active = set(self._active_workers.keys())

        to_start = desired - active
        to_stop = active - desired

        for sid in to_stop:
            logger.info("Stopping worker for removed/disabled source %s", sid)
            del self._active_workers[sid]

        for sid in to_start:
            logger.info("Starting worker for source %s", sid)
            self._active_workers[sid] = {"status": "running"}

        return {"started": list(to_start), "stopped": list(to_stop), "active": len(self._active_workers)}

    async def run(self, poll_interval: float = 30.0):
        while self._running:
            try:
                result = await self.reconcile()
                logger.debug("Reconciliation: %s", result)
            except Exception:
                logger.exception("Reconciliation failed")
            await asyncio.sleep(poll_interval)
