"""Unit tests for shared.data.sec_client."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import numpy as np
import pytest

from shared.data.sec_client import SECClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton between tests."""
    import shared.data.sec_client as mod
    mod._client_instance = None
    yield
    mod._client_instance = None


@pytest.fixture()
def client(tmp_path):
    """Return a SECClient with a temporary cache dir."""
    c = SECClient()
    c._cache_dir = tmp_path / "sec_cache"
    c._cache_dir.mkdir(parents=True, exist_ok=True)
    return c


# Reusable mock data
CIK_MAPPING_RESPONSE = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp."},
}

SUBMISSIONS_RESPONSE = {
    "cik": "0000320193",
    "name": "Apple Inc.",
    "filings": {
        "recent": {
            "form": ["10-K", "4", "4", "13F-HR", "8-K", "4"],
            "filingDate": [
                "2026-03-15", "2026-03-10", "2026-02-20",
                "2026-02-15", "2026-01-10", "2025-12-01",
            ],
            "primaryDocument": ["doc1", "doc2", "doc3", "doc4", "doc5", "doc6"],
            "accessionNumber": ["acc1", "acc2", "acc3", "acc4", "acc5", "acc6"],
        }
    },
}


# ---------------------------------------------------------------------------
# Test: CIK lookup
# ---------------------------------------------------------------------------

class TestGetCik:
    def test_returns_zero_padded_cik(self, client):
        with patch.object(client, "_http_get", return_value=CIK_MAPPING_RESPONSE):
            cik = client.get_cik("AAPL")
            assert cik == "0000320193"

    def test_returns_empty_for_unknown_ticker(self, client):
        with patch.object(client, "_http_get", return_value=CIK_MAPPING_RESPONSE):
            cik = client.get_cik("UNKNOWN_TICKER_XYZ")
            assert cik == ""

    def test_caches_cik_mapping(self, client):
        call_count = 0

        def counting_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return CIK_MAPPING_RESPONSE

        with patch.object(client, "_http_get", side_effect=counting_get):
            client.get_cik("AAPL")
            client.get_cik("MSFT")
            # Second call should use cached mapping
            assert call_count == 1

    def test_returns_empty_on_http_failure(self, client):
        with patch.object(client, "_http_get", side_effect=RuntimeError("err")):
            cik = client.get_cik("AAPL")
            assert cik == ""


# ---------------------------------------------------------------------------
# Test: get_company_filings
# ---------------------------------------------------------------------------

class TestGetCompanyFilings:
    def test_returns_all_filings_when_no_filter(self, client):
        def mock_get(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "company_tickers" in url:
                return CIK_MAPPING_RESPONSE
            return SUBMISSIONS_RESPONSE

        with patch.object(client, "_http_get", side_effect=mock_get):
            filings = client.get_company_filings("AAPL", limit=10)
            assert len(filings) == 6
            assert filings[0]["form"] == "10-K"

    def test_filters_by_form_type(self, client):
        def mock_get(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "company_tickers" in url:
                return CIK_MAPPING_RESPONSE
            return SUBMISSIONS_RESPONSE

        with patch.object(client, "_http_get", side_effect=mock_get):
            filings = client.get_company_filings("AAPL", form_type="4")
            assert all(f["form"] == "4" for f in filings)
            assert len(filings) == 3

    def test_returns_empty_for_unknown_ticker(self, client):
        with patch.object(client, "_http_get", return_value=CIK_MAPPING_RESPONSE):
            filings = client.get_company_filings("UNKNOWN_TICKER_XYZ")
            assert filings == []

    def test_respects_limit(self, client):
        def mock_get(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "company_tickers" in url:
                return CIK_MAPPING_RESPONSE
            return SUBMISSIONS_RESPONSE

        with patch.object(client, "_http_get", side_effect=mock_get):
            filings = client.get_company_filings("AAPL", limit=2)
            assert len(filings) == 2


# ---------------------------------------------------------------------------
# Test: get_insider_filings
# ---------------------------------------------------------------------------

class TestGetInsiderFilings:
    def test_filters_form4_within_days(self, client):
        def mock_get(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "company_tickers" in url:
                return CIK_MAPPING_RESPONSE
            return SUBMISSIONS_RESPONSE

        with patch.object(client, "_http_get", side_effect=mock_get):
            # With today patched to 2026-04-11
            with patch("shared.data.sec_client.date") as mock_date:
                mock_date.today.return_value = date(2026, 4, 11)
                mock_date.fromisoformat = date.fromisoformat
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                filings = client.get_insider_filings("AAPL", days=90)
                # Form 4 filings within 90 days of 2026-04-11:
                # 2026-03-10, 2026-02-20 are within 90d; 2025-12-01 is NOT
                assert all(f["form"] == "4" for f in filings)
                assert len(filings) >= 1


# ---------------------------------------------------------------------------
# Test: get_institutional_filings
# ---------------------------------------------------------------------------

class TestGetInstitutionalFilings:
    def test_returns_13f_filings(self, client):
        def mock_get(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "company_tickers" in url:
                return CIK_MAPPING_RESPONSE
            return SUBMISSIONS_RESPONSE

        with patch.object(client, "_http_get", side_effect=mock_get):
            filings = client.get_institutional_filings("AAPL")
            assert all(f["form"] == "13F-HR" for f in filings)
            assert len(filings) == 1


# ---------------------------------------------------------------------------
# Test: rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_rate_limit_configured_for_sec(self, client):
        # SEC: 10 req/sec = 600/min
        assert client._requests_per_minute == 600


# ---------------------------------------------------------------------------
# Test: get_features
# ---------------------------------------------------------------------------

class TestGetFeatures:
    def test_returns_all_expected_features(self, client):
        def mock_get(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "company_tickers" in url:
                return CIK_MAPPING_RESPONSE
            return SUBMISSIONS_RESPONSE

        with patch.object(client, "_http_get", side_effect=mock_get):
            features = client.get_features("AAPL", date(2026, 4, 11))
            assert "sec_filing_count_90d" in features
            assert "sec_filing_recency_days" in features
            assert "sec_form4_count_90d" in features
            assert "sec_13f_count_qtr" in features

    def test_sec_filing_count_90d(self, client):
        def mock_get(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "company_tickers" in url:
                return CIK_MAPPING_RESPONSE
            return SUBMISSIONS_RESPONSE

        with patch.object(client, "_http_get", side_effect=mock_get):
            features = client.get_features("AAPL", date(2026, 4, 11))
            # Filings within 90d of 2026-04-11 (cutoff=2026-01-11):
            # 03-15, 03-10, 02-20, 02-15 are within; 01-10 is before cutoff
            assert features["sec_filing_count_90d"] == 4.0

    def test_returns_nan_on_failure(self, client):
        with patch.object(client, "_http_get", side_effect=RuntimeError("err")):
            features = client.get_features("AAPL", date(2026, 4, 11))
            # When CIK lookup fails, get_company_filings returns [], so count=0
            assert features["sec_filing_count_90d"] == 0.0
            assert np.isnan(features["sec_filing_recency_days"])


# ---------------------------------------------------------------------------
# Test: user agent
# ---------------------------------------------------------------------------

class TestUserAgent:
    def test_default_user_agent(self, client):
        assert "Phoenix Trading Bot" in client._user_agent

    def test_custom_user_agent(self, tmp_path):
        import os
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Custom Agent foo@bar.com"}):
            c = SECClient()
            c._cache_dir = tmp_path / "sec_cache2"
            c._cache_dir.mkdir(parents=True, exist_ok=True)
            assert c._user_agent == "Custom Agent foo@bar.com"
