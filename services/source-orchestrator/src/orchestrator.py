import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from shared.crypto.credentials import decrypt_credentials
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.models.database import AsyncSessionLocal
from shared.models.trade import DataSource

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 600
BASE_BACKOFF_SECONDS = 10


class SourceOrchestrator:
    def __init__(self):
        self._active_workers: dict[str, dict] = {}
        self._running = False
        self._producer = KafkaProducerWrapper()
        self._backoff: dict[str, tuple[int, float]] = {}

    async def start(self):
        self._running = True
        await self._producer.start()
        logger.info("Source orchestrator started")

    async def stop(self):
        self._running = False
        for source_id, worker in list(self._active_workers.items()):
            task = worker.get("task")
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            logger.info("Stopped worker for source %s", source_id)
        self._active_workers.clear()
        await self._producer.stop()
        logger.info("Source orchestrator stopped")

    async def _update_source_status(
        self, source_id: str, status: str, error_msg: str | None = None
    ):
        try:
            async with AsyncSessionLocal() as session:
                import uuid as _uuid

                db_source = await session.get(DataSource, _uuid.UUID(source_id))
                if db_source:
                    db_source.connection_status = status
                    if status == "CONNECTED":
                        db_source.last_connected_at = datetime.now(timezone.utc)
                    db_source.updated_at = datetime.now(timezone.utc)
                    await session.commit()
        except Exception:
            logger.exception("Failed to update status for source %s", source_id)

    def _cleanup_dead_tasks(self):
        dead = [
            sid for sid, w in self._active_workers.items()
            if w.get("task") and w["task"].done()
        ]
        for sid in dead:
            task = self._active_workers[sid]["task"]
            exc = task.exception() if not task.cancelled() else None
            if exc:
                logger.warning(
                    "Worker for source %s died with error: %s", sid, exc
                )
            self._active_workers.pop(sid, None)
        return dead

    def _is_in_backoff(self, source_id: str) -> bool:
        if source_id not in self._backoff:
            return False
        _, ready_at = self._backoff[source_id]
        if time.monotonic() >= ready_at:
            return False
        return True

    def _record_failure(self, source_id: str):
        attempts, _ = self._backoff.get(source_id, (0, 0.0))
        attempts += 1
        delay = min(BASE_BACKOFF_SECONDS * (2 ** (attempts - 1)), MAX_BACKOFF_SECONDS)
        self._backoff[source_id] = (attempts, time.monotonic() + delay)
        logger.info("Source %s backoff: attempt %d, retry in %ds", source_id, attempts, delay)

    def _clear_backoff(self, source_id: str):
        self._backoff.pop(source_id, None)

    def _parse_channel_ids(self, channel_ids_raw) -> list[int]:
        if not channel_ids_raw:
            return []
        if isinstance(channel_ids_raw, list):
            parts = [str(c).strip() for c in channel_ids_raw]
        else:
            parts = [c.strip() for c in str(channel_ids_raw).split(",")]
        return [int(c) for c in parts if c.isdigit()]

    async def reconcile(self):
        dead_sources = self._cleanup_dead_tasks()
        for sid in dead_sources:
            asyncio.create_task(self._update_source_status(sid, "ERROR"))
            self._record_failure(sid)

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DataSource).where(DataSource.enabled.is_(True))
            )
            sources = result.scalars().all()
            source_map = {str(s.id): s for s in sources}

        desired = set(source_map.keys())
        active = set(self._active_workers.keys())

        to_start = desired - active
        to_stop = active - desired

        for sid in to_stop:
            worker = self._active_workers.pop(sid, None)
            if worker:
                task = worker.get("task")
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
            self._clear_backoff(sid)
            logger.info("Stopped worker for removed/disabled source %s", sid)

        for sid in to_start:
            if self._is_in_backoff(sid):
                continue

            source = source_map[sid]
            if source.source_type != "discord":
                logger.info("Skipping non-discord source %s (type=%s)", sid, source.source_type)
                continue
            try:
                creds = decrypt_credentials(source.credentials_encrypted)
                token = creds.get("user_token") or creds.get("bot_token", "")
                channel_ids = self._parse_channel_ids(creds.get("channel_ids", ""))

                await self._update_source_status(sid, "CONNECTING")

                task = asyncio.create_task(
                    self._run_ingestor(
                        token=token,
                        channel_ids=channel_ids,
                        user_id=str(source.user_id),
                        auth_type=source.auth_type,
                        data_source_id=sid,
                    )
                )
                self._active_workers[sid] = {"task": task, "status": "connecting"}

                logger.info(
                    "Started Discord ingestor for source %s (user=%s, channels=%s)",
                    sid, source.user_id, channel_ids,
                )
            except Exception:
                logger.exception("Failed to start ingestor for source %s", sid)
                await self._update_source_status(sid, "ERROR")
                self._record_failure(sid)

        return {
            "started": list(to_start),
            "stopped": list(to_stop),
            "active": len(self._active_workers),
            "dead_cleaned": dead_sources,
        }

    async def _run_ingestor(
        self, token: str, channel_ids: list[int],
        user_id: str, auth_type: str, data_source_id: str,
    ):
        from services.discord_ingestor.src.connector import DiscordIngestor

        ingestor = DiscordIngestor(
            token=token,
            target_channels=channel_ids,
            user_id=user_id,
            auth_type=auth_type,
            producer=self._producer,
            data_source_id=data_source_id,
        )
        try:
            await self._update_source_status(data_source_id, "CONNECTED")
            self._clear_backoff(data_source_id)
            await ingestor.start()
        except asyncio.CancelledError:
            await ingestor.stop()
            raise
        except Exception:
            logger.exception("Ingestor for source %s crashed", data_source_id)
            await self._update_source_status(data_source_id, "ERROR")
            self._record_failure(data_source_id)
            raise

    async def run(self, poll_interval: float = 30.0):
        while self._running:
            try:
                result = await self.reconcile()
                if result["started"] or result["stopped"] or result["dead_cleaned"]:
                    logger.info("Reconciliation: %s", result)
            except Exception:
                logger.exception("Reconciliation failed")
            await asyncio.sleep(poll_interval)
