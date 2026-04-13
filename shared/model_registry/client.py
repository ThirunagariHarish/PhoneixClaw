"""Model Registry client — upload, download, and track model bundles in MinIO.

Wraps the ``minio`` Python SDK and the ``model_bundles`` PostgreSQL table
to provide a single interface for the backtesting pipeline and live agents.
"""

from __future__ import annotations

import io
import logging
import os
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from minio import Minio
from minio.error import S3Error
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.feature_store import ModelBundle

log = logging.getLogger(__name__)

BUCKET = "phoenix-models"
REQUIRED_BUNDLE_FILES = {"best_model.json", "meta.json", "imputer.pkl", "scaler.pkl"}


class ModelRegistryClient:
    """Manages model bundle lifecycle: upload to MinIO, register in DB, download for inference."""

    def __init__(
        self,
        db_session: AsyncSession,
        minio_endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ):
        self._db = db_session
        endpoint = minio_endpoint or os.getenv("MINIO_ENDPOINT", "localhost:9000")
        ak = access_key or os.getenv("MINIO_ACCESS_KEY") or os.getenv("MINIO_ROOT_USER", "minioadmin")
        sk = secret_key or os.getenv("MINIO_SECRET_KEY") or os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")

        secure = endpoint.startswith("https")
        clean_endpoint = endpoint.replace("https://", "").replace("http://", "")

        self._minio = Minio(clean_endpoint, access_key=ak, secret_key=sk, secure=secure)
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            if not self._minio.bucket_exists(BUCKET):
                self._minio.make_bucket(BUCKET)
                log.info("Created MinIO bucket: %s", BUCKET)
        except S3Error as exc:
            log.error("Failed to ensure MinIO bucket %s: %s", BUCKET, exc)
            raise

    def upload_bundle(self, agent_id: str, version: int, bundle_path: Path) -> str:
        """Upload a tar.gz bundle to MinIO. Returns the minio_path key."""
        minio_path = f"models/{agent_id}/v{version}/bundle.tar.gz"

        if not bundle_path.exists():
            raise FileNotFoundError(f"Bundle not found: {bundle_path}")

        file_size = bundle_path.stat().st_size
        with bundle_path.open("rb") as fobj:
            self._minio.put_object(
                BUCKET,
                minio_path,
                fobj,
                length=file_size,
                content_type="application/gzip",
            )

        log.info("Uploaded bundle to %s/%s (%d bytes)", BUCKET, minio_path, file_size)
        return minio_path

    def download_bundle(self, minio_path: str, dest_dir: Path) -> Path:
        """Download a bundle tar.gz from MinIO and extract to dest_dir/models/."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        models_dir = dest_dir / "models"
        models_dir.mkdir(parents=True, exist_ok=True)

        response = self._minio.get_object(BUCKET, minio_path)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()

        tar_buffer = io.BytesIO(data)
        with tarfile.open(fileobj=tar_buffer, mode="r:gz") as tar:
            tar.extractall(path=models_dir, filter="data")

        log.info("Extracted bundle %s to %s", minio_path, models_dir)
        return models_dir

    async def get_latest_bundle(self, agent_id: str) -> dict[str, Any] | None:
        """Query model_bundles for the latest approved bundle for an agent."""
        result = await self._db.execute(
            select(ModelBundle)
            .where(ModelBundle.agent_id == uuid.UUID(agent_id), ModelBundle.status == "approved")
            .order_by(ModelBundle.version.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return _bundle_to_dict(row)

    async def register_bundle(
        self,
        agent_id: str,
        version: int,
        minio_path: str,
        metrics: dict[str, Any],
    ) -> uuid.UUID:
        """Insert a new model_bundle row and return its ID."""
        bundle = ModelBundle(
            agent_id=uuid.UUID(agent_id),
            version=version,
            minio_path=minio_path,
            primary_model=metrics.get("primary_model"),
            accuracy=metrics.get("accuracy"),
            auc_roc=metrics.get("auc_roc"),
            sharpe_ratio=metrics.get("sharpe_ratio"),
            training_trades=metrics.get("training_trades"),
            feature_count=metrics.get("feature_count"),
            feature_schema=metrics.get("feature_schema"),
            status="pending",
        )
        self._db.add(bundle)
        await self._db.flush()
        log.info("Registered model bundle %s for agent %s v%d", bundle.id, agent_id, version)
        return bundle.id

    async def update_bundle_status(self, bundle_id: str, new_status: str) -> bool:
        """Transition a bundle's status (pending → approved/retired)."""
        valid_statuses = {"pending", "approved", "retired"}
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid status '{new_status}'. Must be one of {valid_statuses}")

        values: dict[str, Any] = {"status": new_status}
        if new_status == "approved":
            values["deployed_at"] = datetime.now(timezone.utc)

        result = await self._db.execute(
            update(ModelBundle).where(ModelBundle.id == uuid.UUID(bundle_id)).values(**values)
        )
        await self._db.flush()
        return result.rowcount > 0

    async def list_bundles(self, agent_id: str) -> list[dict[str, Any]]:
        """List all bundles for an agent, newest first."""
        result = await self._db.execute(
            select(ModelBundle)
            .where(ModelBundle.agent_id == uuid.UUID(agent_id))
            .order_by(ModelBundle.version.desc())
        )
        return [_bundle_to_dict(row) for row in result.scalars().all()]

    @staticmethod
    def validate_bundle(bundle_dir: Path) -> dict[str, Any]:
        """Check that required model files exist in a bundle directory."""
        present: set[str] = set()
        missing: set[str] = set()
        for fname in REQUIRED_BUNDLE_FILES:
            if (bundle_dir / fname).exists():
                present.add(fname)
            else:
                missing.add(fname)

        return {
            "valid": len(missing) == 0,
            "present": sorted(present),
            "missing": sorted(missing),
        }


def _bundle_to_dict(b: ModelBundle) -> dict[str, Any]:
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
