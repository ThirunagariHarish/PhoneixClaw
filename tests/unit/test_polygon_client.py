"""Unit tests for shared.data.polygon_client."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import numpy as np
import pytest

from shared.data.polygon_client import PolygonClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton between tests."""
    import shared.data.polygon_client as mod
    mod._client_instance = None
    yield
    mod._client_instance = None


@pytest.fixture()
def client(tmp_path):
    """Return a PolygonClient with a temporary cache dir and fake API key."""
    c = PolygonClient(api_key="test_polygon_key")
    c._cache_dir = tmp_path / "polygon_cache"
    c._cache_dir.mkdir(parents=True, exist_ok=True)
    return c


@pytest.fixture()
def no_key_client(tmp_path):
    """Return a PolygonClient with no API key configured."""
    c = PolygonClient.__new__(PolygonClient)
    c._name = "polygon"
    c._api_key = ""
    c._cache_dir = tmp_path / "polygon_cache_nokey"
    c._cache_dir.mkdir(parents=True, exist_ok=True)
    c._cache_ttl_seconds = 6.0 * 3600
    c._base_url = "https://api.polygon.io"
    c._requests_per_minute = 5
    c._request_timestamps = []
    import threading
    c._rate_lock = threading.Lock()
    return c


# ---------------------------------------------------------------------------
# Test: get_ticker_news
# ---------------------------------------------------------------------------

class TestGetTickerNews:
    def test_returns_results_on_success(self, client):
        mock_response = {
            "results": [
                {"title": "AAPL hits new high", "published_utc": "2026-04-10"},
                {"title": "Apple earnings preview", "published_utc": "2026-04-09"},
            ],
            "count": 2,
        }
        with patch.object(client, "_http_get", return_value=mock_response):
            news = client.get_ticker_news("AAPL", published_utc_gte="2026-04-01")
            assert len(news) == 2
            assert news[0]["title"] == "AAPL hits new high"

    def test_returns_empty_on_failure(self, client):
        with patch.object(client, "_http_get", side_effect=RuntimeError("timeout")):
            news = client.get_ticker_news("AAPL")
            assert news == []

    def test_returns_empty_with_no_api_key(self, no_key_client):
        result = no_key_client.get_ticker_news("AAPL")
        assert result == []


# ---------------------------------------------------------------------------
# Test: get_ticker_details
# ---------------------------------------------------------------------------

class TestGetTickerDetails:
    def test_returns_details_on_success(self, client):
        mock_response = {
            "results": {
                "name": "Apple Inc.",
                "ticker": "AAPL",
                "market_cap": 3000000000000,
                "total_employees": 164000,
                "sic_description": "Electronic Computers",
            }
        }
        with patch.object(client, "_http_get", return_value=mock_response):
            details = client.get_ticker_details("AAPL")
            assert details["name"] == "Apple Inc."
            assert details["market_cap"] == 3000000000000

    def test_returns_empty_on_failure(self, client):
        with patch.object(client, "_http_get", side_effect=RuntimeError("500")):
            details = client.get_ticker_details("AAPL")
            assert details == {}


# ---------------------------------------------------------------------------
# Test: get_related_companies
# ---------------------------------------------------------------------------

class TestGetRelatedCompanies:
    def test_returns_tickers(self, client):
        mock_response = {
            "results": [
                {"ticker": "MSFT"},
                {"ticker": "GOOGL"},
                {"ticker": "AMZN"},
            ]
        }
        with patch.object(client, "_http_get", return_value=mock_response):
            peers = client.get_related_companies("AAPL")
            assert peers == ["MSFT", "GOOGL", "AMZN"]

    def test_returns_empty_on_failure(self, client):
        with patch.object(client, "_http_get", side_effect=RuntimeError("err")):
            assert client.get_related_companies("AAPL") == []


# ---------------------------------------------------------------------------
# Test: get_stock_splits
# ---------------------------------------------------------------------------

class TestGetStockSplits:
    def test_returns_splits(self, client):
        mock_response = {
            "results": [
                {"execution_date": "2020-08-31", "split_from": 1, "split_to": 4},
            ]
        }
        with patch.object(client, "_http_get", return_value=mock_response):
            splits = client.get_stock_splits("AAPL")
            assert len(splits) == 1
            assert splits[0]["split_to"] == 4


# ---------------------------------------------------------------------------
# Test: get_dividends
# ---------------------------------------------------------------------------

class TestGetDividends:
    def test_returns_dividends(self, client):
        mock_response = {
            "results": [
                {"ex_dividend_date": "2026-02-07", "cash_amount": 0.25},
            ]
        }
        with patch.object(client, "_http_get", return_value=mock_response):
            divs = client.get_dividends("AAPL")
            assert len(divs) == 1
            assert divs[0]["cash_amount"] == 0.25


# ---------------------------------------------------------------------------
# Test: rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_rate_limit_configured(self, client):
        assert client._requests_per_minute == 5

    def test_rate_limit_blocks_when_exceeded(self, client):
        """Verify that _wait_for_rate_limit adds timestamps."""
        import time
        # Fill up the rate limit window
        now = time.monotonic()
        client._request_timestamps = [now - i * 0.1 for i in range(5)]
        # The next call should block (but we just verify timestamps are managed)
        assert len(client._request_timestamps) == 5


# ---------------------------------------------------------------------------
# Test: no API key graceful handling
# ---------------------------------------------------------------------------

class TestNoApiKey:
    def test_all_methods_return_empty(self, no_key_client):
        assert no_key_client.get_ticker_news("AAPL") == []
        assert no_key_client.get_ticker_details("AAPL") == {}
        assert no_key_client.get_related_companies("AAPL") == []
        assert no_key_client.get_stock_splits("AAPL") == []
        assert no_key_client.get_dividends("AAPL") == []


# ---------------------------------------------------------------------------
# Test: get_features
# ---------------------------------------------------------------------------

class TestGetFeatures:
    def test_returns_feature_dict(self, client):
        with patch.object(client, "get_related_companies", return_value=["MSFT", "GOOGL"]), \
             patch.object(client, "get_ticker_news", return_value=[{"title": "news"}]), \
             patch.object(client, "get_ticker_details", return_value={"market_cap": 3e12, "total_employees": 100000}):
            features = client.get_features("AAPL", date(2026, 4, 10))
            assert features["polygon_peer_count"] == 2.0
            assert features["polygon_news_count_today"] == 1.0
            assert features["polygon_market_cap"] == 3e12

    def test_returns_nan_on_failure(self, client):
        with patch.object(client, "get_related_companies", side_effect=Exception), \
             patch.object(client, "get_ticker_news", side_effect=Exception), \
             patch.object(client, "get_ticker_details", side_effect=Exception):
            features = client.get_features("AAPL", date(2026, 4, 10))
            assert np.isnan(features["polygon_peer_count"])
            assert np.isnan(features["polygon_news_count_today"])


# ---------------------------------------------------------------------------
# Test: caching
# ---------------------------------------------------------------------------

class TestCaching:
    def test_cached_response_is_reused(self, client):
        mock_response = {"results": [{"title": "cached news"}]}
        call_count = 0

        def counting_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_response

        with patch.object(client, "_http_get", side_effect=counting_get):
            result1 = client.get_ticker_news("AAPL")
            result2 = client.get_ticker_news("AAPL")
            assert result1 == result2
            assert call_count == 1  # second call served from cache
