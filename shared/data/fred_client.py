"""FRED (Federal Reserve Economic Data) API client with disk caching.

Provides macro-economic data for both the backtest enrichment pipeline
and the live position monitor's macro_check tool.

Requires: pip install fredapi
Set FRED_API_KEY environment variable (free at https://fred.stlouisfed.org/docs/api/api_key.html).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FRED_SERIES: dict[str, str] = {
    "DGS2": "treasury_2y",
    "DGS10": "treasury_10y",
    "T10Y2Y": "yield_spread_2_10",
    "UNRATE": "unemployment_rate",
    "ICSA": "weekly_jobless_claims",
    "GDPC1": "real_gdp_growth",
    "CPIAUCSL": "cpi_index",
    "PPIACO": "ppi_index",
    "UMCSENT": "consumer_sentiment",
    "VIXCLS": "vix_fred",
}

# FRED release IDs for dynamic event calendar lookup
RELEASE_IDS: dict[str, int] = {
    "fomc": 21,    # FOMC Meetings/Statements
    "cpi": 10,     # Consumer Price Index
    "nfp": 50,     # Employment Situation (NFP)
    "gdp": 53,     # GDP Advance Estimate
    "ppi": 35,     # Producer Price Index
    "ism": 29,     # ISM Manufacturing
}

_CACHE_DIR = Path(os.getenv("FRED_CACHE_DIR", "/tmp/phoenix_fred_cache"))
_CACHE_TTL_HOURS = 12


class FredClient:
    """Wrapper around fredapi with disk caching and graceful degradation."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("FRED_API_KEY", "")
        self._fred = None
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _get_fred(self):
        if self._fred is None:
            if not self._api_key:
                raise ValueError("FRED_API_KEY not set")
            try:
                from fredapi import Fred
                self._fred = Fred(api_key=self._api_key)
            except ImportError:
                raise ImportError("fredapi not installed: pip install fredapi")
        return self._fred

    def _cache_path(self, series_id: str) -> Path:
        return _CACHE_DIR / f"{series_id}.parquet"

    def _is_cache_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
        return age < _CACHE_TTL_HOURS * 3600

    def get_series(
        self,
        series_id: str,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> pd.Series:
        """Fetch a FRED series with disk caching."""
        cache_path = self._cache_path(series_id)

        if self._is_cache_fresh(cache_path):
            try:
                df = pd.read_parquet(cache_path)
                s = df.iloc[:, 0]
                if start:
                    s = s[s.index >= str(start)]
                if end:
                    s = s[s.index <= str(end)]
                return s
            except Exception:
                pass

        try:
            fred = self._get_fred()
            data = fred.get_series(
                series_id,
                observation_start=str(start) if start else None,
                observation_end=str(end) if end else None,
            )
            if data is not None and not data.empty:
                pd.DataFrame(data).to_parquet(cache_path)
            return data if data is not None else pd.Series(dtype=float)
        except Exception as e:
            logger.warning("FRED fetch failed for %s: %s", series_id, e)
            if cache_path.exists():
                try:
                    return pd.read_parquet(cache_path).iloc[:, 0]
                except Exception:
                    pass
            return pd.Series(dtype=float)

    def get_release_dates(self, release_name: str, start_year: int = 2024) -> list[date]:
        """Fetch release dates for a named economic event (e.g. 'fomc', 'cpi')."""
        release_id = RELEASE_IDS.get(release_name)
        if not release_id:
            return []

        cache_path = _CACHE_DIR / f"release_{release_name}.json"
        if self._is_cache_fresh(cache_path):
            try:
                dates = json.loads(cache_path.read_text())
                return [date.fromisoformat(d) for d in dates]
            except Exception:
                pass

        try:
            fred = self._get_fred()
            df = fred.get_release_dates(release_id)
            if df is not None and not df.empty:
                dates_list = sorted(set(
                    d.date() if hasattr(d, "date") else d
                    for d in df.values
                    if hasattr(d, "year") and d.year >= start_year
                ))
                cache_path.write_text(json.dumps([d.isoformat() for d in dates_list]))
                return dates_list
        except Exception as e:
            logger.warning("FRED release dates failed for %s: %s", release_name, e)

        return []

    def get_macro_features(self, as_of_date: date | str) -> dict[str, float]:
        """Compute macro features as of a given date for enrichment."""
        if isinstance(as_of_date, str):
            as_of_date = date.fromisoformat(as_of_date)

        start = as_of_date - timedelta(days=365)
        features: dict[str, float] = {}

        for series_id, feature_name in FRED_SERIES.items():
            try:
                s = self.get_series(series_id, start=start, end=as_of_date)
                if s.empty:
                    features[feature_name] = np.nan
                    continue
                s = s.dropna()
                if s.empty:
                    features[feature_name] = np.nan
                    continue
                features[feature_name] = float(s.iloc[-1])
            except Exception:
                features[feature_name] = np.nan

        # Derived features
        t2y = features.get("treasury_2y", np.nan)
        t10y = features.get("treasury_10y", np.nan)
        if not np.isnan(t2y) and not np.isnan(t10y):
            features["yield_curve_inverted"] = float(t2y > t10y)
        else:
            features["yield_curve_inverted"] = np.nan

        # Yield spread 5d change
        try:
            spread_s = self.get_series("T10Y2Y", start=start, end=as_of_date).dropna()
            if len(spread_s) >= 6:
                features["yield_spread_change_5d"] = float(spread_s.iloc[-1] - spread_s.iloc[-6])
            else:
                features["yield_spread_change_5d"] = np.nan
        except Exception:
            features["yield_spread_change_5d"] = np.nan

        # Jobless claims 4-week average
        try:
            claims = self.get_series("ICSA", start=start, end=as_of_date).dropna()
            if len(claims) >= 4:
                features["jobless_claims_4w_avg"] = float(claims.iloc[-4:].mean())
            else:
                features["jobless_claims_4w_avg"] = np.nan
        except Exception:
            features["jobless_claims_4w_avg"] = np.nan

        # CPI year-over-year change
        try:
            cpi = self.get_series("CPIAUCSL", start=as_of_date - timedelta(days=400), end=as_of_date).dropna()
            if len(cpi) >= 13:
                features["cpi_yoy_change"] = float((cpi.iloc[-1] / cpi.iloc[-13] - 1) * 100)
            else:
                features["cpi_yoy_change"] = np.nan
        except Exception:
            features["cpi_yoy_change"] = np.nan

        # PPI year-over-year change
        try:
            ppi = self.get_series("PPIACO", start=as_of_date - timedelta(days=400), end=as_of_date).dropna()
            if len(ppi) >= 13:
                features["ppi_yoy_change"] = float((ppi.iloc[-1] / ppi.iloc[-13] - 1) * 100)
            else:
                features["ppi_yoy_change"] = np.nan
        except Exception:
            features["ppi_yoy_change"] = np.nan

        # Consumer sentiment change
        try:
            sent = self.get_series("UMCSENT", start=start, end=as_of_date).dropna()
            if len(sent) >= 2:
                features["consumer_sentiment_change"] = float(sent.iloc[-1] - sent.iloc[-2])
            else:
                features["consumer_sentiment_change"] = np.nan
        except Exception:
            features["consumer_sentiment_change"] = np.nan

        # Composite "surprise" proxy when full expectations are unavailable
        parts: list[float] = []
        cpi_y = features.get("cpi_yoy_change", np.nan)
        if not np.isnan(cpi_y):
            parts.append(float(np.clip(cpi_y / 5.0, -1.0, 1.0)))
        ppi_y = features.get("ppi_yoy_change", np.nan)
        if not np.isnan(ppi_y):
            parts.append(float(np.clip(ppi_y / 5.0, -1.0, 1.0)))
        sent_ch = features.get("consumer_sentiment_change", np.nan)
        if not np.isnan(sent_ch):
            parts.append(float(np.clip(sent_ch / 10.0, -1.0, 1.0)))
        spread_ch = features.get("yield_spread_change_5d", np.nan)
        if not np.isnan(spread_ch):
            parts.append(float(np.clip(-spread_ch / 0.5, -1.0, 1.0)))
        if parts:
            features["economic_surprise_composite"] = float(round(float(np.mean(parts)), 4))
        else:
            features["economic_surprise_composite"] = np.nan

        return features

    def get_event_dates(self, event_name: str, as_of_date: date | None = None) -> list[date]:
        """Get dates for a named event, with fallback to static lists."""
        dates = self.get_release_dates(event_name)
        if dates:
            return dates
        return _STATIC_EVENT_DATES.get(event_name, [])


# Static fallback dates (kept from enrich.py for when FRED API is unavailable)
_STATIC_EVENT_DATES: dict[str, list[date]] = {
    "fomc": [date.fromisoformat(d) for d in [
        "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
        "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
        "2025-07-30", "2025-09-17", "2025-11-05", "2025-12-17",
        "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
    ]],
    "cpi": [date.fromisoformat(d) for d in [
        "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10",
        "2024-05-15", "2024-06-12", "2024-07-11", "2024-08-14",
        "2024-09-11", "2024-10-10", "2024-11-13", "2024-12-11",
        "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10",
        "2025-05-13", "2025-06-11", "2025-07-15", "2025-08-12",
        "2025-09-10", "2025-10-14", "2025-11-12", "2025-12-10",
        "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-10",
        "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
        "2026-09-11", "2026-10-13", "2026-11-10", "2026-12-10",
    ]],
    "nfp": [date.fromisoformat(d) for d in [
        "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05",
        "2024-05-03", "2024-06-07", "2024-07-05", "2024-08-02",
        "2024-09-06", "2024-10-04", "2024-11-01", "2024-12-06",
        "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04",
        "2025-05-02", "2025-06-06", "2025-07-03", "2025-08-01",
        "2025-09-05", "2025-10-03", "2025-11-07", "2025-12-05",
        "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
        "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07",
        "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
    ]],
}


_client_instance: FredClient | None = None


def get_fred_client() -> FredClient:
    """Module-level singleton."""
    global _client_instance
    if _client_instance is None:
        _client_instance = FredClient()
    return _client_instance
