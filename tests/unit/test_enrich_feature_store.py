"""Tests for Feature Store integration in agents/backtesting/tools/enrich.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents" / "backtesting"))

from agents.backtesting.tools.enrich import _read_from_feature_store


class TestReadFromFeatureStore:
    """Tests for _read_from_feature_store helper."""

    def test_returns_none_when_no_database_url(self):
        with patch.dict("os.environ", {}, clear=True):
            result = _read_from_feature_store("AAPL")
        assert result is None

    def test_returns_none_when_database_url_empty(self):
        with patch.dict("os.environ", {"DATABASE_URL": ""}):
            result = _read_from_feature_store("AAPL")
        assert result is None

    def test_returns_features_from_store(self):
        fake_features = {"rsi_14": 55.0, "macd_line": 0.5, "sma_20": 150.0}

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_client_instance = MagicMock()
        mock_client_instance.read_feature_view = AsyncMock(return_value=fake_features)

        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://user:pass@localhost/db", "REDIS_URL": ""}):
            with (
                patch(
                    "sqlalchemy.ext.asyncio.create_async_engine",
                    return_value=mock_engine,
                ),
                patch(
                    "sqlalchemy.ext.asyncio.AsyncSession",
                    return_value=mock_session,
                ),
                patch(
                    "shared.feature_store.client.FeatureStoreClient",
                    return_value=mock_client_instance,
                ),
            ):
                result = _read_from_feature_store("AAPL")

        assert result == fake_features

    def test_returns_none_on_exception(self):
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://localhost/db", "REDIS_URL": ""}):
            with patch(
                "sqlalchemy.ext.asyncio.create_async_engine",
                side_effect=Exception("connection refused"),
            ):
                result = _read_from_feature_store("AAPL")
        assert result is None

    def test_returns_none_when_store_returns_empty(self):
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://localhost/db", "REDIS_URL": ""}):
            mock_engine = MagicMock()
            mock_engine.dispose = AsyncMock()

            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            mock_client_instance = MagicMock()
            mock_client_instance.read_feature_view = AsyncMock(return_value={})

            with (
                patch(
                    "sqlalchemy.ext.asyncio.create_async_engine",
                    return_value=mock_engine,
                ),
                patch(
                    "sqlalchemy.ext.asyncio.AsyncSession",
                    return_value=mock_session,
                ),
                patch(
                    "shared.feature_store.client.FeatureStoreClient",
                    return_value=mock_client_instance,
                ),
            ):
                result = _read_from_feature_store("AAPL")

        assert result is None

    def test_as_of_date_parameter_accepted(self):
        """as_of_date is accepted without error (forward-compat)."""
        with patch.dict("os.environ", {}, clear=True):
            result = _read_from_feature_store("AAPL", as_of_date="2025-01-15")
        assert result is None
