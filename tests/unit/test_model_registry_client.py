"""Unit tests for shared.model_registry.client — ModelRegistryClient."""

from __future__ import annotations

import io
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.model_registry.client import BUCKET, REQUIRED_BUNDLE_FILES, ModelRegistryClient


@pytest.fixture()
def mock_minio():
    with patch("shared.model_registry.client.Minio") as mock_cls:
        instance = MagicMock()
        instance.bucket_exists.return_value = True
        mock_cls.return_value = instance
        yield instance


@pytest.fixture()
def mock_db():
    return AsyncMock()


@pytest.fixture()
def client(mock_minio, mock_db):
    with patch.dict("os.environ", {
        "MINIO_ENDPOINT": "localhost:9000",
        "MINIO_ACCESS_KEY": "test",
        "MINIO_SECRET_KEY": "test",
    }):
        return ModelRegistryClient(db_session=mock_db)


class TestEnsureBucket:
    def test_creates_bucket_when_missing(self, mock_db):
        with patch("shared.model_registry.client.Minio") as mock_cls:
            instance = MagicMock()
            instance.bucket_exists.return_value = False
            mock_cls.return_value = instance

            with patch.dict("os.environ", {
                "MINIO_ENDPOINT": "localhost:9000",
                "MINIO_ACCESS_KEY": "test",
                "MINIO_SECRET_KEY": "test",
            }):
                ModelRegistryClient(db_session=mock_db)

            instance.make_bucket.assert_called_once_with(BUCKET)

    def test_skips_create_when_exists(self, mock_minio, mock_db):
        mock_minio.bucket_exists.return_value = True
        with patch.dict("os.environ", {
            "MINIO_ENDPOINT": "localhost:9000",
            "MINIO_ACCESS_KEY": "test",
            "MINIO_SECRET_KEY": "test",
        }):
            ModelRegistryClient(db_session=mock_db)
        mock_minio.make_bucket.assert_not_called()


class TestUploadBundle:
    def test_upload_returns_minio_path(self, client, mock_minio, tmp_path):
        bundle = tmp_path / "bundle.tar.gz"
        bundle.write_bytes(b"fake tar content")

        result = client.upload_bundle("agent-123", 1, bundle)

        assert result == "models/agent-123/v1/bundle.tar.gz"
        mock_minio.put_object.assert_called_once()
        call_args = mock_minio.put_object.call_args
        assert call_args[0][0] == BUCKET
        assert call_args[0][1] == "models/agent-123/v1/bundle.tar.gz"

    def test_upload_raises_on_missing_file(self, client):
        with pytest.raises(FileNotFoundError):
            client.upload_bundle("agent-123", 1, Path("/nonexistent/bundle.tar.gz"))


class TestDownloadBundle:
    def test_download_extracts_to_models_dir(self, client, mock_minio, tmp_path):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b'{"model": "xgboost"}'
            info = tarfile.TarInfo(name="best_model.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        buf.seek(0)

        response = MagicMock()
        response.read.return_value = buf.getvalue()
        mock_minio.get_object.return_value = response

        result = client.download_bundle("models/agent-123/v1/bundle.tar.gz", tmp_path)

        assert result == tmp_path / "models"
        assert (result / "best_model.json").exists()


class TestGetLatestBundle:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_bundles(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await client.get_latest_bundle("00000000-0000-0000-0000-000000000001")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_bundle_dict(self, client, mock_db):
        bundle = MagicMock()
        bundle.id = uuid.uuid4()
        bundle.agent_id = uuid.uuid4()
        bundle.version = 3
        bundle.minio_path = "models/agent/v3/bundle.tar.gz"
        bundle.primary_model = "xgboost"
        bundle.accuracy = 0.85
        bundle.auc_roc = 0.90
        bundle.sharpe_ratio = 1.5
        bundle.training_trades = 500
        bundle.feature_count = 120
        bundle.feature_schema = {"technical": ["sma_20"]}
        bundle.status = "approved"
        bundle.validation_passed = True
        bundle.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bundle.deployed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = bundle
        mock_db.execute.return_value = mock_result

        result = await client.get_latest_bundle(str(bundle.agent_id))
        assert result is not None
        assert result["version"] == 3
        assert result["status"] == "approved"
        assert result["accuracy"] == 0.85


class TestRegisterBundle:
    @pytest.mark.asyncio
    async def test_creates_bundle_row(self, client, mock_db):
        mock_db.flush = AsyncMock()
        metrics = {
            "primary_model": "xgboost",
            "accuracy": 0.85,
            "feature_count": 100,
        }

        agent_id = "00000000-0000-0000-0000-000000000001"
        await client.register_bundle(agent_id, 1, "models/a/v1/bundle.tar.gz", metrics)

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert added.version == 1
        assert added.primary_model == "xgboost"
        assert added.status == "pending"


class TestValidateBundle:
    def test_valid_bundle(self, tmp_path):
        for f in REQUIRED_BUNDLE_FILES:
            (tmp_path / f).write_text("data")

        result = ModelRegistryClient.validate_bundle(tmp_path)
        assert result["valid"] is True
        assert result["missing"] == []

    def test_missing_files(self, tmp_path):
        (tmp_path / "best_model.json").write_text("{}")

        result = ModelRegistryClient.validate_bundle(tmp_path)
        assert result["valid"] is False
        assert "meta.json" in result["missing"]
        assert "imputer.pkl" in result["missing"]
        assert "scaler.pkl" in result["missing"]

    def test_empty_dir(self, tmp_path):
        result = ModelRegistryClient.validate_bundle(tmp_path)
        assert result["valid"] is False
        assert len(result["missing"]) == len(REQUIRED_BUNDLE_FILES)
