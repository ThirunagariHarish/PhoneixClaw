"""Unit tests for the Polymarket backtest loader (Phase 7, F10).

No network. Uses ``httpx.MockTransport`` to fake the Gamma /trades
endpoint and an isolated tmp cache dir.

Reference: docs/architecture/polymarket-tab.md Phase 7 DoD.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd
import pytest

from services.backtest_runner.src.loaders.polymarket_loader import (
    LoaderConfig,
    PolymarketBacktestLoader,
    PolymarketLoaderError,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(hours=1)


def _trade(ts: datetime, price: float, size: float) -> dict:
    return {"timestamp": ts.isoformat(), "price": price, "size": size}


def _make_loader(handler, tmp_path: Path) -> PolymarketBacktestLoader:
    transport = httpx.MockTransport(handler)
    cfg = LoaderConfig(cache_dir=tmp_path / "cache", page_limit=10)
    return PolymarketBacktestLoader(cfg, transport=transport)


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
def test_load_bars_buckets_trades_into_ohlc(tmp_path):
    trades = [
        _trade(START + timedelta(seconds=10), 0.50, 100),
        _trade(START + timedelta(seconds=20), 0.55, 50),
        _trade(START + timedelta(seconds=30), 0.48, 25),
        # Second minute
        _trade(START + timedelta(minutes=1, seconds=5), 0.60, 10),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/trades"
        assert request.url.params["market"] == "mkt-1"
        return httpx.Response(200, json=trades)

    with _make_loader(handler, tmp_path) as loader:
        df = loader.load_bars("mkt-1", START, END)

    assert list(df.columns) == [
        "time", "open", "high", "low", "close", "volume", "mid", "trades",
    ]
    assert len(df) == 2
    first = df.iloc[0]
    assert first["open"] == pytest.approx(0.50)
    assert first["high"] == pytest.approx(0.55)
    assert first["low"] == pytest.approx(0.48)
    assert first["close"] == pytest.approx(0.48)
    assert first["volume"] == pytest.approx(175)
    assert first["trades"] == 3
    second = df.iloc[1]
    assert second["open"] == pytest.approx(0.60)
    assert second["volume"] == pytest.approx(10)


def test_load_bars_paginates_until_short_page(tmp_path):
    page_one = [_trade(START + timedelta(seconds=i), 0.5, 1) for i in range(10)]
    page_two = [_trade(START + timedelta(seconds=10 + i), 0.5, 1) for i in range(3)]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        offset = int(request.url.params["offset"])
        if offset == 0:
            return httpx.Response(200, json=page_one)
        if offset == 10:
            return httpx.Response(200, json=page_two)
        return httpx.Response(200, json=[])

    with _make_loader(handler, tmp_path) as loader:
        df = loader.load_bars("mkt-1", START, END)

    assert calls["n"] == 2
    assert df["trades"].sum() == 13


def test_load_bars_envelope_with_data_key(tmp_path):
    trades = [_trade(START + timedelta(seconds=5), 0.7, 2)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": trades})

    with _make_loader(handler, tmp_path) as loader:
        df = loader.load_bars("mkt-1", START, END)
    assert len(df) == 1
    assert df.iloc[0]["close"] == pytest.approx(0.7)


def test_load_bars_empty_window_returns_empty_schema(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    with _make_loader(handler, tmp_path) as loader:
        df = loader.load_bars("mkt-1", START, END)

    assert df.empty
    assert list(df.columns) == [
        "time", "open", "high", "low", "close", "volume", "mid", "trades",
    ]


def test_load_bars_uses_parquet_cache(tmp_path):
    trades = [_trade(START + timedelta(seconds=5), 0.5, 1)]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=trades)

    with _make_loader(handler, tmp_path) as loader:
        df1 = loader.load_bars("mkt-cache", START, END)
        df2 = loader.load_bars("mkt-cache", START, END)

    assert calls["n"] == 1  # second call served from cache
    pd.testing.assert_frame_equal(df1.reset_index(drop=True), df2.reset_index(drop=True))

    # Cache file actually exists on disk.
    cache_files = list((tmp_path / "cache").glob("*.cache"))
    assert len(cache_files) == 1


def test_load_bars_force_refresh_bypasses_cache(tmp_path):
    trades = [_trade(START + timedelta(seconds=5), 0.5, 1)]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=trades)

    with _make_loader(handler, tmp_path) as loader:
        loader.load_bars("mkt-1", START, END)
        loader.load_bars("mkt-1", START, END, force_refresh=True)

    assert calls["n"] == 2


def test_load_bars_http_error_raises(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="boom")

    with _make_loader(handler, tmp_path) as loader:
        with pytest.raises(PolymarketLoaderError):
            loader.load_bars("mkt-1", START, END)


def test_load_bars_transport_error_raises(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    with _make_loader(handler, tmp_path) as loader:
        with pytest.raises(PolymarketLoaderError):
            loader.load_bars("mkt-1", START, END)


def test_load_bars_non_json_raises(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", headers={"content-type": "text/plain"})

    with _make_loader(handler, tmp_path) as loader:
        with pytest.raises(PolymarketLoaderError):
            loader.load_bars("mkt-1", START, END)


def test_load_bars_non_list_payload_raises(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "bad"})

    with _make_loader(handler, tmp_path) as loader:
        with pytest.raises(PolymarketLoaderError):
            loader.load_bars("mkt-1", START, END)


def test_load_bars_skips_malformed_records(tmp_path):
    trades = [
        {"price": 0.5, "size": 1},  # missing ts
        {"timestamp": (START + timedelta(seconds=5)).isoformat(), "size": 1},  # missing price
        _trade(START + timedelta(seconds=10), 0.6, 2),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=trades)

    with _make_loader(handler, tmp_path) as loader:
        df = loader.load_bars("mkt-1", START, END)

    assert len(df) == 1
    assert df.iloc[0]["volume"] == pytest.approx(2)


def test_load_bars_accepts_numeric_timestamps(tmp_path):
    ts_ms = int((START + timedelta(seconds=5)).timestamp() * 1000)
    ts_s = int((START + timedelta(seconds=70)).timestamp())
    trades = [
        {"ts": ts_ms, "price": 0.5, "size": 1},
        {"ts": ts_s, "price": 0.7, "size": 1},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=trades)

    with _make_loader(handler, tmp_path) as loader:
        df = loader.load_bars("mkt-1", START, END)

    assert len(df) == 2


def test_load_bars_rejects_inverted_window(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json=[])

    with _make_loader(handler, tmp_path) as loader:
        with pytest.raises(PolymarketLoaderError):
            loader.load_bars("mkt-1", END, START)


def test_load_bars_walk_forward_compatible_columns(tmp_path):
    """Smoke check: loader output looks like the existing data_loader frame.

    The walk-forward engine consumes ``time/open/high/low/close/volume``
    columns; we extend that schema with ``mid/trades`` but stay backwards
    compatible.
    """
    trades = [_trade(START + timedelta(seconds=i * 5), 0.5 + i * 0.01, 1) for i in range(5)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=trades)

    with _make_loader(handler, tmp_path) as loader:
        df = loader.load_bars("mkt-1", START, END)

    for col in ("time", "open", "high", "low", "close", "volume"):
        assert col in df.columns
    assert pd.api.types.is_datetime64_any_dtype(df["time"])
