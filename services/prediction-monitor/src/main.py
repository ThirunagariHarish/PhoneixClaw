"""Phoenix Prediction Monitor — accuracy tracking, feature drift, and retrain alerts."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import numpy as np
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.db.models.feature_store import Prediction

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
ACCURACY_THRESHOLD = float(os.environ.get("ACCURACY_THRESHOLD", "0.55"))
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", "300"))

_engine = create_async_engine(DATABASE_URL, pool_size=5, max_overflow=5, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)
_redis: aioredis.Redis | None = None
_bg_tasks: list[asyncio.Task] = []


class OutcomePayload(BaseModel):
    actual_outcome: str = Field(..., pattern=r"^(WIN|LOSS)$")
    actual_pnl: float


class WindowMetrics(BaseModel):
    total: int = 0
    correct: int = 0
    accuracy: float = 0.0
    precision: float = 0.0
    avg_confidence: float = 0.0


class DriftedFeature(BaseModel):
    name: str
    baseline_mean: float
    recent_mean: float
    shift_std: float


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_correct(prediction: str, outcome: str) -> bool:
    return (prediction == "TRADE" and outcome == "WIN") or (prediction == "SKIP" and outcome == "LOSS")


def _compute_window_metrics(predictions: list[Prediction]) -> WindowMetrics:
    if not predictions:
        return WindowMetrics()

    resolved = [p for p in predictions if p.actual_outcome is not None]
    if not resolved:
        return WindowMetrics(total=len(predictions))

    correct = sum(1 for p in resolved if _is_correct(p.prediction, p.actual_outcome))
    trade_preds = [p for p in resolved if p.prediction == "TRADE"]
    trade_correct = sum(1 for p in trade_preds if p.actual_outcome == "WIN")
    precision = trade_correct / len(trade_preds) if trade_preds else 0.0

    confidences = [p.confidence for p in resolved if p.confidence is not None]
    avg_conf = float(np.mean(confidences)) if confidences else 0.0

    return WindowMetrics(
        total=len(resolved),
        correct=correct,
        accuracy=round(correct / len(resolved), 4) if resolved else 0.0,
        precision=round(precision, 4),
        avg_confidence=round(avg_conf, 4),
    )


async def _get_predictions_since(
    session: AsyncSession, agent_id: UUID, since: datetime
) -> list[Prediction]:
    stmt = (
        select(Prediction)
        .where(Prediction.agent_id == agent_id, Prediction.predicted_at >= since)
        .order_by(Prediction.predicted_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _get_all_predictions(session: AsyncSession, agent_id: UUID) -> list[Prediction]:
    stmt = (
        select(Prediction)
        .where(Prediction.agent_id == agent_id)
        .order_by(Prediction.predicted_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _compute_accuracy(session: AsyncSession, agent_id: UUID) -> dict[str, Any]:
    now = _now_utc()
    windows: dict[str, WindowMetrics] = {}

    for label, delta in [("1d", timedelta(days=1)), ("7d", timedelta(days=7)), ("30d", timedelta(days=30))]:
        preds = await _get_predictions_since(session, agent_id, now - delta)
        windows[label] = _compute_window_metrics(preds)

    all_preds = await _get_all_predictions(session, agent_id)
    windows["all_time"] = _compute_window_metrics(all_preds)

    return {"agent_id": str(agent_id), "windows": {k: v.model_dump() for k, v in windows.items()}}


async def _compute_drift(session: AsyncSession, agent_id: UUID) -> dict[str, Any]:
    now = _now_utc()
    recent_preds = await _get_predictions_since(session, agent_id, now - timedelta(days=7))
    baseline_preds = await _get_predictions_since(session, agent_id, now - timedelta(days=30))

    baseline_only = [p for p in baseline_preds if p.predicted_at < now - timedelta(days=7)]

    recent_snapshots = [p.features_snapshot for p in recent_preds if p.features_snapshot]
    baseline_snapshots = [p.features_snapshot for p in baseline_only if p.features_snapshot]

    if not recent_snapshots or not baseline_snapshots:
        return {"agent_id": str(agent_id), "drifted_features": [], "drift_score": 0.0}

    all_keys: set[str] = set()
    for snap in recent_snapshots + baseline_snapshots:
        all_keys.update(k for k, v in snap.items() if isinstance(v, (int, float)))

    drifted: list[dict[str, Any]] = []
    drift_count = 0

    for key in sorted(all_keys):
        recent_vals = [s[key] for s in recent_snapshots if key in s and isinstance(s[key], (int, float))]
        baseline_vals = [s[key] for s in baseline_snapshots if key in s and isinstance(s[key], (int, float))]

        if len(recent_vals) < 2 or len(baseline_vals) < 2:
            continue

        baseline_mean = float(np.mean(baseline_vals))
        baseline_std = float(np.std(baseline_vals))
        recent_mean = float(np.mean(recent_vals))

        if baseline_std == 0:
            continue

        shift_std = abs(recent_mean - baseline_mean) / baseline_std

        if shift_std > 2.0:
            drifted.append({
                "name": key,
                "baseline_mean": round(baseline_mean, 4),
                "recent_mean": round(recent_mean, 4),
                "shift_std": round(shift_std, 4),
            })
            drift_count += 1

    total_features = len(all_keys) if all_keys else 1
    drift_score = round(drift_count / total_features, 4)

    return {"agent_id": str(agent_id), "drifted_features": drifted, "drift_score": drift_score}


async def _get_distinct_agent_ids(session: AsyncSession) -> list[UUID]:
    stmt = select(Prediction.agent_id).distinct()
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def _check_alerts(session: AsyncSession) -> list[dict[str, Any]]:
    agent_ids = await _get_distinct_agent_ids(session)
    alerts: list[dict[str, Any]] = []
    now = _now_utc()

    for agent_id in agent_ids:
        preds_7d = await _get_predictions_since(session, agent_id, now - timedelta(days=7))
        metrics = _compute_window_metrics(preds_7d)
        if metrics.total > 0 and metrics.accuracy < ACCURACY_THRESHOLD:
            alerts.append({
                "agent_id": str(agent_id),
                "alert_type": "needs_retrain",
                "accuracy_7d": metrics.accuracy,
                "total_predictions_7d": metrics.total,
                "threshold": ACCURACY_THRESHOLD,
            })

    return alerts


async def _background_accuracy_check() -> None:
    while True:
        try:
            async with _session_factory() as session:
                alerts = await _check_alerts(session)
                for alert in alerts:
                    log.warning(
                        "Agent %s accuracy degraded: %.2f (threshold %.2f)",
                        alert["agent_id"], alert["accuracy_7d"], alert["threshold"],
                    )
                    if _redis:
                        await _redis.publish(
                            f"retrain_needed:{alert['agent_id']}",
                            f'{{"agent_id": "{alert["agent_id"]}", "accuracy_7d": {alert["accuracy_7d"]}}}',
                        )
        except Exception as exc:
            log.error("Background accuracy check failed: %s", exc)

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis
    try:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        await _redis.ping()
        log.info("Connected to Redis")
    except Exception as exc:
        log.warning("Redis unavailable, running without pub/sub: %s", exc)
        _redis = None

    _bg_tasks.append(asyncio.create_task(_background_accuracy_check()))
    log.info("Prediction monitor background tasks started")

    yield

    for task in _bg_tasks:
        task.cancel()
    _bg_tasks.clear()
    if _redis:
        await _redis.aclose()


app = FastAPI(title="Phoenix Prediction Monitor", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "phoenix-prediction-monitor", "redis_connected": _redis is not None}


@app.get("/accuracy/{agent_id}")
async def get_accuracy(agent_id: UUID):
    async with _session_factory() as session:
        return await _compute_accuracy(session, agent_id)


@app.get("/drift/{agent_id}")
async def get_drift(agent_id: UUID):
    async with _session_factory() as session:
        return await _compute_drift(session, agent_id)


@app.get("/predictions/{agent_id}")
async def get_predictions(
    agent_id: UUID,
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    ticker: Optional[str] = Query(None),
    prediction_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    async with _session_factory() as session:
        stmt = select(Prediction).where(Prediction.agent_id == agent_id)

        if since:
            stmt = stmt.where(Prediction.predicted_at >= since)
        if until:
            stmt = stmt.where(Prediction.predicted_at <= until)
        if ticker:
            stmt = stmt.where(Prediction.ticker == ticker.upper())
        if prediction_type:
            stmt = stmt.where(Prediction.prediction == prediction_type.upper())

        stmt = stmt.order_by(Prediction.predicted_at.desc()).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return [
        {
            "id": row.id,
            "agent_id": str(row.agent_id),
            "model_bundle_id": str(row.model_bundle_id) if row.model_bundle_id else None,
            "ticker": row.ticker,
            "prediction": row.prediction,
            "confidence": row.confidence,
            "reasoning": row.reasoning,
            "predicted_at": row.predicted_at.isoformat() if row.predicted_at else None,
            "actual_outcome": row.actual_outcome,
            "actual_pnl": row.actual_pnl,
            "outcome_at": row.outcome_at.isoformat() if row.outcome_at else None,
        }
        for row in rows
    ]


@app.post("/predictions/{prediction_id}/outcome")
async def record_outcome(prediction_id: int, payload: OutcomePayload):
    async with _session_factory() as session:
        stmt = select(Prediction).where(Prediction.id == prediction_id)
        result = await session.execute(stmt)
        pred = result.scalar_one_or_none()

        if not pred:
            raise HTTPException(status_code=404, detail=f"Prediction {prediction_id} not found")

        await session.execute(
            update(Prediction)
            .where(Prediction.id == prediction_id)
            .values(
                actual_outcome=payload.actual_outcome,
                actual_pnl=payload.actual_pnl,
                outcome_at=_now_utc(),
            )
        )
        await session.commit()

    return {"status": "updated", "prediction_id": prediction_id}


@app.get("/alerts")
async def get_alerts():
    async with _session_factory() as session:
        return {"alerts": await _check_alerts(session)}
