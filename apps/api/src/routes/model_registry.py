"""Model Registry API routes — manage versioned model bundles.

Endpoints for listing, registering, and managing model bundles stored in
MinIO with metadata tracked in the model_bundles table.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from apps.api.src.deps import DbSession
from shared.db.models.feature_store import ModelBundle

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/model-bundles", tags=["model-registry"])


class RegisterBundleRequest(BaseModel):
    version: int = Field(..., ge=1)
    minio_path: str = Field(..., min_length=1)
    metrics: dict[str, Any] = Field(default_factory=dict)


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(approved|retired)$")


@router.get("/{agent_id}")
async def list_bundles(agent_id: uuid.UUID, session: DbSession) -> list[dict[str, Any]]:
    """List all model bundles for an agent, newest version first."""
    result = await session.execute(
        select(ModelBundle)
        .where(ModelBundle.agent_id == agent_id)
        .order_by(ModelBundle.version.desc())
    )
    return [_to_dict(b) for b in result.scalars().all()]


@router.get("/{agent_id}/latest")
async def get_latest_bundle(agent_id: uuid.UUID, session: DbSession) -> dict[str, Any]:
    """Get the latest approved bundle for an agent."""
    result = await session.execute(
        select(ModelBundle)
        .where(ModelBundle.agent_id == agent_id, ModelBundle.status == "approved")
        .order_by(ModelBundle.version.desc())
        .limit(1)
    )
    bundle = result.scalar_one_or_none()
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No approved bundle found for agent {agent_id}",
        )
    return _to_dict(bundle)


@router.post("/{agent_id}", status_code=status.HTTP_201_CREATED)
async def register_bundle(
    agent_id: uuid.UUID,
    payload: RegisterBundleRequest,
    session: DbSession,
) -> dict[str, Any]:
    """Register a new model bundle (called by the backtesting pipeline)."""
    existing = await session.execute(
        select(ModelBundle).where(
            ModelBundle.agent_id == agent_id,
            ModelBundle.version == payload.version,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Bundle v{payload.version} already exists for agent {agent_id}",
        )

    metrics = payload.metrics
    bundle = ModelBundle(
        agent_id=agent_id,
        version=payload.version,
        minio_path=payload.minio_path,
        primary_model=metrics.get("primary_model"),
        accuracy=metrics.get("accuracy"),
        auc_roc=metrics.get("auc_roc"),
        sharpe_ratio=metrics.get("sharpe_ratio"),
        training_trades=metrics.get("training_trades"),
        feature_count=metrics.get("feature_count"),
        feature_schema=metrics.get("feature_schema"),
        status="pending",
    )
    session.add(bundle)
    await session.flush()

    logger.info("Registered bundle v%d for agent %s (id=%s)", payload.version, agent_id, bundle.id)
    return _to_dict(bundle)


@router.patch("/{bundle_id}/status")
async def update_bundle_status(
    bundle_id: uuid.UUID,
    payload: UpdateStatusRequest,
    session: DbSession,
) -> dict[str, Any]:
    """Approve or retire a model bundle."""
    from datetime import datetime, timezone

    values: dict[str, Any] = {"status": payload.status}
    if payload.status == "approved":
        values["deployed_at"] = datetime.now(timezone.utc)

    result = await session.execute(
        update(ModelBundle).where(ModelBundle.id == bundle_id).values(**values).returning(ModelBundle)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bundle {bundle_id} not found",
        )

    logger.info("Updated bundle %s status to %s", bundle_id, payload.status)
    return _to_dict(row)


def _to_dict(b: ModelBundle) -> dict[str, Any]:
    return {
        "id": str(b.id),
        "agent_id": str(b.agent_id),
        "version": b.version,
        "minio_path": b.minio_path,
        "primary_model": b.primary_model,
        "accuracy": b.accuracy,
        "auc_roc": b.auc_roc,
        "sharpe_ratio": b.sharpe_ratio,
        "training_trades": b.training_trades,
        "feature_count": b.feature_count,
        "feature_schema": b.feature_schema,
        "status": b.status,
        "validation_passed": b.validation_passed,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "deployed_at": b.deployed_at.isoformat() if b.deployed_at else None,
    }
