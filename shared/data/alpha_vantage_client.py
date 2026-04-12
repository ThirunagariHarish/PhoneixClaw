"""Alpha Vantage API client with disk caching and daily rate limiting.

Provides news sentiment data as a fallback source when Finnhub is unavailable.

API docs: https://www.alphavantage.co/documentation/
Free tier: 25 requests/day.

Requires: ALPHA_VANTAGE_API_KEY environment variable.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from shared.data.base_client import BaseDataClient

logger = logging.getLogger(__name__)

_CACHE_DIR = "/tmp/phoenix_alphavantage_cache"
_CACHE_TTL_HOURS = 2.0
_DAILY_LIMIT = 25


class AlphaVantageClient(BaseDataClient):
    """Sync HTTP client for Alpha Vantage NEWS_SENTIMENT endpoint.

    Tracks daily request count to stay within the 25 requests/day free-tier
    limit.  Count is persisted to disk so it survives process restarts.
    """

    _instance = None

    def __init__(self, api_key: str | None = None):
        super().__init__(
            name="alphavantage",
            api_key_env="ALPHA_VANTAGE_API_KEY",
            cache_dir=_CACHE_DIR,
            cache_ttl_hours=_CACHE_TTL_HOURS,
            base_url="https://www.alphavantage.co",
            requests_per_minute=5,  # conservative burst limit
        )
        if api_key:
            self._api_key = api_key
        self._daily_count_path = Path(_CACHE_DIR) / "_daily_count.json"
        Path(_CACHE_DIR).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Daily rate tracking
    # ------------------------------------------------------------------

    def _load_daily_count(self) -> tuple[str, int]:
        """Return (date_str, count) from persisted tracker."""
        try:
            if self._daily_count_path.exists():
                data = json.loads(self._daily_count_path.read_text())
                return data.get("date", ""), data.get("count", 0)
        except Exception:
            pass
        return "", 0

    def _save_daily_count(self, date_str: str, count: int) -> None:
        try:
            self._daily_count_path.write_text(
                json.dumps({"date": date_str, "count": count})
            )
        except Exception:
            pass

    def _check_daily_limit(self) -> bool:
        """Return True if we can make another request today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        saved_date, count = self._load_daily_count()
        if saved_date != today:
            # New day -- reset
            self._save_daily_count(today, 0)
            return True
        return count < _DAILY_LIMIT

    def _increment_daily_count(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        saved_date, count = self._load_daily_count()
        if saved_date != today:
            self._save_daily_count(today, 1)
        else:
            self._save_daily_count(today, count + 1)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_news_sentiment(
        self,
        tickers: str,
        time_from: str | None = None,
        time_to: str | None = None,
    ) -> list[dict]:
        """Fetch news articles with sentiment scores from Alpha Vantage.

        Parameters
        ----------
        tickers : str
            Comma-separated tickers, e.g. ``"AAPL"`` or ``"AAPL,MSFT"``.
        time_from, time_to : str, optional
            ``YYYYMMDDTHHMM`` formatted timestamps for date filtering.

        Returns
        -------
        list[dict]
            Each dict contains ``title``, ``url``, ``time_published``,
            ``overall_sentiment_score``, ``overall_sentiment_label``,
            ``ticker_sentiment`` (list), etc.  Empty list on failure.
        """
        if not self._api_key:
            logger.debug("Alpha Vantage API key not configured; skipping")
            return []

        # Build cache key
        cache_key = f"av_news_{tickers}_{time_from or 'none'}_{time_to or 'none'}"
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached.get("_data", [])

        # Check daily limit
        if not self._check_daily_limit():
            logger.warning("Alpha Vantage daily limit (%d) reached", _DAILY_LIMIT)
            return []

        params: dict = {
            "function": "NEWS_SENTIMENT",
            "tickers": tickers,
            "apikey": self._api_key,
        }
        if time_from:
            params["time_from"] = time_from
        if time_to:
            params["time_to"] = time_to

        url = f"{self._base_url}/query"
        try:
            raw = self._http_get(url, params=params, timeout=20.0)
        except RuntimeError as exc:
            logger.warning("Alpha Vantage request failed: %s", exc)
            return []

        self._increment_daily_count()

        articles = raw.get("feed", [])
        if not isinstance(articles, list):
            articles = []

        # Cache
        self._write_cache(cache_key, {"_data": articles})
        return articles

    # ------------------------------------------------------------------
    # Feature interface
    # ------------------------------------------------------------------

    def get_features(self, ticker: str, as_of_date: date) -> dict[str, float]:
        """Return a flat dict of Alpha Vantage-derived features."""
        features: dict[str, float] = {}
        try:
            articles = self.get_news_sentiment(ticker)
            if articles:
                scores = []
                for a in articles:
                    s = a.get("overall_sentiment_score")
                    if s is not None:
                        try:
                            scores.append(float(s))
                        except (TypeError, ValueError):
                            pass
                if scores:
                    features["av_sentiment_avg"] = float(np.mean(scores))
                    features["av_article_count"] = float(len(scores))
                else:
                    features["av_sentiment_avg"] = np.nan
                    features["av_article_count"] = 0.0
            else:
                features["av_sentiment_avg"] = np.nan
                features["av_article_count"] = 0.0
        except Exception:
            features["av_sentiment_avg"] = np.nan
            features["av_article_count"] = 0.0
        return features


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------
_client_instance: AlphaVantageClient | None = None


def get_alpha_vantage_client() -> AlphaVantageClient:
    """Return the module-level singleton ``AlphaVantageClient``."""
    global _client_instance
    if _client_instance is None:
        _client_instance = AlphaVantageClient()
    return _client_instance
