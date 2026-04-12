"""Centralized data source orchestrator with fallback chains.

Provides a single entry point to fetch news, insider data, institutional
data, and company details from multiple sources with automatic failover.
Also computes meta-features about data quality and cross-source agreement.

Usage::

    from shared.data.source_manager import get_source_manager
    sm = get_source_manager()
    features = sm.get_all_features("AAPL", date.today())
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class SourceManager:
    """Centralized data source orchestrator with fallback chains."""

    _instance = None

    def __init__(self) -> None:
        # Lazy-loaded client references (avoid import errors if deps missing)
        self._finnhub = None
        self._polygon = None
        self._sec = None
        self._finnhub_available: bool | None = None
        self._polygon_available: bool | None = None
        self._sec_available: bool | None = None

    # ------------------------------------------------------------------
    # Client accessors (lazy init)
    # ------------------------------------------------------------------

    def _get_finnhub(self):
        if self._finnhub_available is False:
            return None
        try:
            from shared.data.finnhub_client import get_finnhub_client
            client = get_finnhub_client()
            self._finnhub_available = True
            self._finnhub = client
            return client
        except Exception:
            self._finnhub_available = False
            return None

    def _get_polygon(self):
        if self._polygon_available is False:
            return None
        try:
            from shared.data.polygon_client import get_polygon_client
            client = get_polygon_client()
            # Polygon needs an API key to work
            if not client._api_key:
                self._polygon_available = False
                return None
            self._polygon_available = True
            self._polygon = client
            return client
        except Exception:
            self._polygon_available = False
            return None

    def _get_sec(self):
        if self._sec_available is False:
            return None
        try:
            from shared.data.sec_client import get_sec_client
            client = get_sec_client()
            self._sec_available = True
            self._sec = client
            return client
        except Exception:
            self._sec_available = False
            return None

    # ------------------------------------------------------------------
    # Fallback chain methods
    # ------------------------------------------------------------------

    def get_news(self, ticker: str, as_of_date: date) -> list[dict]:
        """Finnhub -> Polygon fallback chain for news articles."""
        # Try Finnhub first
        finnhub = self._get_finnhub()
        if finnhub:
            try:
                from_date = str(as_of_date - timedelta(days=7))
                to_date = str(as_of_date)
                news = finnhub.get_company_news(ticker, from_date, to_date)
                if news:
                    return news
            except Exception:
                logger.debug("Finnhub news failed for %s, trying Polygon", ticker)

        # Fallback to Polygon
        polygon = self._get_polygon()
        if polygon:
            try:
                news = polygon.get_ticker_news(
                    ticker,
                    published_utc_gte=str(as_of_date - timedelta(days=7)),
                    published_utc_lte=str(as_of_date),
                    limit=50,
                )
                if news:
                    return news
            except Exception:
                logger.debug("Polygon news also failed for %s", ticker)

        return []

    def get_insider_data(self, ticker: str, as_of_date: date) -> dict:
        """Finnhub -> SEC EDGAR fallback for insider trading data.

        Returns a dict with ``transactions`` (list) and ``sentiment`` (dict).
        """
        result: dict[str, Any] = {"transactions": [], "sentiment": {}}

        # Try Finnhub first
        finnhub = self._get_finnhub()
        if finnhub:
            try:
                txns = finnhub.get_insider_transactions(ticker)
                if txns:
                    result["transactions"] = txns
                    result["source"] = "finnhub"
                    sent = finnhub.get_insider_sentiment(ticker)
                    if sent:
                        result["sentiment"] = sent
                    return result
            except Exception:
                logger.debug("Finnhub insider data failed for %s, trying SEC", ticker)

        # Fallback to SEC EDGAR
        sec = self._get_sec()
        if sec:
            try:
                filings = sec.get_insider_filings(ticker, days=90)
                if filings:
                    result["transactions"] = filings
                    result["source"] = "sec"
                    return result
            except Exception:
                logger.debug("SEC insider data also failed for %s", ticker)

        return result

    def get_institutional_data(self, ticker: str) -> dict:
        """Finnhub -> SEC EDGAR fallback for institutional holdings.

        Returns a dict with ``filings`` (list) and optional ownership info.
        """
        result: dict[str, Any] = {"filings": []}

        # Try Finnhub
        finnhub = self._get_finnhub()
        if finnhub:
            try:
                # Finnhub does not have a dedicated institutional endpoint
                # in the free tier, so we fall through to SEC
                pass
            except Exception:
                pass

        # SEC EDGAR 13F filings
        sec = self._get_sec()
        if sec:
            try:
                filings = sec.get_institutional_filings(ticker)
                if filings:
                    result["filings"] = filings
                    result["source"] = "sec"
                    return result
            except Exception:
                logger.debug("SEC institutional data failed for %s", ticker)

        return result

    def get_company_details(self, ticker: str) -> dict:
        """yfinance -> Polygon fallback for company details."""
        # Try yfinance first
        try:
            import yfinance as yf
            yf_ticker = yf.Ticker(ticker)
            info = yf_ticker.info
            if info and info.get("shortName"):
                return {
                    "name": info.get("shortName", ""),
                    "sector": info.get("sector", ""),
                    "industry": info.get("industry", ""),
                    "market_cap": info.get("marketCap"),
                    "employees": info.get("fullTimeEmployees"),
                    "source": "yfinance",
                }
        except Exception:
            logger.debug("yfinance details failed for %s, trying Polygon", ticker)

        # Fallback to Polygon
        polygon = self._get_polygon()
        if polygon:
            try:
                details = polygon.get_ticker_details(ticker)
                if details and details.get("name"):
                    return {
                        "name": details.get("name", ""),
                        "sector": details.get("sic_description", ""),
                        "industry": details.get("sic_description", ""),
                        "market_cap": details.get("market_cap"),
                        "employees": details.get("total_employees"),
                        "source": "polygon",
                    }
            except Exception:
                logger.debug("Polygon details also failed for %s", ticker)

        return {}

    # ------------------------------------------------------------------
    # Peer / related companies
    # ------------------------------------------------------------------

    def get_peers(self, ticker: str) -> list[str]:
        """Get related/peer ticker symbols.

        Uses Polygon related-companies endpoint, falls back to yfinance
        sector-based peer lookup.
        """
        polygon = self._get_polygon()
        if polygon:
            try:
                peers = polygon.get_related_companies(ticker)
                if peers:
                    return peers[:10]
            except Exception:
                pass

        # yfinance fallback -- not a direct peer API, return empty
        return []

    # ------------------------------------------------------------------
    # Sector rotation score
    # ------------------------------------------------------------------

    def _compute_sector_rotation_score(self, as_of_date: date) -> float:
        """Sector ETF momentum vs SPY.

        Computes the average 5d return spread of sector ETFs vs SPY.
        Positive = risk-on rotation, negative = risk-off.
        """
        try:
            import yfinance as yf

            sector_etfs = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU"]
            end = str(as_of_date)
            start = str(as_of_date - timedelta(days=30))

            spy = yf.download("SPY", start=start, end=end, progress=False)
            if isinstance(spy.columns, __import__("pandas").MultiIndex):
                spy.columns = spy.columns.get_level_values(0)
            if spy.empty or len(spy) < 6:
                return np.nan

            spy_ret_5d = float((spy["Close"].iloc[-1] - spy["Close"].iloc[-6]) / spy["Close"].iloc[-6])

            spreads: list[float] = []
            for etf in sector_etfs:
                try:
                    data = yf.download(etf, start=start, end=end, progress=False)
                    if isinstance(data.columns, __import__("pandas").MultiIndex):
                        data.columns = data.columns.get_level_values(0)
                    if not data.empty and len(data) >= 6:
                        etf_ret = float(
                            (data["Close"].iloc[-1] - data["Close"].iloc[-6]) / data["Close"].iloc[-6]
                        )
                        spreads.append(etf_ret - spy_ret_5d)
                except Exception:
                    continue

            if spreads:
                return float(np.std(spreads))
            return np.nan
        except Exception:
            return np.nan

    # ------------------------------------------------------------------
    # Peer relative performance
    # ------------------------------------------------------------------

    def _compute_peer_relative_perf(self, ticker: str, as_of_date: date) -> float:
        """Ticker's 5d return minus average peer 5d return."""
        try:
            import yfinance as yf

            peers = self.get_peers(ticker)
            if not peers:
                return np.nan

            end = str(as_of_date)
            start = str(as_of_date - timedelta(days=30))

            ticker_data = yf.download(ticker, start=start, end=end, progress=False)
            if isinstance(ticker_data.columns, __import__("pandas").MultiIndex):
                ticker_data.columns = ticker_data.columns.get_level_values(0)
            if ticker_data.empty or len(ticker_data) < 6:
                return np.nan

            ticker_ret = float(
                (ticker_data["Close"].iloc[-1] - ticker_data["Close"].iloc[-6])
                / ticker_data["Close"].iloc[-6]
            )

            peer_rets: list[float] = []
            for peer in peers[:5]:  # limit to 5 peers for speed
                try:
                    p_data = yf.download(peer, start=start, end=end, progress=False)
                    if isinstance(p_data.columns, __import__("pandas").MultiIndex):
                        p_data.columns = p_data.columns.get_level_values(0)
                    if not p_data.empty and len(p_data) >= 6:
                        p_ret = float(
                            (p_data["Close"].iloc[-1] - p_data["Close"].iloc[-6])
                            / p_data["Close"].iloc[-6]
                        )
                        peer_rets.append(p_ret)
                except Exception:
                    continue

            if peer_rets:
                return float(ticker_ret - np.mean(peer_rets))
            return np.nan
        except Exception:
            return np.nan

    # ------------------------------------------------------------------
    # Data quality meta-features
    # ------------------------------------------------------------------

    def _compute_data_quality_meta(
        self,
        ticker: str,
        as_of_date: date,
        features: dict[str, float],
    ) -> dict[str, float]:
        """Compute meta-features about data quality across sources."""
        meta: dict[str, float] = {}

        # data_source_count: how many sources returned data
        source_count = 0
        if self._finnhub_available:
            source_count += 1
        if self._polygon_available:
            source_count += 1
        if self._sec_available:
            source_count += 1
        meta["data_source_count"] = float(source_count)

        # data_freshness_hours: best-case freshness
        meta["data_freshness_hours"] = 0.0  # we just fetched

        # primary_source_available: 1 if Finnhub (primary for most chains) responded
        meta["primary_source_available"] = float(self._finnhub_available is True)

        # cross_source_agreement: compare insider data from Finnhub vs SEC
        try:
            agreement = self._compute_cross_source_agreement(ticker)
            meta["cross_source_agreement"] = agreement
        except Exception:
            meta["cross_source_agreement"] = np.nan

        # data_completeness_score: fraction of features that are non-NaN
        total = len(features)
        if total > 0:
            non_nan = sum(
                1 for v in features.values()
                if v is not None and not (isinstance(v, float) and np.isnan(v))
            )
            meta["data_completeness_score"] = float(non_nan / total)
        else:
            meta["data_completeness_score"] = 0.0

        return meta

    def _compute_cross_source_agreement(self, ticker: str) -> float:
        """Compare insider data counts from Finnhub vs SEC (0-1 agreement)."""
        finnhub_count = 0
        sec_count = 0

        finnhub = self._get_finnhub()
        if finnhub:
            try:
                txns = finnhub.get_insider_transactions(ticker)
                finnhub_count = len(txns) if txns else 0
            except Exception:
                pass

        sec = self._get_sec()
        if sec:
            try:
                filings = sec.get_insider_filings(ticker, days=90)
                sec_count = len(filings) if filings else 0
            except Exception:
                pass

        if finnhub_count == 0 and sec_count == 0:
            return 1.0  # both agree: no data
        if finnhub_count == 0 or sec_count == 0:
            return 0.0  # one has data, the other doesn't

        # Ratio-based agreement (1.0 = perfect match)
        ratio = min(finnhub_count, sec_count) / max(finnhub_count, sec_count)
        return float(round(ratio, 4))

    # ------------------------------------------------------------------
    # Main feature aggregator
    # ------------------------------------------------------------------

    def get_all_features(self, ticker: str, as_of_date: date) -> dict[str, float]:
        """Compute all source-manager features for *ticker*.

        Returns a flat dict of ~20-25 features spanning:
        - SEC filing features (4)
        - Finnhub social/news features (2)
        - Peer/sector features (2)
        - Data quality meta-features (5)
        - Additional Polygon-derived features as available
        """
        features: dict[str, float] = {}

        # SEC features
        sec = self._get_sec()
        if sec:
            try:
                sec_feats = sec.get_features(ticker, as_of_date)
                features.update(sec_feats)
            except Exception:
                logger.debug("SEC features failed for %s", ticker)

        # Finnhub social features
        finnhub = self._get_finnhub()
        if finnhub:
            try:
                fh_feats = finnhub.get_features(ticker, as_of_date)
                features.update(fh_feats)
            except Exception:
                logger.debug("Finnhub features failed for %s", ticker)

        # Polygon features
        polygon = self._get_polygon()
        if polygon:
            try:
                pg_feats = polygon.get_features(ticker, as_of_date)
                features.update(pg_feats)
            except Exception:
                logger.debug("Polygon features failed for %s", ticker)

        # Peer relative performance
        try:
            features["peer_relative_perf_5d"] = self._compute_peer_relative_perf(
                ticker, as_of_date
            )
        except Exception:
            features["peer_relative_perf_5d"] = np.nan

        # Sector rotation score
        try:
            features["sector_rotation_score"] = self._compute_sector_rotation_score(
                as_of_date
            )
        except Exception:
            features["sector_rotation_score"] = np.nan

        # Set defaults for any expected features not yet populated
        _expected_sec = [
            "sec_filing_count_90d", "sec_filing_recency_days",
            "sec_form4_count_90d", "sec_13f_count_qtr",
        ]
        _expected_social = [
            "finnhub_social_sentiment", "reddit_mentions_24h",
        ]
        for key in _expected_sec + _expected_social:
            features.setdefault(key, np.nan)
        features.setdefault("peer_relative_perf_5d", np.nan)
        features.setdefault("sector_rotation_score", np.nan)

        # Data quality meta-features (computed last, using the features dict)
        meta = self._compute_data_quality_meta(ticker, as_of_date, features)
        features.update(meta)

        return features


# ------------------------------------------------------------------
# Module-level singleton accessor
# ------------------------------------------------------------------
_manager_instance: SourceManager | None = None


def get_source_manager() -> SourceManager:
    """Return the module-level singleton ``SourceManager``."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = SourceManager()
    return _manager_instance
