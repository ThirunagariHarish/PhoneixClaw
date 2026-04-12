"""Finnhub API client with disk caching and rate limiting.

Provides news, sentiment, insider, earnings, recommendations, and social data
for the news sentiment and company events enrichment pipelines.

API docs: https://finnhub.io/docs/api
Free tier: 60 requests/minute. API key passed as ``token`` query param.

Requires: FINNHUB_API_KEY environment variable.
"""

from __future__ import annotations

import logging
from datetime import date

from shared.data.base_client import BaseDataClient

logger = logging.getLogger(__name__)

_CACHE_DIR = "/tmp/phoenix_finnhub_cache"

# TTLs in hours
_NEWS_TTL_HOURS = 1.0
_DEFAULT_TTL_HOURS = 6.0


class FinnhubClient(BaseDataClient):
    """Sync HTTP client for Finnhub API endpoints."""

    _instance = None

    def __init__(self, api_key: str | None = None):
        super().__init__(
            name="finnhub",
            api_key_env="FINNHUB_API_KEY",
            cache_dir=_CACHE_DIR,
            cache_ttl_hours=_DEFAULT_TTL_HOURS,
            base_url="https://finnhub.io/api/v1",
            requests_per_minute=60,
        )
        if api_key:
            self._api_key = api_key

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict | None = None,
             cache_key: str | None = None,
             ttl_hours: float | None = None) -> dict | list:
        """Perform an authenticated GET and return parsed JSON.

        Uses disk cache with a configurable TTL.  Returns ``{}`` or ``[]``
        on any failure -- never raises.
        """
        if not self._api_key:
            logger.debug("Finnhub API key not configured; skipping %s", path)
            return {}

        ttl_seconds = ttl_hours * 3600 if ttl_hours is not None else None

        # Check cache
        if cache_key:
            cached = self._read_cache(cache_key, ttl_seconds=ttl_seconds)
            if cached is not None:
                return cached.get("_data", cached)

        url = f"{self._base_url}{path}"
        merged_params = {"token": self._api_key}
        if params:
            merged_params.update(params)

        try:
            raw = self._http_get(url, params=merged_params, timeout=15.0)
        except RuntimeError as exc:
            logger.warning("Finnhub request failed for %s: %s", path, exc)
            return {}

        # Cache the result
        if cache_key:
            data_to_cache = {"_data": raw} if isinstance(raw, list) else raw
            self._write_cache(cache_key, data_to_cache)

        return raw

    def _get_list(self, path: str, params: dict | None = None,
                  cache_key: str | None = None,
                  ttl_hours: float | None = None) -> list[dict]:
        """Like ``_get`` but guarantees a list return."""
        result = self._get(path, params=params, cache_key=cache_key, ttl_hours=ttl_hours)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "_data" in result:
            return result["_data"]
        return []

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_company_news(self, ticker: str, from_date: str, to_date: str) -> list[dict]:
        """GET /api/v1/company-news -- articles for *ticker* in date range.

        Parameters
        ----------
        ticker : str
            Stock symbol, e.g. ``"AAPL"``.
        from_date, to_date : str
            ``YYYY-MM-DD`` formatted dates.

        Returns
        -------
        list[dict]
            Each dict contains ``headline``, ``source``, ``datetime`` (unix),
            ``summary``, ``url``, etc.  Empty list on failure.
        """
        cache_key = f"company_news_{ticker}_{from_date}_{to_date}"
        return self._get_list(
            "/company-news",
            params={"symbol": ticker, "from": from_date, "to": to_date},
            cache_key=cache_key,
            ttl_hours=_NEWS_TTL_HOURS,
        )

    def get_news_sentiment(self, ticker: str) -> dict:
        """GET /api/v1/news-sentiment -- aggregated news sentiment for *ticker*.

        Returns dict with ``buzz``, ``companyNewsScore``, ``sectorAverageBullishPercent``, etc.
        """
        cache_key = f"news_sentiment_{ticker}"
        result = self._get(
            "/news-sentiment",
            params={"symbol": ticker},
            cache_key=cache_key,
            ttl_hours=_NEWS_TTL_HOURS,
        )
        return result if isinstance(result, dict) else {}

    def get_insider_sentiment(self, ticker: str) -> dict:
        """GET /api/v1/stock/insider-sentiment."""
        cache_key = f"insider_sentiment_{ticker}"
        result = self._get(
            "/stock/insider-sentiment",
            params={"symbol": ticker},
            cache_key=cache_key,
        )
        return result if isinstance(result, dict) else {}

    def get_insider_transactions(self, ticker: str) -> list[dict]:
        """GET /api/v1/stock/insider-transactions."""
        cache_key = f"insider_transactions_{ticker}"
        result = self._get(
            "/stock/insider-transactions",
            params={"symbol": ticker},
            cache_key=cache_key,
        )
        if isinstance(result, dict):
            return result.get("data", [])
        return result if isinstance(result, list) else []

    def get_earnings_surprises(self, ticker: str) -> list[dict]:
        """GET /api/v1/stock/earnings -- historical earnings surprises."""
        cache_key = f"earnings_{ticker}"
        return self._get_list(
            "/stock/earnings",
            params={"symbol": ticker},
            cache_key=cache_key,
        )

    def get_recommendation_trends(self, ticker: str) -> list[dict]:
        """GET /api/v1/stock/recommendation -- analyst recommendation trends."""
        cache_key = f"recommendation_{ticker}"
        return self._get_list(
            "/stock/recommendation",
            params={"symbol": ticker},
            cache_key=cache_key,
        )

    def get_price_target(self, ticker: str) -> dict:
        """GET /api/v1/stock/price-target -- consensus price target."""
        cache_key = f"price_target_{ticker}"
        result = self._get(
            "/stock/price-target",
            params={"symbol": ticker},
            cache_key=cache_key,
        )
        return result if isinstance(result, dict) else {}

    def get_social_sentiment(self, ticker: str) -> dict:
        """GET /api/v1/stock/social-sentiment -- Reddit/Twitter mentions."""
        cache_key = f"social_sentiment_{ticker}"
        result = self._get(
            "/stock/social-sentiment",
            params={"symbol": ticker},
            cache_key=cache_key,
        )
        return result if isinstance(result, dict) else {}

    # ------------------------------------------------------------------
    # Feature interface (required by BaseDataClient)
    # ------------------------------------------------------------------

    def get_features(self, ticker: str, as_of_date: date) -> dict[str, float]:
        """Return a flat dict of Finnhub-derived features.

        This is a convenience aggregator; the news_client module uses the
        individual methods directly for more granular control.
        """
        import numpy as np

        features: dict[str, float] = {}
        try:
            sent = self.get_news_sentiment(ticker)
            features["finnhub_news_score"] = self._safe_float(
                sent.get("companyNewsScore")
            )
            buzz = sent.get("buzz", {})
            features["finnhub_buzz_articles"] = self._safe_float(
                buzz.get("articlesInLastWeek")
            )
            features["finnhub_sector_avg_bullish"] = self._safe_float(
                sent.get("sectorAverageBullishPercent")
            )
        except Exception:
            features.setdefault("finnhub_news_score", np.nan)
            features.setdefault("finnhub_buzz_articles", np.nan)
            features.setdefault("finnhub_sector_avg_bullish", np.nan)

        try:
            social = self.get_social_sentiment(ticker)
            reddit = social.get("reddit", [])
            if reddit:
                latest = reddit[-1] if isinstance(reddit, list) else {}
                features["finnhub_social_sentiment"] = self._safe_float(
                    latest.get("score")
                )
                features["reddit_mentions_24h"] = self._safe_float(
                    latest.get("mention")
                )
            else:
                features["finnhub_social_sentiment"] = np.nan
                features["reddit_mentions_24h"] = np.nan
        except Exception:
            features.setdefault("finnhub_social_sentiment", np.nan)
            features.setdefault("reddit_mentions_24h", np.nan)

        return features


# ------------------------------------------------------------------
# Module-level singleton accessor
# ------------------------------------------------------------------
_client_instance: FinnhubClient | None = None


def get_finnhub_client() -> FinnhubClient:
    """Return the module-level singleton ``FinnhubClient``."""
    global _client_instance
    if _client_instance is None:
        _client_instance = FinnhubClient()
    return _client_instance
