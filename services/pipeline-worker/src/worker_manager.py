"""Worker Manager — manages N concurrent agent async tasks."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import select, update

from services.pipeline_worker.src.agent_worker import AgentWorker
from services.pipeline_worker.src.config import settings
from shared.db.models.agent import Agent, PipelineWorkerState
from shared.db.models.agent_session import AgentSession

logger = logging.getLogger(__name__)


class WorkerManager:
    """Manages lifecycle of per-agent pipeline worker tasks."""

    def __init__(self, redis_client: aioredis.Redis, session_factory: Any) -> None:
        self._redis = redis_client
        self._session_factory = session_factory
        self._workers: dict[str, asyncio.Task] = {}
        self._worker_instances: dict[str, AgentWorker] = {}

    @property
    def active_count(self) -> int:
        return len(self._workers)

    async def start_worker(
        self,
        agent_id: str,
        connector_ids: list[str],
        config: dict,
    ) -> dict:
        """Create an AgentWorker, wrap in asyncio.Task, record session in DB."""
        if agent_id in self._workers:
            return {"agent_id": agent_id, "status": "already_running"}

        if len(self._workers) >= settings.MAX_WORKERS:
            raise RuntimeError(f"Max workers ({settings.MAX_WORKERS}) reached")

        worker = AgentWorker(
            agent_id=agent_id,
            connector_ids=connector_ids,
            config=config,
            redis_client=self._redis,
            session_factory=self._session_factory,
        )

        task = asyncio.create_task(
            self._run_with_error_handling(agent_id, worker),
            name=f"pipeline-worker-{agent_id}",
        )

        self._workers[agent_id] = task
        self._worker_instances[agent_id] = worker

        # Record in DB
        await self._record_session_start(agent_id, connector_ids, config)

        stream_keys = [f"stream:channel:{cid}" for cid in connector_ids]
        return {
            "agent_id": agent_id,
            "worker_id": str(uuid.uuid4()),
            "status": "starting",
            "stream_keys": stream_keys,
        }

    async def stop_worker(self, agent_id: str) -> bool:
        """Cancel a worker task gracefully and update DB."""
        task = self._workers.get(agent_id)
        if not task:
            return False

        instance = self._worker_instances.get(agent_id)
        if instance:
            instance.stop()

        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=10.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

        self._workers.pop(agent_id, None)
        self._worker_instances.pop(agent_id, None)

        await self._update_agent_status(agent_id, "STOPPED")
        return True

    def get_worker(self, agent_id: str) -> dict | None:
        """Return stats for a single worker."""
        instance = self._worker_instances.get(agent_id)
        if not instance:
            return None
        return instance.stats

    def list_workers(self) -> list[dict]:
        """Return stats for all active workers."""
        return [inst.stats for inst in self._worker_instances.values()]

    async def recover_workers(self) -> int:
        """On startup, resume workers for agents with engine_type=pipeline and worker_status=RUNNING."""
        recovered = 0
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    select(Agent).where(
                        Agent.engine_type == "pipeline",
                        Agent.worker_status == "RUNNING",
                    )
                )
                agents = result.scalars().all()

                for agent in agents:
                    connector_ids = agent.config.get("connector_ids", [])
                    if not connector_ids:
                        logger.warning(
                            "Skipping recovery for agent %s — no connector_ids in config",
                            agent.id,
                        )
                        continue
                    try:
                        await self.start_worker(
                            str(agent.id), connector_ids, agent.config,
                        )
                        recovered += 1
                        logger.info("Recovered pipeline worker for agent %s", agent.id)
                    except Exception as exc:
                        logger.error("Failed to recover worker for %s: %s", agent.id, exc)
                        await self._update_agent_status(str(agent.id), "ERROR", str(exc))
        except Exception as exc:
            logger.error("Worker recovery failed: %s", exc)

        logger.info("Recovered %d pipeline workers", recovered)
        return recovered

    async def shutdown(self) -> None:
        """Stop all workers gracefully on service shutdown."""
        agent_ids = list(self._workers.keys())
        logger.info("Shutting down %d pipeline workers", len(agent_ids))
        for agent_id in agent_ids:
            try:
                await self.stop_worker(agent_id)
            except Exception as exc:
                logger.error("Error stopping worker %s during shutdown: %s", agent_id, exc)

    async def _run_with_error_handling(self, agent_id: str, worker: AgentWorker) -> None:
        """Wrapper that catches unhandled exceptions from a worker task."""
        try:
            await worker.run()
        except asyncio.CancelledError:
            logger.info("Worker %s cancelled", agent_id)
        except Exception as exc:
            logger.error("Worker %s crashed: %s", agent_id, exc, exc_info=True)
            await self._update_agent_status(agent_id, "ERROR", str(exc)[:500])
        finally:
            self._workers.pop(agent_id, None)
            self._worker_instances.pop(agent_id, None)

    async def _record_session_start(
        self,
        agent_id: str,
        connector_ids: list[str],
        config: dict,
    ) -> None:
        """Insert/update AgentSession and PipelineWorkerState + set agent worker_status."""
        try:
            async with self._session_factory() as session:
                # Update agent status
                await session.execute(
                    update(Agent)
                    .where(Agent.id == agent_id)
                    .values(
                        worker_status="RUNNING",
                        runtime_status="active",
                        last_activity_at=datetime.now(timezone.utc),
                        error_message=None,
                    )
                )

                # Create session record
                agent_session = AgentSession(
                    agent_id=agent_id,
                    agent_type="pipeline_worker",
                    status="running",
                    trading_mode=config.get("trading_mode", "live"),
                    config=config,
                )
                session.add(agent_session)

                # Upsert PipelineWorkerState
                stream_key = f"stream:channel:{connector_ids[0]}" if connector_ids else ""
                existing = await session.execute(
                    select(PipelineWorkerState).where(
                        PipelineWorkerState.agent_id == agent_id
                    )
                )
                state = existing.scalar_one_or_none()
                if state:
                    state.stream_key = stream_key
                    state.last_heartbeat = datetime.now(timezone.utc)
                    state.started_at = datetime.now(timezone.utc)
                else:
                    state = PipelineWorkerState(
                        agent_id=agent_id,
                        stream_key=stream_key,
                        started_at=datetime.now(timezone.utc),
                        last_heartbeat=datetime.now(timezone.utc),
                    )
                    session.add(state)

                await session.commit()
        except Exception as exc:
            logger.error("Failed to record session start for %s: %s", agent_id, exc)

    async def _update_agent_status(
        self,
        agent_id: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update Agent.worker_status and optionally error_message."""
        try:
            async with self._session_factory() as session:
                values: dict = {
                    "worker_status": status,
                    "runtime_status": "stopped" if status in ("STOPPED", "ERROR") else "active",
                }
                if error_message is not None:
                    values["error_message"] = error_message
                await session.execute(
                    update(Agent).where(Agent.id == agent_id).values(**values)
                )
                await session.commit()
        except Exception as exc:
            logger.error("Failed to update status for %s: %s", agent_id, exc)
