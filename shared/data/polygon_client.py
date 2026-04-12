"""Polygon.io API client with disk caching and rate limiting.

Provides news, ticker details, related companies, splits, and dividends
for the data expansion enrichment pipeline.

API docs: https://polygon.io/docs
Free tier: 5 requests/minute. API key passed as ``apiKey`` query param.

Requires: POLYGON_API_KEY environment variable.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np

from shared.data.base_client import BaseDataClient

logger = logging.getLogger(__name__)

_CACHE_DIR = "/tmp/phoenix_polygon_cache"
_NEWS_TTL_HOURS = 1.0
_REFERENCE_TTL_HOURS = 6.0


class PolygonClient(BaseDataClient):
    """Sync HTTP client for Polygon.io API endpoints."""

    _instance = None

    def __init__(self, api_key: str | None = None):
        super().__init__(
            name="polygon",
            api_key_env="POLYGON_API_KEY",
            cache_dir=_CACHE_DIR,
            cache_ttl_hours=_REFERENCE_TTL_HOURS,
            base_url="https://api.polygon.io",
            requests_per_minute=5,
        )
        if api_key:
            self._api_key = api_key

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _polygon_get(self, path: str, params: dict | None = None,
                     cache_key: str | None = None,
                     ttl_hours: float | None = None) -> dict | list:
        """Perform an authenticated GET and return parsed JSON.

        Auth is via ``apiKey`` query param.  Uses disk cache with a
        configurable TTL.  Returns ``{}`` or ``[]`` on any failure.
        """
        if not self._api_key:
            logger.debug("Polygon API key not configured; skipping %s", path)
            return {}

        ttl_seconds = ttl_hours * 3600 if ttl_hours is not None else None

        # Check cache
        if cache_key:
            cached = self._read_cache(cache_key, ttl_seconds=ttl_seconds)
            if cached is not None:
                return cached.get("_data", cached)

        url = f"{self._base_url}{path}"
        merged_params = {"apiKey": self._api_key}
        if params:
            merged_params.update(params)

        try:
            raw = self._http_get(url, params=merged_params, timeout=15.0)
        except RuntimeError as exc:
            logger.warning("Polygon request failed for %s: %s", path, exc)
            return {}

        # Cache the result
        if cache_key:
            data_to_cache = {"_data": raw} if isinstance(raw, list) else raw
            self._write_cache(cache_key, data_to_cache)

        return raw

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_ticker_news(
        self,
        ticker: str,
        published_utc_gte: str | None = None,
        published_utc_lte: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """GET /v2/reference/news -- news articles for *ticker*.

        Parameters
        ----------
        ticker : str
            Stock symbol, e.g. ``"AAPL"``.
        published_utc_gte : str | None
            Filter articles published on or after this date (``YYYY-MM-DD``).
        published_utc_lte : str | None
            Filter articles published on or before this date (``YYYY-MM-DD``).
        limit : int
            Max number of articles to return.

        Returns
        -------
        list[dict]
            Each dict contains ``title``, ``author``, ``published_utc``,
            ``article_url``, ``tickers``, etc.  Empty list on failure.
        """
        params: dict = {"ticker": ticker, "limit": limit, "order": "desc"}
        if published_utc_gte:
            params["published_utc.gte"] = published_utc_gte
        if published_utc_lte:
            params["published_utc.lte"] = published_utc_lte

        cache_key = f"news_{ticker}_{published_utc_gte}_{published_utc_lte}_{limit}"
        result = self._polygon_get(
            "/v2/reference/news",
            params=params,
            cache_key=cache_key,
            ttl_hours=_NEWS_TTL_HOURS,
        )
        if isinstance(result, dict):
            return result.get("results", [])
        return result if isinstance(result, list) else []

    def get_ticker_details(self, ticker: str) -> dict:
        """GET /v3/reference/tickers/{ticker} -- company details.

        Returns dict with ``name``, ``market_cap``, ``sic_code``,
        ``total_employees``, etc.  Empty dict on failure.
        """
        cache_key = f"ticker_details_{ticker}"
        result = self._polygon_get(
            f"/v3/reference/tickers/{ticker}",
            cache_key=cache_key,
            ttl_hours=_REFERENCE_TTL_HOURS,
        )
        if isinstance(result, dict):
            return result.get("results", result)
        return {}

    def get_related_companies(self, ticker: str) -> list[str]:
        """GET /v1/related-companies/{ticker} -- peer/related tickers.

        Returns list of related ticker symbols.  Empty list on failure.
        """
        cache_key = f"related_{ticker}"
        result = self._polygon_get(
            f"/v1/related-companies/{ticker}",
            cache_key=cache_key,
            ttl_hours=_REFERENCE_TTL_HOURS,
        )
        if isinstance(result, dict):
            results = result.get("results", [])
            return [r.get("ticker", "") for r in results if isinstance(r, dict) and r.get("ticker")]
        return []

    def get_stock_splits(self, ticker: str) -> list[dict]:
        """GET /v3/reference/splits -- stock split history.

        Returns list of split records with ``execution_date``,
        ``split_from``, ``split_to``.  Empty list on failure.
        """
        cache_key = f"splits_{ticker}"
        result = self._polygon_get(
            "/v3/reference/splits",
            params={"ticker": ticker},
            cache_key=cache_key,
            ttl_hours=_REFERENCE_TTL_HOURS,
        )
        if isinstance(result, dict):
            return result.get("results", [])
        return result if isinstance(result, list) else []

    def get_dividends(self, ticker: str) -> list[dict]:
        """GET /v3/reference/dividends -- dividend history.

        Returns list of dividend records with ``ex_dividend_date``,
        ``cash_amount``, ``frequency``.  Empty list on failure.
        """
        cache_key = f"dividends_{ticker}"
        result = self._polygon_get(
            "/v3/reference/dividends",
            params={"ticker": ticker},
            cache_key=cache_key,
            ttl_hours=_REFERENCE_TTL_HOURS,
        )
        if isinstance(result, dict):
            return result.get("results", [])
        return result if isinstance(result, list) else []

    # ------------------------------------------------------------------
    # Feature interface (required by BaseDataClient)
    # ------------------------------------------------------------------

    def get_features(self, ticker: str, as_of_date: date) -> dict[str, float]:
        """Return a flat dict of Polygon-derived features.

        Currently provides peer-count and recent news/split/dividend counts.
        """
        features: dict[str, float] = {}

        try:
            related = self.get_related_companies(ticker)
            features["polygon_peer_count"] = float(len(related))
        except Exception:
            features["polygon_peer_count"] = np.nan

        try:
            news = self.get_ticker_news(
                ticker,
                published_utc_gte=str(as_of_date),
                limit=50,
            )
            features["polygon_news_count_today"] = float(len(news))
        except Exception:
            features["polygon_news_count_today"] = np.nan

        try:
            details = self.get_ticker_details(ticker)
            features["polygon_market_cap"] = self._safe_float(details.get("market_cap"))
            features["polygon_total_employees"] = self._safe_float(details.get("total_employees"))
        except Exception:
            features["polygon_market_cap"] = np.nan
            features["polygon_total_employees"] = np.nan

        return features


# ------------------------------------------------------------------
# Module-level singleton accessor
# ------------------------------------------------------------------
_client_instance: PolygonClient | None = None


def get_polygon_client() -> PolygonClient:
    """Return the module-level singleton ``PolygonClient``."""
    global _client_instance
    if _client_instance is None:
        _client_instance = PolygonClient()
    return _client_instance
