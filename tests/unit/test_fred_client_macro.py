"""Unit tests for FRED client macro feature composition."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from shared.data.fred_client import FredClient


def test_get_macro_features_composite(monkeypatch):
    """economic_surprise_composite is present when CPI/PPI/sentiment exist."""

    idx = pd.date_range("2023-01-01", periods=30, freq="ME")

    def fake_series(series_id, start=None, end=None):
        if series_id == "CPIAUCSL":
            return pd.Series(np.linspace(290, 312, len(idx)), index=idx)
        if series_id == "PPIACO":
            return pd.Series(np.linspace(240, 252, len(idx)), index=idx)
        if series_id == "UMCSENT":
            return pd.Series(np.linspace(72, 66, len(idx)), index=idx)
        if series_id == "T10Y2Y":
            return pd.Series(np.linspace(0.6, 0.25, len(idx)), index=idx)
        if series_id == "ICSA":
            return pd.Series(np.full(len(idx), 220_000.0), index=idx)
        return pd.Series(np.full(len(idx), 4.0 + hash(series_id) % 3 * 0.01), index=idx)

    client = FredClient(api_key="test")
    monkeypatch.setattr(client, "_get_fred", lambda: MagicMock())
    monkeypatch.setattr(client, "get_series", fake_series)

    feats = client.get_macro_features(date(2024, 6, 1))
    assert "economic_surprise_composite" in feats
    assert not np.isnan(feats["economic_surprise_composite"])


# ---- Cache hit / miss behavior ----

def test_get_series_cache_hit(monkeypatch, tmp_path):
    """When cache is fresh, FRED API should not be called."""
    import shared.data.fred_client as fred_module

    monkeypatch.setattr(fred_module, "_CACHE_DIR", tmp_path)
    client = FredClient(api_key="test")

    # Pre-populate cache
    s = pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2024-01-01", periods=3))
    pd.DataFrame(s).to_parquet(tmp_path / "DGS10.parquet")

    mock_fred = MagicMock()
    mock_fred.get_series = MagicMock(side_effect=Exception("Should not be called"))
    monkeypatch.setattr(client, "_fred", mock_fred)

    result = client.get_series("DGS10")
    assert len(result) == 3
    mock_fred.get_series.assert_not_called()


def test_get_series_cache_miss_fetches_from_api(monkeypatch, tmp_path):
    """When cache is stale/missing, should fetch from API."""
    import shared.data.fred_client as fred_module

    monkeypatch.setattr(fred_module, "_CACHE_DIR", tmp_path)
    client = FredClient(api_key="test")

    expected = pd.Series([4.5, 4.6], index=pd.date_range("2024-06-01", periods=2))
    mock_fred = MagicMock()
    mock_fred.get_series.return_value = expected
    monkeypatch.setattr(client, "_fred", mock_fred)

    result = client.get_series("DGS10")
    mock_fred.get_series.assert_called_once()
    assert len(result) == 2


# ---- Network failure handling ----

def test_get_series_api_failure_returns_empty(monkeypatch, tmp_path):
    """When API fails and no cache exists, return empty Series."""
    import shared.data.fred_client as fred_module

    monkeypatch.setattr(fred_module, "_CACHE_DIR", tmp_path)
    client = FredClient(api_key="test")

    mock_fred = MagicMock()
    mock_fred.get_series.side_effect = Exception("Network error")
    monkeypatch.setattr(client, "_fred", mock_fred)

    result = client.get_series("DGS10")
    assert isinstance(result, pd.Series)
    assert result.empty


def test_get_series_api_failure_falls_back_to_stale_cache(monkeypatch, tmp_path):
    """When API fails but stale cache exists, return stale cache data."""
    import os
    import time

    import shared.data.fred_client as fred_module

    monkeypatch.setattr(fred_module, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(fred_module, "_CACHE_TTL_HOURS", 0)  # Force stale

    client = FredClient(api_key="test")

    # Write stale cache
    stale_data = pd.Series([99.0], index=pd.date_range("2024-01-01", periods=1))
    cache_path = tmp_path / "DGS10.parquet"
    pd.DataFrame(stale_data).to_parquet(cache_path)
    # Make it old
    old_time = time.time() - 999999
    os.utime(cache_path, (old_time, old_time))

    mock_fred = MagicMock()
    mock_fred.get_series.side_effect = Exception("Network error")
    monkeypatch.setattr(client, "_fred", mock_fred)

    result = client.get_series("DGS10")
    assert len(result) == 1
    assert result.iloc[0] == 99.0


# ---- No FRED API key ----

def test_no_api_key_raises(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    client = FredClient(api_key="")
    import pytest
    with pytest.raises(ValueError, match="FRED_API_KEY"):
        client._get_fred()


# ---- economic_surprise_composite with partial data ----

def test_surprise_composite_only_cpi(monkeypatch):
    """When only CPI data is available, composite should still be computed."""
    idx = pd.date_range("2023-01-01", periods=30, freq="ME")

    def fake_series(series_id, start=None, end=None):
        if series_id == "CPIAUCSL":
            return pd.Series(np.linspace(290, 312, len(idx)), index=idx)
        return pd.Series(dtype=float)  # empty for everything else

    client = FredClient(api_key="test")
    monkeypatch.setattr(client, "_get_fred", lambda: MagicMock())
    monkeypatch.setattr(client, "get_series", fake_series)

    feats = client.get_macro_features(date(2024, 6, 1))
    assert "economic_surprise_composite" in feats
    assert not np.isnan(feats["economic_surprise_composite"])


def test_surprise_composite_all_empty(monkeypatch):
    """When all series are empty, composite should be nan."""

    def fake_series(series_id, start=None, end=None):
        return pd.Series(dtype=float)

    client = FredClient(api_key="test")
    monkeypatch.setattr(client, "_get_fred", lambda: MagicMock())
    monkeypatch.setattr(client, "get_series", fake_series)

    feats = client.get_macro_features(date(2024, 6, 1))
    assert np.isnan(feats["economic_surprise_composite"])


# ---- yield_curve_inverted ----

def test_yield_curve_inverted_flag(monkeypatch):
    """When 2y > 10y, yield_curve_inverted should be 1.0."""
    idx = pd.date_range("2023-01-01", periods=30, freq="ME")

    def fake_series(series_id, start=None, end=None):
        if series_id == "DGS2":
            return pd.Series(np.full(len(idx), 5.0), index=idx)
        if series_id == "DGS10":
            return pd.Series(np.full(len(idx), 4.0), index=idx)
        return pd.Series(np.full(len(idx), 1.0), index=idx)

    client = FredClient(api_key="test")
    monkeypatch.setattr(client, "_get_fred", lambda: MagicMock())
    monkeypatch.setattr(client, "get_series", fake_series)

    feats = client.get_macro_features(date(2024, 6, 1))
    assert feats["yield_curve_inverted"] == 1.0


def test_yield_curve_not_inverted(monkeypatch):
    idx = pd.date_range("2023-01-01", periods=30, freq="ME")

    def fake_series(series_id, start=None, end=None):
        if series_id == "DGS2":
            return pd.Series(np.full(len(idx), 3.0), index=idx)
        if series_id == "DGS10":
            return pd.Series(np.full(len(idx), 4.5), index=idx)
        return pd.Series(np.full(len(idx), 1.0), index=idx)

    client = FredClient(api_key="test")
    monkeypatch.setattr(client, "_get_fred", lambda: MagicMock())
    monkeypatch.setattr(client, "get_series", fake_series)

    feats = client.get_macro_features(date(2024, 6, 1))
    assert feats["yield_curve_inverted"] == 0.0


# ---- get_release_dates ----

def test_get_release_dates_unknown_event():
    client = FredClient(api_key="test")
    assert client.get_release_dates("unknown_event") == []


def test_get_release_dates_cached(monkeypatch, tmp_path):
    import json as json_mod

    import shared.data.fred_client as fred_module

    monkeypatch.setattr(fred_module, "_CACHE_DIR", tmp_path)
    client = FredClient(api_key="test")

    # Pre-populate cache
    dates = ["2024-06-12", "2024-07-31"]
    (tmp_path / "release_fomc.json").write_text(json_mod.dumps(dates))

    result = client.get_release_dates("fomc")
    assert len(result) == 2
    assert result[0] == date(2024, 6, 12)


def test_get_release_dates_api_failure_returns_empty(monkeypatch, tmp_path):
    import shared.data.fred_client as fred_module

    monkeypatch.setattr(fred_module, "_CACHE_DIR", tmp_path)
    client = FredClient(api_key="test")

    mock_fred = MagicMock()
    mock_fred.get_release_dates.side_effect = Exception("API error")
    monkeypatch.setattr(client, "_fred", mock_fred)

    result = client.get_release_dates("fomc")
    assert result == []


# ---- get_event_dates fallback to static ----

def test_get_event_dates_falls_back_to_static(monkeypatch):
    client = FredClient(api_key="test")
    # Force get_release_dates to return empty
    monkeypatch.setattr(client, "get_release_dates", lambda name: [])

    dates = client.get_event_dates("fomc")
    assert len(dates) > 0
    assert all(isinstance(d, date) for d in dates)


def test_get_event_dates_unknown_returns_empty(monkeypatch):
    client = FredClient(api_key="test")
    monkeypatch.setattr(client, "get_release_dates", lambda name: [])
    assert client.get_event_dates("nonexistent_event") == []


# ---- get_macro_features string date input ----

def test_get_macro_features_string_date(monkeypatch):
    idx = pd.date_range("2023-01-01", periods=30, freq="ME")

    def fake_series(series_id, start=None, end=None):
        return pd.Series(np.full(len(idx), 2.0), index=idx)

    client = FredClient(api_key="test")
    monkeypatch.setattr(client, "_get_fred", lambda: MagicMock())
    monkeypatch.setattr(client, "get_series", fake_series)

    feats = client.get_macro_features("2024-06-01")
    assert isinstance(feats, dict)
    assert "treasury_2y" in feats


# ---- Jobless claims 4w avg ----

def test_jobless_claims_insufficient_data(monkeypatch):
    """With fewer than 4 data points, jobless_claims_4w_avg should be nan."""

    def fake_series(series_id, start=None, end=None):
        if series_id == "ICSA":
            return pd.Series([200_000.0], index=pd.date_range("2024-01-01", periods=1))
        return pd.Series(dtype=float)

    client = FredClient(api_key="test")
    monkeypatch.setattr(client, "_get_fred", lambda: MagicMock())
    monkeypatch.setattr(client, "get_series", fake_series)

    feats = client.get_macro_features(date(2024, 6, 1))
    assert np.isnan(feats["jobless_claims_4w_avg"])


# ---- CPI YoY with insufficient history ----

def test_cpi_yoy_insufficient_history(monkeypatch):
    """With fewer than 13 CPI data points, cpi_yoy_change should be nan."""
    idx = pd.date_range("2024-01-01", periods=5, freq="ME")

    def fake_series(series_id, start=None, end=None):
        if series_id == "CPIAUCSL":
            return pd.Series(np.linspace(300, 305, 5), index=idx)
        return pd.Series(dtype=float)

    client = FredClient(api_key="test")
    monkeypatch.setattr(client, "_get_fred", lambda: MagicMock())
    monkeypatch.setattr(client, "get_series", fake_series)

    feats = client.get_macro_features(date(2024, 6, 1))
    assert np.isnan(feats["cpi_yoy_change"])
