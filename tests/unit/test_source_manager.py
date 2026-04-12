"""Unit tests for shared.data.source_manager."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from shared.data.source_manager import SourceManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton between tests."""
    import shared.data.source_manager as mod
    mod._manager_instance = None
    yield
    mod._manager_instance = None


@pytest.fixture()
def manager():
    """Return a fresh SourceManager."""
    return SourceManager()


# ---------------------------------------------------------------------------
# Test: fallback chain -- get_news
# ---------------------------------------------------------------------------

class TestGetNews:
    def test_primary_source_succeeds(self, manager):
        mock_finnhub = MagicMock()
        mock_finnhub.get_company_news.return_value = [{"headline": "AAPL up"}]

        with patch.object(manager, "_get_finnhub", return_value=mock_finnhub):
            news = manager.get_news("AAPL", date(2026, 4, 10))
            assert len(news) == 1
            assert news[0]["headline"] == "AAPL up"

    def test_fallback_to_polygon_when_finnhub_fails(self, manager):
        mock_finnhub = MagicMock()
        mock_finnhub.get_company_news.side_effect = Exception("fail")

        mock_polygon = MagicMock()
        mock_polygon.get_ticker_news.return_value = [{"title": "polygon news"}]

        with patch.object(manager, "_get_finnhub", return_value=mock_finnhub), \
             patch.object(manager, "_get_polygon", return_value=mock_polygon):
            news = manager.get_news("AAPL", date(2026, 4, 10))
            assert len(news) == 1
            assert news[0]["title"] == "polygon news"

    def test_returns_empty_when_all_sources_fail(self, manager):
        mock_finnhub = MagicMock()
        mock_finnhub.get_company_news.side_effect = Exception("fail")

        mock_polygon = MagicMock()
        mock_polygon.get_ticker_news.side_effect = Exception("fail")

        with patch.object(manager, "_get_finnhub", return_value=mock_finnhub), \
             patch.object(manager, "_get_polygon", return_value=mock_polygon):
            news = manager.get_news("AAPL", date(2026, 4, 10))
            assert news == []

    def test_returns_empty_when_no_clients_available(self, manager):
        with patch.object(manager, "_get_finnhub", return_value=None), \
             patch.object(manager, "_get_polygon", return_value=None):
            news = manager.get_news("AAPL", date(2026, 4, 10))
            assert news == []

    def test_finnhub_empty_falls_through_to_polygon(self, manager):
        mock_finnhub = MagicMock()
        mock_finnhub.get_company_news.return_value = []  # empty, not failure

        mock_polygon = MagicMock()
        mock_polygon.get_ticker_news.return_value = [{"title": "fallback news"}]

        with patch.object(manager, "_get_finnhub", return_value=mock_finnhub), \
             patch.object(manager, "_get_polygon", return_value=mock_polygon):
            news = manager.get_news("AAPL", date(2026, 4, 10))
            assert len(news) == 1


# ---------------------------------------------------------------------------
# Test: fallback chain -- get_insider_data
# ---------------------------------------------------------------------------

class TestGetInsiderData:
    def test_finnhub_success(self, manager):
        mock_finnhub = MagicMock()
        mock_finnhub.get_insider_transactions.return_value = [{"name": "Tim Cook"}]
        mock_finnhub.get_insider_sentiment.return_value = {"mspr": 0.5}

        with patch.object(manager, "_get_finnhub", return_value=mock_finnhub):
            result = manager.get_insider_data("AAPL", date(2026, 4, 10))
            assert result["source"] == "finnhub"
            assert len(result["transactions"]) == 1

    def test_sec_fallback(self, manager):
        mock_finnhub = MagicMock()
        mock_finnhub.get_insider_transactions.side_effect = Exception("fail")

        mock_sec = MagicMock()
        mock_sec.get_insider_filings.return_value = [{"form": "4"}]

        with patch.object(manager, "_get_finnhub", return_value=mock_finnhub), \
             patch.object(manager, "_get_sec", return_value=mock_sec):
            result = manager.get_insider_data("AAPL", date(2026, 4, 10))
            assert result["source"] == "sec"

    def test_all_fail_gracefully(self, manager):
        with patch.object(manager, "_get_finnhub", return_value=None), \
             patch.object(manager, "_get_sec", return_value=None):
            result = manager.get_insider_data("AAPL", date(2026, 4, 10))
            assert result["transactions"] == []


# ---------------------------------------------------------------------------
# Test: data quality meta-features
# ---------------------------------------------------------------------------

class TestDataQualityMeta:
    def test_data_completeness_all_present(self, manager):
        features = {"a": 1.0, "b": 2.0, "c": 3.0}
        meta = manager._compute_data_quality_meta("AAPL", date(2026, 4, 10), features)
        assert meta["data_completeness_score"] == 1.0

    def test_data_completeness_with_nans(self, manager):
        features = {"a": 1.0, "b": np.nan, "c": np.nan, "d": 4.0}
        meta = manager._compute_data_quality_meta("AAPL", date(2026, 4, 10), features)
        assert meta["data_completeness_score"] == 0.5

    def test_data_completeness_empty(self, manager):
        meta = manager._compute_data_quality_meta("AAPL", date(2026, 4, 10), {})
        assert meta["data_completeness_score"] == 0.0

    def test_source_count(self, manager):
        manager._finnhub_available = True
        manager._polygon_available = True
        manager._sec_available = False
        meta = manager._compute_data_quality_meta("AAPL", date(2026, 4, 10), {"a": 1.0})
        assert meta["data_source_count"] == 2.0

    def test_primary_source_available(self, manager):
        manager._finnhub_available = True
        meta = manager._compute_data_quality_meta("AAPL", date(2026, 4, 10), {})
        assert meta["primary_source_available"] == 1.0

        manager._finnhub_available = False
        meta = manager._compute_data_quality_meta("AAPL", date(2026, 4, 10), {})
        assert meta["primary_source_available"] == 0.0


# ---------------------------------------------------------------------------
# Test: cross-source agreement
# ---------------------------------------------------------------------------

class TestCrossSourceAgreement:
    def test_both_sources_have_data(self, manager):
        mock_finnhub = MagicMock()
        mock_finnhub.get_insider_transactions.return_value = [1, 2, 3, 4, 5]

        mock_sec = MagicMock()
        mock_sec.get_insider_filings.return_value = [1, 2, 3]

        with patch.object(manager, "_get_finnhub", return_value=mock_finnhub), \
             patch.object(manager, "_get_sec", return_value=mock_sec):
            agreement = manager._compute_cross_source_agreement("AAPL")
            assert agreement == 0.6  # 3/5

    def test_both_empty(self, manager):
        mock_finnhub = MagicMock()
        mock_finnhub.get_insider_transactions.return_value = []

        mock_sec = MagicMock()
        mock_sec.get_insider_filings.return_value = []

        with patch.object(manager, "_get_finnhub", return_value=mock_finnhub), \
             patch.object(manager, "_get_sec", return_value=mock_sec):
            assert manager._compute_cross_source_agreement("AAPL") == 1.0

    def test_one_has_data_other_empty(self, manager):
        mock_finnhub = MagicMock()
        mock_finnhub.get_insider_transactions.return_value = [1, 2]

        with patch.object(manager, "_get_finnhub", return_value=mock_finnhub), \
             patch.object(manager, "_get_sec", return_value=None):
            assert manager._compute_cross_source_agreement("AAPL") == 0.0


# ---------------------------------------------------------------------------
# Test: get_all_features
# ---------------------------------------------------------------------------

class TestGetAllFeatures:
    def test_returns_expected_feature_keys(self, manager):
        mock_sec = MagicMock()
        mock_sec.get_features.return_value = {
            "sec_filing_count_90d": 5.0,
            "sec_filing_recency_days": 10.0,
            "sec_form4_count_90d": 3.0,
            "sec_13f_count_qtr": 1.0,
        }

        mock_finnhub = MagicMock()
        mock_finnhub.get_features.return_value = {
            "finnhub_social_sentiment": 0.7,
            "reddit_mentions_24h": 42.0,
        }
        mock_finnhub.get_insider_transactions.return_value = []

        mock_polygon = MagicMock()
        mock_polygon._api_key = "key"
        mock_polygon.get_features.return_value = {
            "polygon_peer_count": 5.0,
        }

        with patch.object(manager, "_get_sec", return_value=mock_sec), \
             patch.object(manager, "_get_finnhub", return_value=mock_finnhub), \
             patch.object(manager, "_get_polygon", return_value=mock_polygon), \
             patch.object(manager, "_compute_peer_relative_perf", return_value=0.01), \
             patch.object(manager, "_compute_sector_rotation_score", return_value=0.05):
            features = manager.get_all_features("AAPL", date(2026, 4, 10))

            # SEC features
            assert features["sec_filing_count_90d"] == 5.0
            assert features["sec_form4_count_90d"] == 3.0

            # Social features
            assert features["finnhub_social_sentiment"] == 0.7
            assert features["reddit_mentions_24h"] == 42.0

            # Peer/sector features
            assert features["peer_relative_perf_5d"] == 0.01
            assert features["sector_rotation_score"] == 0.05

            # Data quality meta-features
            assert "data_source_count" in features
            assert "data_completeness_score" in features
            assert "primary_source_available" in features
            assert "cross_source_agreement" in features
            assert "data_freshness_hours" in features

    def test_all_sources_fail_gracefully(self, manager):
        with patch.object(manager, "_get_sec", return_value=None), \
             patch.object(manager, "_get_finnhub", return_value=None), \
             patch.object(manager, "_get_polygon", return_value=None), \
             patch.object(manager, "_compute_peer_relative_perf", return_value=np.nan), \
             patch.object(manager, "_compute_sector_rotation_score", return_value=np.nan):
            features = manager.get_all_features("AAPL", date(2026, 4, 10))
            # Should still return a dict with NaN defaults
            assert isinstance(features, dict)
            assert "sec_filing_count_90d" in features
            assert "finnhub_social_sentiment" in features
            assert "data_completeness_score" in features


# ---------------------------------------------------------------------------
# Test: get_company_details fallback
# ---------------------------------------------------------------------------

class TestGetCompanyDetails:
    def test_yfinance_success(self, manager):
        mock_yf = MagicMock()
        mock_yf_ticker = MagicMock()
        mock_yf_ticker.info = {
            "shortName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "marketCap": 3000000000000,
            "fullTimeEmployees": 164000,
        }
        mock_yf.Ticker.return_value = mock_yf_ticker

        import sys
        with patch.dict(sys.modules, {"yfinance": mock_yf}):
            details = manager.get_company_details("AAPL")
            assert details["name"] == "Apple Inc."
            assert details["source"] == "yfinance"

    def test_polygon_fallback(self, manager):
        mock_polygon = MagicMock()
        mock_polygon.get_ticker_details.return_value = {
            "name": "Apple Inc.",
            "sic_description": "Electronics",
        }

        import sys
        # Make yfinance import raise ImportError
        with patch.dict(sys.modules, {"yfinance": None}), \
             patch.object(manager, "_get_polygon", return_value=mock_polygon):
            details = manager.get_company_details("AAPL")
            assert details["name"] == "Apple Inc."
            assert details["source"] == "polygon"


# ---------------------------------------------------------------------------
# Test: singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_source_manager_returns_same_instance(self):
        from shared.data.source_manager import get_source_manager
        a = get_source_manager()
        b = get_source_manager()
        assert a is b
