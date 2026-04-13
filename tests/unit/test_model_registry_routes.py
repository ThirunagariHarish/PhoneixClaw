"""Unit tests for apps.api.src.routes.model_registry — API endpoints."""

from __future__ import annotations

import pytest


class TestRegisterBundleRequestValidation:
    def test_valid_request(self):
        from apps.api.src.routes.model_registry import RegisterBundleRequest

        req = RegisterBundleRequest(version=1, minio_path="models/a/v1/bundle.tar.gz")
        assert req.version == 1
        assert req.metrics == {}

    def test_invalid_version(self):
        from apps.api.src.routes.model_registry import RegisterBundleRequest

        with pytest.raises(Exception):
            RegisterBundleRequest(version=0, minio_path="test")

    def test_empty_minio_path(self):
        from apps.api.src.routes.model_registry import RegisterBundleRequest

        with pytest.raises(Exception):
            RegisterBundleRequest(version=1, minio_path="")


class TestUpdateStatusRequestValidation:
    def test_approved(self):
        from apps.api.src.routes.model_registry import UpdateStatusRequest

        req = UpdateStatusRequest(status="approved")
        assert req.status == "approved"

    def test_retired(self):
        from apps.api.src.routes.model_registry import UpdateStatusRequest

        req = UpdateStatusRequest(status="retired")
        assert req.status == "retired"

    def test_invalid_status(self):
        from apps.api.src.routes.model_registry import UpdateStatusRequest

        with pytest.raises(Exception):
            UpdateStatusRequest(status="deleted")
