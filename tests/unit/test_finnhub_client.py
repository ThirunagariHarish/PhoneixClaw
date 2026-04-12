"""Unit tests for shared.data.finnhub_client."""

from __future__ import annotations

import os
import shutil
import time
from datetime import date
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

# Ensure the module can be imported
os.environ.setdefault("FINNHUB_API_KEY", "test-key-123")

from shared.data.finnhub_client import FinnhubClient, get_finnhub_client

CACHE_DIR = "/tmp/phoenix_finnhub_cache_test"


@pytest.fixture(autouse=True)
def _clean_singleton():
    """Reset module-level singleton and test cache between tests."""
    import shared.data.finnhub_client as mod
    mod._client_instance = None
    FinnhubClient._instance = None
    if Path(CACHE_DIR).exists():
        shutil.rmtree(CACHE_DIR)
    yield
    if Path(CACHE_DIR).exists():
        shutil.rmtree(CACHE_DIR)
    mod._client_instance = None
    FinnhubClient._instance = None


def _make_client() -> FinnhubClient:
    c = FinnhubClient(api_key="test-key")
    c._cache_dir = Path(CACHE_DIR)
    c._cache_dir.mkdir(parents=True, exist_ok=True)
    return c


# -----------------------------------------------------------------------
# HTTP endpoint mocking
# -----------------------------------------------------------------------

SAMPLE_NEWS = [
    {
        "datetime": 1700000000,
        "headline": "AAPL surges on strong earnings",
        "source": "Reuters",
        "url": "https://example.com/1",
        "summary": "Apple reported record revenue.",
    },
    {
        "datetime": 1700010000,
        "headline": "AAPL faces supply chain issues",
        "source": "Bloomberg",
        "url": "https://example.com/2",
        "summary": "Supply chain concerns weigh.",
    },
]

SAMPLE_NEWS_SENTIMENT = {
    "buzz": {"articlesInLastWeek": 42, "weeklyAverage": 30.0},
    "companyNewsScore": 0.75,
    "sectorAverageBullishPercent": 0.55,
    "sentiment": {"bearishPercent": 0.2, "bullishPercent": 0.8},
}

SAMPLE_INSIDER_TRANSACTIONS = {
    "data": [
        {"name": "Tim Cook", "share": 50000, "change": -10000, "transactionDate": "2024-01-15"},
    ]
}

SAMPLE_EARNINGS = [
    {"actual": 1.46, "estimate": 1.39, "period": "2024-01-01", "surprise": 0.07},
    {"actual": 1.29, "estimate": 1.30, "period": "2023-10-01", "surprise": -0.01},
]

SAMPLE_RECOMMENDATIONS = [
    {"buy": 25, "hold": 8, "sell": 2, "period": "2024-01-01", "strongBuy": 10, "strongSell": 0},
]

SAMPLE_PRICE_TARGET = {
    "lastUpdated": "2024-01-20",
    "targetHigh": 250.0,
    "targetLow": 180.0,
    "targetMean": 215.0,
    "targetMedian": 210.0,
}

SAMPLE_SOCIAL_SENTIMENT = {
    "reddit": [
        {"atTime": "2024-01-20T00:00:00", "mention": 150, "positiveScore": 0.65, "score": 0.42},
    ],
    "twitter": [
        {"atTime": "2024-01-20T00:00:00", "mention": 500, "score": 0.38},
    ],
}


class TestFinnhubClientMethods:
    """Test individual API methods with mocked HTTP."""

    def test_get_company_news(self):
        client = _make_client()
        with patch.object(client, "_http_get", return_value=SAMPLE_NEWS):
            result = client.get_company_news("AAPL", "2024-01-01", "2024-01-31")
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["headline"] == "AAPL surges on strong earnings"

    def test_get_news_sentiment(self):
        client = _make_client()
        with patch.object(client, "_http_get", return_value=SAMPLE_NEWS_SENTIMENT):
            result = client.get_news_sentiment("AAPL")
        assert result["companyNewsScore"] == 0.75
        assert result["buzz"]["articlesInLastWeek"] == 42

    def test_get_insider_transactions(self):
        client = _make_client()
        with patch.object(client, "_http_get", return_value=SAMPLE_INSIDER_TRANSACTIONS):
            result = client.get_insider_transactions("AAPL")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "Tim Cook"

    def test_get_earnings_surprises(self):
        client = _make_client()
        with patch.object(client, "_http_get", return_value=SAMPLE_EARNINGS):
            result = client.get_earnings_surprises("AAPL")
        assert len(result) == 2
        assert result[0]["surprise"] == 0.07

    def test_get_recommendation_trends(self):
        client = _make_client()
        with patch.object(client, "_http_get", return_value=SAMPLE_RECOMMENDATIONS):
            result = client.get_recommendation_trends("AAPL")
        assert len(result) == 1
        assert result[0]["buy"] == 25

    def test_get_price_target(self):
        client = _make_client()
        with patch.object(client, "_http_get", return_value=SAMPLE_PRICE_TARGET):
            result = client.get_price_target("AAPL")
        assert result["targetMean"] == 215.0

    def test_get_social_sentiment(self):
        client = _make_client()
        with patch.object(client, "_http_get", return_value=SAMPLE_SOCIAL_SENTIMENT):
            result = client.get_social_sentiment("AAPL")
        assert "reddit" in result
        assert result["reddit"][0]["mention"] == 150


class TestFinnhubGracefulFailure:
    """Test that all methods return empty on failure."""

    def test_company_news_returns_empty_on_error(self):
        client = _make_client()
        with patch.object(client, "_http_get", side_effect=RuntimeError("timeout")):
            result = client.get_company_news("AAPL", "2024-01-01", "2024-01-31")
        assert result == []

    def test_news_sentiment_returns_empty_on_error(self):
        client = _make_client()
        with patch.object(client, "_http_get", side_effect=RuntimeError("500")):
            result = client.get_news_sentiment("AAPL")
        assert result == {}

    def test_no_api_key_returns_empty(self):
        client = _make_client()
        client._api_key = ""
        result = client.get_company_news("AAPL", "2024-01-01", "2024-01-31")
        assert result == []  # _get_list returns [] when no key

    def test_social_sentiment_returns_empty_on_error(self):
        client = _make_client()
        with patch.object(client, "_http_get", side_effect=RuntimeError("err")):
            result = client.get_social_sentiment("AAPL")
        assert result == {}


class TestFinnhubCache:
    """Test disk caching behavior."""

    def test_cache_hit_avoids_http(self):
        client = _make_client()
        # First call: populate cache
        with patch.object(client, "_http_get", return_value=SAMPLE_NEWS) as mock_http:
            result1 = client.get_company_news("AAPL", "2024-01-01", "2024-01-31")
            assert mock_http.call_count == 1

        # Second call: should hit cache, no HTTP
        with patch.object(client, "_http_get", return_value=[]) as mock_http:
            result2 = client.get_company_news("AAPL", "2024-01-01", "2024-01-31")
            assert mock_http.call_count == 0

        assert len(result1) == len(result2)

    def test_cache_miss_when_stale(self):
        client = _make_client()
        # Populate cache using price_target (default 6h TTL)
        with patch.object(client, "_http_get", return_value=SAMPLE_PRICE_TARGET):
            client.get_price_target("AAPL")

        # Force cache to be stale by modifying mtime (older than 6h default TTL)
        cache_files = list(client._cache_dir.glob("*.json"))
        assert len(cache_files) > 0
        old_time = time.time() - 25200  # 7 hours ago (> 6h default TTL)
        for f in cache_files:
            os.utime(f, (old_time, old_time))

        # Should make a new HTTP request since cache is stale
        with patch.object(client, "_http_get", return_value={"targetMean": 220.0}) as mock_http:
            result = client.get_price_target("AAPL")
            assert mock_http.call_count == 1
            assert result["targetMean"] == 220.0


class TestFinnhubRateLimiting:
    """Test rate limiting behavior."""

    def test_rate_limit_tracking(self):
        client = _make_client()
        client._requests_per_minute = 5
        # Fill the rate limiter
        for _ in range(5):
            client._request_timestamps.append(time.monotonic())

        # Next call should block/wait
        client._wait_for_rate_limit()
        # It should have waited some amount of time (but we can't be too precise)
        # Just verify the timestamp list grew
        assert len(client._request_timestamps) == 6


class TestFinnhubGetFeatures:
    """Test the get_features aggregator method."""

    def test_returns_float_dict(self):
        client = _make_client()
        with patch.object(client, "get_news_sentiment", return_value=SAMPLE_NEWS_SENTIMENT), \
             patch.object(client, "get_social_sentiment", return_value=SAMPLE_SOCIAL_SENTIMENT):
            features = client.get_features("AAPL", date(2024, 1, 20))

        assert isinstance(features, dict)
        assert features["finnhub_news_score"] == 0.75
        assert features["finnhub_buzz_articles"] == 42.0
        assert features["reddit_mentions_24h"] == 150.0

    def test_returns_nan_on_failure(self):
        client = _make_client()
        with patch.object(client, "get_news_sentiment", side_effect=Exception("fail")), \
             patch.object(client, "get_social_sentiment", side_effect=Exception("fail")):
            features = client.get_features("AAPL", date(2024, 1, 20))

        assert np.isnan(features["finnhub_news_score"])
        assert np.isnan(features["finnhub_social_sentiment"])


class TestFinnhubSingleton:
    """Test singleton accessor."""

    def test_get_finnhub_client_returns_same_instance(self):
        import shared.data.finnhub_client as mod
        mod._client_instance = None
        c1 = get_finnhub_client()
        c2 = get_finnhub_client()
        assert c1 is c2
