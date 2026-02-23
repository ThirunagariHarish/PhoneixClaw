import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from shared.crypto.credentials import decrypt_credentials
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.models.database import AsyncSessionLocal
from shared.models.trade import DataSource, TradePipeline

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 600
BASE_BACKOFF_SECONDS = 10


class SourceOrchestrator:
    def __init__(self):
        self._active_workers: dict[str, dict] = {}
        self._running = False
        self._producer = KafkaProducerWrapper()
        self._backoff: dict[str, tuple[int, float]] = {}
        self._last_reconcile_result: dict | None = None

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

    async def _update_pipeline_status(
        self, pipeline_id: str, status: str, error_msg: str | None = None
    ):
        try:
            async with AsyncSessionLocal() as session:
                import uuid as _uuid
                db_pipeline = await session.get(TradePipeline, _uuid.UUID(pipeline_id))
                if db_pipeline:
                    db_pipeline.status = status
                    if error_msg:
                        db_pipeline.error_message = error_msg
                    db_pipeline.updated_at = datetime.now(timezone.utc)
                    await session.commit()
        except Exception:
            logger.exception("Failed to update pipeline status for %s", pipeline_id)

    async def reconcile(self):
        dead_sources = self._cleanup_dead_tasks()
        for sid in dead_sources:
            if sid.startswith("pipe:"):
                asyncio.create_task(self._update_pipeline_status(sid[5:], "ERROR"))
            else:
                asyncio.create_task(self._update_source_status(sid, "ERROR"))
            self._record_failure(sid)

        desired: dict[str, dict] = {}

        async with AsyncSessionLocal() as session:
            pipe_result = await session.execute(
                select(TradePipeline)
                .where(TradePipeline.enabled.is_(True))
                .options(selectinload(TradePipeline.data_source), selectinload(TradePipeline.channel))
            )
            pipelines = pipe_result.scalars().all()
            for p in pipelines:
                if not p.data_source or p.data_source.source_type != "discord":
                    continue
                worker_key = f"pipe:{p.id}"
                desired[worker_key] = {
                    "type": "pipeline",
                    "pipeline": p,
                    "source": p.data_source,
                    "channel": p.channel,
                }

            ds_result = await session.execute(
                select(DataSource).where(DataSource.enabled.is_(True))
            )
            sources = ds_result.scalars().all()
            for s in sources:
                if s.source_type != "discord":
                    continue
                sid = str(s.id)
                pipeline_covers = any(
                    d["source"] and str(d["source"].id) == sid
                    for d in desired.values()
                )
                if not pipeline_covers:
                    desired[sid] = {"type": "legacy", "source": s}

        active = set(self._active_workers.keys())
        desired_keys = set(desired.keys())

        to_start = desired_keys - active
        to_stop = active - desired_keys

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
            logger.info("Stopped worker %s", sid)

        for wkey in to_start:
            if self._is_in_backoff(wkey):
                continue

            info = desired[wkey]
            source = info["source"]
            try:
                creds = decrypt_credentials(source.credentials_encrypted)
                token = creds.get("user_token") or creds.get("bot_token", "")

                if info["type"] == "pipeline":
                    pipeline = info["pipeline"]
                    channel = info["channel"]
                    ch_id = int(channel.channel_identifier.strip())
                    channel_ids = [ch_id]
                    data_source_id = str(source.id)
                    pipeline_id = str(pipeline.id)

                    await self._update_pipeline_status(pipeline_id, "CONNECTING")

                    task = asyncio.create_task(
                        self._run_ingestor(
                            token=token,
                            channel_ids=channel_ids,
                            user_id=str(source.user_id),
                            auth_type=source.auth_type,
                            data_source_id=data_source_id,
                            pipeline_id=pipeline_id,
                        )
                    )
                    self._active_workers[wkey] = {"task": task, "status": "connecting", "pipeline_id": pipeline_id}
                    logger.info(
                        "Started pipeline %s: source=%s channel=%s",
                        pipeline_id, data_source_id, ch_id,
                    )
                else:
                    channel_ids = self._parse_channel_ids(creds.get("channel_ids", ""))
                    await self._update_source_status(wkey, "CONNECTING")
                    task = asyncio.create_task(
                        self._run_ingestor(
                            token=token,
                            channel_ids=channel_ids,
                            user_id=str(source.user_id),
                            auth_type=source.auth_type,
                            data_source_id=wkey,
                        )
                    )
                    self._active_workers[wkey] = {"task": task, "status": "connecting"}
                    logger.info(
                        "Started legacy ingestor for source %s (channels=%s)",
                        wkey, channel_ids,
                    )
            except Exception:
                logger.exception("Failed to start worker %s", wkey)
                if info["type"] == "pipeline":
                    await self._update_pipeline_status(str(info["pipeline"].id), "ERROR")
                else:
                    await self._update_source_status(wkey, "ERROR")
                self._record_failure(wkey)

        self._last_reconcile_result = {
            "started": list(to_start),
            "stopped": list(to_stop),
            "active": len(self._active_workers),
            "dead_cleaned": dead_sources,
        }
        return self._last_reconcile_result

    async def _run_ingestor(
        self, token: str, channel_ids: list[int],
        user_id: str, auth_type: str, data_source_id: str,
        pipeline_id: str | None = None,
    ):
        from services.discord_ingestor.src.connector import DiscordIngestor

        worker_key = f"pipe:{pipeline_id}" if pipeline_id else data_source_id

        async def _mark_connected():
            if pipeline_id:
                await self._update_pipeline_status(pipeline_id, "CONNECTED")
            await self._update_source_status(data_source_id, "CONNECTED")
            self._clear_backoff(worker_key)
            if worker_key in self._active_workers:
                self._active_workers[worker_key]["status"] = "connected"
            logger.info("Worker %s is now CONNECTED", worker_key)

        ingestor = DiscordIngestor(
            token=token,
            target_channels=channel_ids,
            user_id=user_id,
            auth_type=auth_type,
            producer=self._producer,
            data_source_id=data_source_id,
            on_connected=_mark_connected,
        )
        try:
            await ingestor.start()
        except asyncio.CancelledError:
            await ingestor.stop()
            raise
        except Exception:
            logger.exception("Worker %s crashed", worker_key)
            if pipeline_id:
                await self._update_pipeline_status(pipeline_id, "ERROR")
            await self._update_source_status(data_source_id, "ERROR")
            self._record_failure(worker_key)
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
