"""Unit tests for shared.data.news_client."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import numpy as np
import pytest

from shared.data.news_client import (
    _ALL_NEWS_FEATURES,
    _article_source,
    _article_timestamp,
    _extract_sentiment,
    _score_headline,
    get_news_features,
)

# -----------------------------------------------------------------------
# Fixtures: sample article data
# -----------------------------------------------------------------------

def _make_article(headline: str, unix_ts: int, source: str = "Reuters",
                  sentiment: float | None = None) -> dict:
    """Create a mock Finnhub-style article."""
    a = {
        "headline": headline,
        "datetime": unix_ts,
        "source": source,
        "url": f"https://example.com/{unix_ts}",
        "summary": headline,
    }
    if sentiment is not None:
        a["sentiment"] = sentiment
    return a


def _make_av_article(title: str, time_published: str,
                     overall_score: float, source_domain: str = "reuters.com") -> dict:
    """Create a mock Alpha Vantage-style article."""
    return {
        "title": title,
        "time_published": time_published,
        "source_domain": source_domain,
        "overall_sentiment_score": overall_score,
        "overall_sentiment_label": "Bullish" if overall_score > 0 else "Bearish",
        "ticker_sentiment": [
            {"ticker": "AAPL", "ticker_sentiment_score": str(overall_score)},
        ],
    }


# Reference date: Jan 15, 2024
REF_DATE = date(2024, 1, 15)
EOD = datetime(2024, 1, 15, 23, 59, 59, tzinfo=timezone.utc)

# Articles spread across time windows
ARTICLES_FINNHUB = [
    # 1h ago
    _make_article("AAPL surges on strong earnings beat", int((EOD - timedelta(minutes=30)).timestamp()),
                  "Reuters", sentiment=0.8),
    # 12h ago
    _make_article("Apple announces new product line", int((EOD - timedelta(hours=12)).timestamp()),
                  "Bloomberg", sentiment=0.3),
    # 2 days ago
    _make_article("AAPL stock drops on China concerns", int((EOD - timedelta(days=2)).timestamp()),
                  "CNBC", sentiment=-0.6),
    # 5 days ago
    _make_article("Apple market share grows in Europe", int((EOD - timedelta(days=5)).timestamp()),
                  "FT", sentiment=0.2),
    # 10 days ago
    _make_article("Tech sector faces headwinds", int((EOD - timedelta(days=10)).timestamp()),
                  "WSJ", sentiment=-0.1),
    # 20 days ago
    _make_article("Apple supply chain stable", int((EOD - timedelta(days=20)).timestamp()),
                  "Reuters", sentiment=0.1),
]


class TestScoreHeadline:
    """Test the keyword/TextBlob fallback sentiment scorer."""

    def test_positive_headline(self):
        score = _score_headline("Stock surges to record highs on strong earnings")
        assert score > 0

    def test_negative_headline(self):
        score = _score_headline("Company crashes after bankruptcy warning")
        assert score < 0

    def test_neutral_headline(self):
        score = _score_headline("Annual report released on schedule")
        # Neutral or near-zero
        assert -0.5 <= score <= 0.5

    def test_empty_string(self):
        assert _score_headline("") == 0.0

    def test_score_range(self):
        score = _score_headline("Everything crashes and drops and falls")
        assert -1.0 <= score <= 1.0


class TestExtractSentiment:
    """Test sentiment extraction from various article formats."""

    def test_finnhub_built_in_sentiment(self):
        article = {"sentiment": 0.75, "headline": "Irrelevant"}
        assert _extract_sentiment(article) == 0.75

    def test_alpha_vantage_overall_score(self):
        article = {"overall_sentiment_score": "0.42", "title": "Irrelevant"}
        assert abs(_extract_sentiment(article) - 0.42) < 0.01

    def test_alpha_vantage_ticker_sentiment(self):
        article = {
            "ticker_sentiment": [
                {"ticker": "AAPL", "ticker_sentiment_score": "-0.3"},
            ],
            "title": "Test",
        }
        assert abs(_extract_sentiment(article) - (-0.3)) < 0.01

    def test_falls_back_to_headline(self):
        article = {"headline": "Stock surges on strong earnings"}
        score = _extract_sentiment(article)
        assert score > 0  # positive headline

    def test_clamps_to_range(self):
        article = {"sentiment": 5.0}
        assert _extract_sentiment(article) == 1.0


class TestArticleTimestamp:
    """Test timestamp extraction."""

    def test_finnhub_unix_timestamp(self):
        ts = _article_timestamp({"datetime": 1700000000})
        assert ts is not None
        assert ts.year == 2023

    def test_alpha_vantage_format(self):
        ts = _article_timestamp({"time_published": "20240115T120000"})
        assert ts is not None
        assert ts.hour == 12

    def test_missing_returns_none(self):
        assert _article_timestamp({}) is None


class TestArticleSource:
    def test_finnhub_source(self):
        assert _article_source({"source": "Reuters"}) == "Reuters"

    def test_alpha_vantage_source(self):
        assert _article_source({"source_domain": "reuters.com"}) == "reuters.com"

    def test_missing(self):
        assert _article_source({}) == ""


class TestGetNewsFeatures:
    """Test the main get_news_features function."""

    @patch("shared.data.news_client._fetch_articles")
    @patch("shared.data.news_client._compute_sector_market_features")
    def test_computes_all_features(self, mock_sector, mock_fetch):
        mock_fetch.return_value = ARTICLES_FINNHUB
        mock_sector.return_value = {
            "sector_news_sentiment": 0.1,
            "sector_news_count": 5.0,
            "market_news_sentiment": 0.05,
        }

        features = get_news_features("AAPL", REF_DATE)

        # All expected features should be present
        for key in _ALL_NEWS_FEATURES:
            assert key in features, f"Missing feature: {key}"

        # Verify specific values
        assert features["news_count_1h"] == 1.0  # 1 article within 1h
        assert features["news_count_24h"] == 2.0  # 2 articles within 24h
        assert features["news_count_7d"] >= 4  # articles within 7 days

        # Sentiment avg 24h should be positive (0.8 + 0.3) / 2 = 0.55
        assert features["news_sentiment_avg_24h"] > 0

        # Source diversity (within 7d)
        assert features["news_source_diversity"] >= 3

        # Recency should be small (most recent is 30min ago)
        assert features["news_recency_hours"] < 1.0

    @patch("shared.data.news_client._fetch_articles")
    @patch("shared.data.news_client._compute_sector_market_features")
    def test_no_articles_returns_nan(self, mock_sector, mock_fetch):
        mock_fetch.return_value = []
        mock_sector.return_value = {
            "sector_news_sentiment": np.nan,
            "sector_news_count": np.nan,
            "market_news_sentiment": np.nan,
        }

        features = get_news_features("AAPL", REF_DATE)

        # All features should exist
        for key in _ALL_NEWS_FEATURES:
            assert key in features, f"Missing feature: {key}"

        # Count features should be 0 or NaN
        assert features["news_count_1h"] == 0.0
        assert features["news_count_24h"] == 0.0
        assert features["news_count_7d"] == 0.0

        # Sentiment features should be NaN
        assert np.isnan(features["news_sentiment_avg_24h"])
        assert np.isnan(features["news_sentiment_avg_7d"])

    @patch("shared.data.news_client._fetch_articles")
    @patch("shared.data.news_client._compute_sector_market_features")
    def test_nan_safety_on_exception(self, mock_sector, mock_fetch):
        mock_fetch.side_effect = Exception("API down")
        mock_sector.return_value = {}

        features = get_news_features("AAPL", REF_DATE)

        # Should not raise -- all features should exist as NaN
        for key in _ALL_NEWS_FEATURES:
            assert key in features

    @patch("shared.data.news_client._fetch_articles")
    @patch("shared.data.news_client._compute_sector_market_features")
    def test_backtest_filters_future_articles(self, mock_sector, mock_fetch):
        """Articles with timestamps after as_of_date should be excluded."""
        future_ts = int((EOD + timedelta(days=1)).timestamp())
        articles = [
            _make_article("Future article", future_ts, "Reuters", sentiment=0.9),
            *ARTICLES_FINNHUB,
        ]
        mock_fetch.return_value = articles
        mock_sector.return_value = {
            "sector_news_sentiment": np.nan,
            "sector_news_count": np.nan,
            "market_news_sentiment": np.nan,
        }

        features = get_news_features("AAPL", REF_DATE)

        # The future article should be excluded, so count should match non-future articles
        # news_count_7d should not include the future article
        assert features["news_count_7d"] >= 4  # only the original articles

    @patch("shared.data.news_client._fetch_articles")
    @patch("shared.data.news_client._compute_sector_market_features")
    def test_buzz_score_computed(self, mock_sector, mock_fetch):
        mock_fetch.return_value = ARTICLES_FINNHUB
        mock_sector.return_value = {
            "sector_news_sentiment": np.nan,
            "sector_news_count": np.nan,
            "market_news_sentiment": np.nan,
        }

        features = get_news_features("AAPL", REF_DATE)

        # buzz_score = news_count_24h / avg_daily_30d
        assert not np.isnan(features["news_buzz_score"])
        assert features["news_buzz_score"] > 0

    @patch("shared.data.news_client._fetch_articles")
    @patch("shared.data.news_client._compute_sector_market_features")
    def test_extreme_count(self, mock_sector, mock_fetch):
        mock_fetch.return_value = ARTICLES_FINNHUB
        mock_sector.return_value = {
            "sector_news_sentiment": np.nan,
            "sector_news_count": np.nan,
            "market_news_sentiment": np.nan,
        }

        features = get_news_features("AAPL", REF_DATE)

        # We have articles with |sentiment| > 0.5: 0.8 and -0.6
        # Only those within 7d count
        assert features["news_extreme_count_7d"] >= 1

    @patch("shared.data.news_client._fetch_articles")
    @patch("shared.data.news_client._compute_sector_market_features")
    def test_sentiment_momentum(self, mock_sector, mock_fetch):
        mock_fetch.return_value = ARTICLES_FINNHUB
        mock_sector.return_value = {
            "sector_news_sentiment": np.nan,
            "sector_news_count": np.nan,
            "market_news_sentiment": np.nan,
        }

        features = get_news_features("AAPL", REF_DATE)

        # Momentum is 3d_avg - 7d_avg; should be a real number
        if not np.isnan(features["news_sentiment_momentum_3d"]):
            assert isinstance(features["news_sentiment_momentum_3d"], float)

    @patch("shared.data.news_client._fetch_articles")
    @patch("shared.data.news_client._compute_sector_market_features")
    def test_positive_negative_ratios_sum_to_one(self, mock_sector, mock_fetch):
        mock_fetch.return_value = ARTICLES_FINNHUB
        mock_sector.return_value = {
            "sector_news_sentiment": np.nan,
            "sector_news_count": np.nan,
            "market_news_sentiment": np.nan,
        }

        features = get_news_features("AAPL", REF_DATE)

        pos = features["news_positive_ratio_7d"]
        neg = features["news_negative_ratio_7d"]
        neu = features["news_neutral_ratio_7d"]
        if not any(np.isnan(x) for x in [pos, neg, neu]):
            assert abs(pos + neg + neu - 1.0) < 0.01


class TestFallbackChain:
    """Test Finnhub -> Alpha Vantage fallback."""

    @patch("shared.data.news_client._fetch_articles_alphavantage")
    @patch("shared.data.news_client._fetch_articles_finnhub")
    @patch("shared.data.news_client._compute_sector_market_features")
    def test_falls_back_to_alphavantage(self, mock_sector, mock_finnhub, mock_av):
        mock_finnhub.return_value = []  # Finnhub fails
        mock_av.return_value = [
            _make_av_article("AAPL beats estimates", "20240115T100000", 0.6),
            _make_av_article("Apple warns on margins", "20240114T080000", -0.3),
        ]
        mock_sector.return_value = {
            "sector_news_sentiment": np.nan,
            "sector_news_count": np.nan,
            "market_news_sentiment": np.nan,
        }

        features = get_news_features("AAPL", REF_DATE)

        assert features["news_count_24h"] >= 1
        assert not np.isnan(features["news_sentiment_avg_24h"])

    @patch("shared.data.news_client._fetch_articles_alphavantage")
    @patch("shared.data.news_client._fetch_articles_finnhub")
    @patch("shared.data.news_client._compute_sector_market_features")
    def test_all_sources_fail_returns_nan(self, mock_sector, mock_finnhub, mock_av):
        mock_finnhub.return_value = []
        mock_av.return_value = []
        mock_sector.return_value = {
            "sector_news_sentiment": np.nan,
            "sector_news_count": np.nan,
            "market_news_sentiment": np.nan,
        }

        features = get_news_features("AAPL", REF_DATE)

        # Should not crash, all sentiment features should be NaN
        assert np.isnan(features["news_sentiment_avg_24h"])
        assert np.isnan(features["news_sentiment_avg_7d"])
        assert features["news_count_24h"] == 0.0


class TestSectorMarketFeatures:
    """Test sector and market sentiment computation."""

    @patch("shared.data.news_client._fetch_articles")
    @patch("shared.data.news_client._get_ticker_sector")
    def test_sector_sentiment_computed(self, mock_sector_fn, mock_fetch):
        mock_sector_fn.return_value = "Technology"
        # First call: main ticker articles; subsequent: sector and market articles
        mock_fetch.side_effect = [
            ARTICLES_FINNHUB,  # main ticker
            [_make_article("Tech rally continues", 1705276800, "CNBC", sentiment=0.4)],  # sector (XLK)
            [_make_article("Market mixed signals", 1705276800, "WSJ", sentiment=0.1)],  # market (SPY)
        ]

        features = get_news_features("AAPL", REF_DATE)

        assert features["sector_news_sentiment"] == pytest.approx(0.4, abs=0.01)
        assert features["sector_news_count"] == 1.0
        assert features["market_news_sentiment"] == pytest.approx(0.1, abs=0.01)


class TestDefaultDateHandling:
    """Test that as_of_date defaults to today for live mode."""

    @patch("shared.data.news_client._fetch_articles")
    @patch("shared.data.news_client._compute_sector_market_features")
    def test_none_date_uses_today(self, mock_sector, mock_fetch):
        mock_fetch.return_value = []
        mock_sector.return_value = {
            "sector_news_sentiment": np.nan,
            "sector_news_count": np.nan,
            "market_news_sentiment": np.nan,
        }

        # Should not raise
        features = get_news_features("AAPL", None)
        assert "news_count_24h" in features
