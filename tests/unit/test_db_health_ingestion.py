"""Unit tests for check_ingestion in db_health module."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx


class TestCheckIngestion:
    def test_healthy_service(self):
        from apps.api.src.services.db_health import check_ingestion
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.get", return_value=mock_resp):
            ok, detail = check_ingestion()

        assert ok is True
        assert "healthy" in detail["detail"]

    def test_unhealthy_status_code(self):
        from apps.api.src.services.db_health import check_ingestion
        mock_resp = MagicMock()
        mock_resp.status_code = 503

        with patch("httpx.get", return_value=mock_resp):
            ok, detail = check_ingestion()

        assert ok is False
        assert "503" in detail["detail"]

    def test_unreachable_service(self):
        from apps.api.src.services.db_health import check_ingestion

        with patch("httpx.get", side_effect=httpx.ConnectError("connection refused")):
            ok, detail = check_ingestion()

        assert ok is False
        assert "unreachable" in detail["detail"]

    def test_uses_env_var_url(self):
        from apps.api.src.services.db_health import check_ingestion
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch.dict("os.environ", {"DISCORD_INGESTION_URL": "http://custom:9999"}):
            with patch("httpx.get", return_value=mock_resp) as mock_get:
                ok, detail = check_ingestion()

        mock_get.assert_called_once_with("http://custom:9999/health", timeout=5.0)
        assert ok is True
