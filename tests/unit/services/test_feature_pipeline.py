"""Unit tests for the Feature Pipeline service — GET /features/{ticker} freshness."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def _patch_infra(monkeypatch):
    """Replace heavy infra (PG engine, Redis, background tasks) with lightweight fakes."""
    import services.feature_pipeline.src.main as mod

    mock_engine = MagicMock()
    monkeypatch.setattr(mod, "_engine", mock_engine)
    monkeypatch.setattr(mod, "_redis", None)
    monkeypatch.setattr(mod, "_bg_tasks", [])


@pytest.fixture
def client(_patch_infra):
    from starlette.testclient import TestClient

    from services.feature_pipeline.src.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestGetFeaturesFreshField:
    """Verify that GET /features/{ticker} returns a ``fresh`` boolean."""

    def test_fresh_when_computed_recently(self, monkeypatch):
        """Features computed < 5 min ago → fresh=True."""
        import services.feature_pipeline.src.main as mod

        now = datetime.now(timezone.utc)
        recent_ts = now - timedelta(minutes=2)
        fake_features = {"rsi_14": 55.0, "sma_20": 150.0}

        mock_fs = MagicMock()
        mock_fs.read_feature_view = AsyncMock(return_value=fake_features)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (recent_ts,)

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)
        monkeypatch.setattr(mod, "_session_factory", mock_factory)
        monkeypatch.setattr(mod, "_redis", None)

        with patch("services.feature_pipeline.src.main.FeatureStoreClient", return_value=mock_fs):
            from starlette.testclient import TestClient
            with TestClient(mod.app, raise_server_exceptions=False) as client:
                resp = client.get("/features/PLTR")

        assert resp.status_code == 200
        data = resp.json()
        assert data["fresh"] is True
        assert data["ticker"] == "PLTR"
        assert data["feature_count"] == 2
        assert data["features"] == fake_features
        assert data["computed_at"] is not None

    def test_stale_when_computed_long_ago(self, monkeypatch):
        """Features computed > 5 min ago → fresh=False."""
        import services.feature_pipeline.src.main as mod

        now = datetime.now(timezone.utc)
        old_ts = now - timedelta(minutes=10)
        fake_features = {"rsi_14": 60.0}

        mock_fs = MagicMock()
        mock_fs.read_feature_view = AsyncMock(return_value=fake_features)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (old_ts,)

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)
        monkeypatch.setattr(mod, "_session_factory", mock_factory)
        monkeypatch.setattr(mod, "_redis", None)

        with patch("services.feature_pipeline.src.main.FeatureStoreClient", return_value=mock_fs):
            from starlette.testclient import TestClient
            with TestClient(mod.app, raise_server_exceptions=False) as client:
                resp = client.get("/features/AAPL")

        data = resp.json()
        assert data["fresh"] is False

    def test_fresh_false_when_no_rows(self, monkeypatch):
        """No rows in DB for this ticker → fresh=False, computed_at=None."""
        import services.feature_pipeline.src.main as mod

        mock_fs = MagicMock()
        mock_fs.read_feature_view = AsyncMock(return_value={})

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (None,)

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)
        monkeypatch.setattr(mod, "_session_factory", mock_factory)
        monkeypatch.setattr(mod, "_redis", None)

        with patch("services.feature_pipeline.src.main.FeatureStoreClient", return_value=mock_fs):
            from starlette.testclient import TestClient
            with TestClient(mod.app, raise_server_exceptions=False) as client:
                resp = client.get("/features/XYZ")

        data = resp.json()
        assert data["fresh"] is False
        assert data["computed_at"] is None
        assert data["feature_count"] == 0

    def test_naive_timestamp_treated_as_utc(self, monkeypatch):
        """A naive (no tzinfo) computed_at from PG is treated as UTC."""
        import services.feature_pipeline.src.main as mod

        naive_ts = datetime.utcnow() - timedelta(minutes=1)  # noqa: DTZ003
        fake_features = {"macd": 0.5}

        mock_fs = MagicMock()
        mock_fs.read_feature_view = AsyncMock(return_value=fake_features)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (naive_ts,)

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)
        monkeypatch.setattr(mod, "_session_factory", mock_factory)
        monkeypatch.setattr(mod, "_redis", None)

        with patch("services.feature_pipeline.src.main.FeatureStoreClient", return_value=mock_fs):
            from starlette.testclient import TestClient
            with TestClient(mod.app, raise_server_exceptions=False) as client:
                resp = client.get("/features/TSLA")

        data = resp.json()
        assert data["fresh"] is True

    def test_ticker_uppercased(self, monkeypatch):
        """Lowercase ticker in URL is uppercased in response."""
        import services.feature_pipeline.src.main as mod

        now = datetime.now(timezone.utc)
        mock_fs = MagicMock()
        mock_fs.read_feature_view = AsyncMock(return_value={"rsi_14": 50.0})

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (now,)

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)
        monkeypatch.setattr(mod, "_session_factory", mock_factory)
        monkeypatch.setattr(mod, "_redis", None)

        with patch("services.feature_pipeline.src.main.FeatureStoreClient", return_value=mock_fs):
            from starlette.testclient import TestClient
            with TestClient(mod.app, raise_server_exceptions=False) as client:
                resp = client.get("/features/pltr")

        data = resp.json()
        assert data["ticker"] == "PLTR"
