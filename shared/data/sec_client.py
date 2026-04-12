"""SEC EDGAR API client with disk caching and rate limiting.

Provides company filings, CIK lookups, insider (Form 4) filings, and
institutional (13F) filing counts for the data expansion enrichment pipeline.

SEC EDGAR is free and requires no API key, but mandates a descriptive
``User-Agent`` header (set via ``SEC_USER_AGENT`` env var).

Docs: https://www.sec.gov/edgar/sec-api-documentation
Fair-use rate limit: max 10 requests/second (600/minute).
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta

import numpy as np

from shared.data.base_client import BaseDataClient

logger = logging.getLogger(__name__)

_CACHE_DIR = "/tmp/phoenix_sec_cache"
_DEFAULT_TTL_HOURS = 24.0
# CIK mappings are stable -- cache for 30 days
_CIK_TTL_HOURS = 24.0 * 30


class SECClient(BaseDataClient):
    """Sync HTTP client for SEC EDGAR endpoints."""

    _instance = None

    def __init__(self) -> None:
        self._user_agent = os.getenv(
            "SEC_USER_AGENT",
            "Phoenix Trading Bot contact@example.com",
        )
        super().__init__(
            name="sec",
            api_key_env="",  # no API key needed
            cache_dir=_CACHE_DIR,
            cache_ttl_hours=_DEFAULT_TTL_HOURS,
            base_url="https://data.sec.gov",
            requests_per_minute=600,  # 10/sec = 600/min
        )
        # SEC does not need an API key; mark as always available
        self._api_key = "__sec_no_key__"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sec_get(self, path: str, cache_key: str | None = None,
                 ttl_hours: float | None = None) -> dict | list:
        """HTTP GET with SEC-mandated ``User-Agent`` and disk cache."""
        ttl_seconds = ttl_hours * 3600 if ttl_hours is not None else None

        if cache_key:
            cached = self._read_cache(cache_key, ttl_seconds=ttl_seconds)
            if cached is not None:
                return cached.get("_data", cached)

        url = f"{self._base_url}{path}"
        headers = {"User-Agent": self._user_agent}

        try:
            raw = self._http_get(url, headers=headers, timeout=15.0)
        except RuntimeError as exc:
            logger.warning("SEC request failed for %s: %s", path, exc)
            return {}

        if cache_key:
            data_to_cache = {"_data": raw} if isinstance(raw, list) else raw
            self._write_cache(cache_key, data_to_cache)

        return raw

    def _get_cik_mapping(self) -> dict[str, str]:
        """Fetch the full ticker-to-CIK mapping from SEC.

        SEC provides ``company_tickers.json`` which maps every
        registered ticker to its CIK number.  Cached for 30 days.
        """
        cache_key = "cik_mapping_full"
        cached = self._read_cache(cache_key, ttl_seconds=_CIK_TTL_HOURS * 3600)
        if cached is not None:
            return cached

        url = "https://www.sec.gov/files/company_tickers.json"
        headers = {"User-Agent": self._user_agent}

        try:
            raw = self._http_get(url, headers=headers, timeout=30.0)
        except RuntimeError as exc:
            logger.warning("SEC CIK mapping fetch failed: %s", exc)
            return {}

        # raw is {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
        mapping: dict[str, str] = {}
        if isinstance(raw, dict):
            for entry in raw.values():
                if isinstance(entry, dict):
                    tick = str(entry.get("ticker", "")).upper()
                    cik = str(entry.get("cik_str", ""))
                    if tick and cik:
                        mapping[tick] = cik.zfill(10)
            self._write_cache(cache_key, mapping)

        return mapping

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_cik(self, ticker: str) -> str:
        """Look up the 10-digit zero-padded CIK for *ticker*.

        Returns empty string if not found.
        """
        mapping = self._get_cik_mapping()
        return mapping.get(ticker.upper(), "")

    def get_company_filings(
        self,
        ticker: str,
        form_type: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Fetch recent SEC filings for *ticker*.

        Parameters
        ----------
        ticker : str
            Stock symbol.
        form_type : str | None
            Filter by form type (e.g. ``"10-K"``, ``"4"``, ``"13F-HR"``).
        limit : int
            Max filings to return.

        Returns
        -------
        list[dict]
            Each dict has ``form``, ``filingDate``, ``primaryDocument``, etc.
        """
        cik = self.get_cik(ticker)
        if not cik:
            logger.warning("No CIK found for ticker %s", ticker)
            return []

        cache_key = f"filings_{ticker}_{form_type}_{limit}"
        result = self._sec_get(
            f"/submissions/CIK{cik}.json",
            cache_key=cache_key,
            ttl_hours=_DEFAULT_TTL_HOURS,
        )
        if not isinstance(result, dict):
            return []

        recent = result.get("filings", {}).get("recent", {})
        if not recent:
            return []

        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])
        accession_numbers = recent.get("accessionNumber", [])

        filings: list[dict] = []
        n = min(len(forms), len(filing_dates))
        for i in range(n):
            entry = {
                "form": forms[i] if i < len(forms) else "",
                "filingDate": filing_dates[i] if i < len(filing_dates) else "",
                "primaryDocument": primary_docs[i] if i < len(primary_docs) else "",
                "accessionNumber": accession_numbers[i] if i < len(accession_numbers) else "",
            }
            if form_type and entry["form"] != form_type:
                continue
            filings.append(entry)
            if len(filings) >= limit:
                break

        return filings

    def get_insider_filings(self, ticker: str, days: int = 90,
                            as_of_date: date | None = None) -> list[dict]:
        """Return Form 4 (insider transaction) filings from the last *days*.

        These are filings by officers, directors, and 10% owners.
        """
        all_filings = self.get_company_filings(ticker, form_type="4", limit=200)
        if not all_filings:
            return []

        cutoff = (as_of_date or date.today()) - timedelta(days=days)
        result: list[dict] = []
        for f in all_filings:
            try:
                fd = date.fromisoformat(f.get("filingDate", ""))
                if fd >= cutoff:
                    result.append(f)
            except (ValueError, TypeError):
                continue
        return result

    def get_institutional_filings(self, ticker: str) -> list[dict]:
        """Return 13F-HR (institutional holdings) filings.

        13F filings are filed quarterly; returns all available from the
        submissions endpoint.
        """
        return self.get_company_filings(ticker, form_type="13F-HR", limit=20)

    # ------------------------------------------------------------------
    # Feature interface (required by BaseDataClient)
    # ------------------------------------------------------------------

    def get_features(self, ticker: str, as_of_date: date) -> dict[str, float]:
        """Return a flat dict of SEC-derived features."""
        features: dict[str, float] = {}

        try:
            # All filings in last 90 days
            all_filings = self.get_company_filings(ticker, limit=200)
            cutoff_90d = as_of_date - timedelta(days=90)
            recent_filings = [
                f for f in all_filings
                if _parse_filing_date(f.get("filingDate", ""), cutoff_90d) >= cutoff_90d
            ]
            features["sec_filing_count_90d"] = float(len(recent_filings))

            # Recency: days since last filing
            if all_filings:
                try:
                    last_date = date.fromisoformat(all_filings[0].get("filingDate", ""))
                    features["sec_filing_recency_days"] = float((as_of_date - last_date).days)
                except (ValueError, TypeError):
                    features["sec_filing_recency_days"] = np.nan
            else:
                features["sec_filing_recency_days"] = np.nan
        except Exception:
            features["sec_filing_count_90d"] = np.nan
            features["sec_filing_recency_days"] = np.nan

        try:
            insider = self.get_insider_filings(ticker, days=90, as_of_date=as_of_date)
            features["sec_form4_count_90d"] = float(len(insider))
        except Exception:
            features["sec_form4_count_90d"] = np.nan

        try:
            institutional = self.get_institutional_filings(ticker)
            # Count filings in the current quarter
            q_start = date(as_of_date.year, ((as_of_date.month - 1) // 3) * 3 + 1, 1)
            qtr_filings = [
                f for f in institutional
                if _parse_filing_date(f.get("filingDate", ""), q_start) >= q_start
            ]
            features["sec_13f_count_qtr"] = float(len(qtr_filings))
        except Exception:
            features["sec_13f_count_qtr"] = np.nan

        return features


def _parse_filing_date(date_str: str, default: date) -> date:
    """Parse a YYYY-MM-DD date string, returning *default* on failure."""
    try:
        return date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return default


# ------------------------------------------------------------------
# Module-level singleton accessor
# ------------------------------------------------------------------
_client_instance: SECClient | None = None


def get_sec_client() -> SECClient:
    """Return the module-level singleton ``SECClient``."""
    global _client_instance
    if _client_instance is None:
        _client_instance = SECClient()
    return _client_instance
