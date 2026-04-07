"""Centralized health checks for the API.

Each function returns a (healthy: bool, detail: dict) tuple. Used by /health
endpoint and the scheduler to detect degraded subsystems.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


async def check_db(timeout: float = 3.0) -> tuple[bool, dict[str, Any]]:
    """Run SELECT 1 against the database. Returns (healthy, {latency_ms, ...})."""
    t0 = time.monotonic()
    try:
        from shared.db.engine import get_engine_singleton
        from sqlalchemy import text

        engine = get_engine_singleton()
        async with asyncio.timeout(timeout):
            async with engine.begin() as conn:
                result = await conn.execute(text("SELECT 1 AS ok"))
                row = result.first()
                if not row or row[0] != 1:
                    return False, {"error": "unexpected result"}

        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return True, {"latency_ms": latency_ms}
    except asyncio.TimeoutError:
        return False, {"error": f"timeout after {timeout}s"}
    except Exception as exc:
        return False, {"error": str(exc)[:200]}


async def check_redis(timeout: float = 2.0) -> tuple[bool, dict[str, Any]]:
    """Ping Redis."""
    t0 = time.monotonic()
    try:
        import redis.asyncio as aioredis

        url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        redis = aioredis.from_url(url, decode_responses=True)
        try:
            async with asyncio.timeout(timeout):
                pong = await redis.ping()
        finally:
            await redis.aclose()

        if not pong:
            return False, {"error": "no pong"}

        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return True, {"latency_ms": latency_ms, "url": url.split("@")[-1]}
    except asyncio.TimeoutError:
        return False, {"error": f"timeout after {timeout}s"}
    except ImportError:
        return False, {"error": "redis-py not installed"}
    except Exception as exc:
        return False, {"error": str(exc)[:200]}


def check_scheduler() -> tuple[bool, dict[str, Any]]:
    """Check if APScheduler is running and has jobs."""
    try:
        from apps.api.src.services.scheduler import get_scheduler_status
        status = get_scheduler_status()
        if not status.get("running"):
            return False, {"reason": status.get("reason") or status.get("error", "not running")}
        return True, {"jobs": len(status.get("jobs", []))}
    except Exception as exc:
        return False, {"error": str(exc)[:200]}


def check_ingestion() -> tuple[bool, dict[str, Any]]:
    """Check if message ingestion daemon is running."""
    try:
        from apps.api.src.services.message_ingestion import get_ingestion_status
        status = get_ingestion_status()
        if not status.get("running"):
            return False, {"connectors": 0}
        connectors = status.get("connectors", [])
        alive = sum(1 for c in connectors if c.get("alive"))
        return True, {"total": len(connectors), "alive": alive}
    except Exception as exc:
        return False, {"error": str(exc)[:200]}


async def check_disk_usage(path: str = "/app/data", warn_threshold: float = 0.85,
                            timeout: float = 1.0) -> tuple[bool, dict[str, Any]]:
    """Return whether disk usage is below the warning threshold."""
    try:
        import shutil
        if not os.path.exists(path):
            # Local dev: use a sensible default
            path = os.path.expanduser("~")
        async with asyncio.timeout(timeout):
            usage = await asyncio.to_thread(shutil.disk_usage, path)
        used_pct = usage.used / usage.total
        healthy = used_pct < warn_threshold
        return healthy, {
            "path": path,
            "used_pct": round(used_pct * 100, 1),
            "free_gb": round(usage.free / (1024 ** 3), 1),
            "total_gb": round(usage.total / (1024 ** 3), 1),
        }
    except asyncio.TimeoutError:
        return True, {"error": "timeout"}  # Don't fail health on slow disk check
    except Exception as exc:
        return True, {"error": str(exc)[:200]}


async def aggregate_health() -> dict[str, Any]:
    """Run all health checks in parallel and return a combined report."""
    db_task = asyncio.create_task(check_db())
    redis_task = asyncio.create_task(check_redis())
    disk_task = asyncio.create_task(check_disk_usage())

    db_ok, db_detail = await db_task
    redis_ok, redis_detail = await redis_task
    disk_ok, disk_detail = await disk_task
    sched_ok, sched_detail = check_scheduler()
    ingest_ok, ingest_detail = check_ingestion()

    overall = db_ok and redis_ok and sched_ok
    return {
        "status": "ready" if overall else "degraded",
        "checks": {
            "database": {"healthy": db_ok, **db_detail},
            "redis": {"healthy": redis_ok, **redis_detail},
            "scheduler": {"healthy": sched_ok, **sched_detail},
            "ingestion": {"healthy": ingest_ok, **ingest_detail},
            "disk": {"healthy": disk_ok, **disk_detail},
        },
    }
