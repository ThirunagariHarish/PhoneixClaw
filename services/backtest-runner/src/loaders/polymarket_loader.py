"""Polymarket historical data loader (Phase 7, Polymarket v1.0 / F10).

Pulls historical PM trade/book data from the Gamma API and exposes it to
the existing walk-forward backtest engine in OHLC-equivalent form.

Reference: docs/architecture/polymarket-tab.md Phase 7 (around line 730).

Design notes
------------
* Polymarket's Gamma API exposes historical *trades* per market (the
  ``/trades`` endpoint, paginated). There is no first-class historical
  *book* endpoint, so we synthesize an OHLC-equivalent series from trades
  by bucketing on a fixed interval (default 1 minute). Each bucket
  produces ``open / high / low / close / volume`` columns plus a
  ``mid`` column (last trade price within the bucket) so the loader is
  drop-in compatible with ``walk_forward.py`` consumers that expect a
  pandas frame with a ``time`` index column.
* Results are cached on disk (parquet when pyarrow/fastparquet is
  available, otherwise pickle) keyed by
  ``(market_id, interval, start, end)``. Subsequent calls within the
  same window are served from cache. The cache is bypassed when
  ``force_refresh=True``.
* All HTTP traffic is synchronous via ``httpx.Client`` so the loader can
  be invoked from the existing (sync) walk-forward engine without an
  event loop. Tests inject an ``httpx.MockTransport`` via the
  ``transport`` argument; production callers omit it.
* This loader is intentionally read-only and contains no business
  logic. Strategy-level signals are produced downstream by the
  archetype agents in ``agents/polymarket/``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
DEFAULT_TIMEOUT = 15.0
DEFAULT_PAGE_LIMIT = 500
MAX_PAGES = 200  # hard cap to avoid runaway pagination
DEFAULT_INTERVAL = "1min"

DEFAULT_CACHE_DIR = Path(
    os.getenv("PM_BACKTEST_CACHE_DIR", "/tmp/phoenix-pm-backtest-cache")
)


class PolymarketLoaderError(RuntimeError):
    """Raised on transport, schema, or pagination failures."""


@dataclass(frozen=True)
class LoaderConfig:
    """Tunable parameters for ``PolymarketBacktestLoader``."""

    base_url: str = DEFAULT_GAMMA_BASE_URL
    timeout: float = DEFAULT_TIMEOUT
    page_limit: int = DEFAULT_PAGE_LIMIT
    interval: str = DEFAULT_INTERVAL
    cache_dir: Path = DEFAULT_CACHE_DIR


class PolymarketBacktestLoader:
    """Loader producing OHLC-equivalent frames from Polymarket trade history.

    The loader is safe to instantiate per-backtest. Pass an explicit
    ``transport`` (``httpx.MockTransport`` in tests) to avoid touching
    the network.
    """

    def __init__(
        self,
        config: LoaderConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config or LoaderConfig()
        self._owns_client = client is None
        if client is not None:
            self._client = client
        else:
            self._client = httpx.Client(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                transport=transport,
            )

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "PolymarketBacktestLoader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def load_bars(
        self,
        market_id: str,
        start: datetime,
        end: datetime,
        *,
        interval: str | None = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Return an OHLC-equivalent frame for ``market_id`` over ``[start, end]``.

        Columns: ``time, open, high, low, close, volume, mid, trades``.

        ``time`` is timezone-aware UTC and sorted ascending. Empty windows
        return an empty DataFrame with the correct schema (so downstream
        code can rely on column presence).
        """
        if start >= end:
            raise PolymarketLoaderError("start must be strictly before end")

        interval = interval or self.config.interval
        cache_path = self._cache_path(market_id, interval, start, end)
        if not force_refresh and cache_path.exists():
            try:
                cached = _read_cache(cache_path)
                logger.info(
                    "pm_loader cache hit market=%s rows=%d path=%s",
                    market_id,
                    len(cached),
                    cache_path,
                )
                return cached
            except Exception as e:  # pragma: no cover - corrupt cache
                logger.warning(
                    "pm_loader cache read failed market=%s err=%s; refetching",
                    market_id,
                    type(e).__name__,
                )

        trades = self._fetch_trades(market_id, start, end)
        bars = self._bucketize(trades, interval=interval)
        self._write_cache(cache_path, bars)
        return bars

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _cache_path(
        self, market_id: str, interval: str, start: datetime, end: datetime
    ) -> Path:
        safe_id = market_id.replace("/", "_")
        fname = (
            f"{safe_id}__{interval}__{int(start.timestamp())}__{int(end.timestamp())}.cache"
        )
        return self.config.cache_dir / fname

    def _write_cache(self, path: Path, df: pd.DataFrame) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_cache_df(path, df)
        except Exception as e:
            # Cache write failures must never break a backtest run.
            logger.warning(
                "pm_loader cache write failed path=%s err=%s", path, type(e).__name__
            )

    def _fetch_trades(
        self, market_id: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """Page through ``/trades`` until the window is exhausted."""
        all_trades: list[dict[str, Any]] = []
        offset = 0
        for _ in range(MAX_PAGES):
            params = {
                "market": market_id,
                "limit": self.config.page_limit,
                "offset": offset,
                "start_ts": int(start.timestamp()),
                "end_ts": int(end.timestamp()),
            }
            try:
                resp = self._client.get("/trades", params=params)
            except httpx.HTTPError as e:
                logger.warning(
                    "pm_loader transport error market=%s err=%s",
                    market_id,
                    type(e).__name__,
                )
                raise PolymarketLoaderError(
                    f"gamma /trades transport error: {type(e).__name__}"
                ) from e

            if resp.status_code >= 400:
                raise PolymarketLoaderError(
                    f"gamma /trades http {resp.status_code} for market={market_id}"
                )

            try:
                payload = resp.json()
            except ValueError as e:
                raise PolymarketLoaderError(
                    f"gamma /trades non-json response for market={market_id}"
                ) from e

            page = payload["data"] if isinstance(payload, dict) and "data" in payload else payload
            if not isinstance(page, list):
                raise PolymarketLoaderError(
                    "gamma /trades returned non-list payload"
                )

            if not page:
                break

            all_trades.extend(page)
            if len(page) < self.config.page_limit:
                break
            offset += len(page)
        else:
            logger.warning(
                "pm_loader hit MAX_PAGES=%d market=%s — truncating", MAX_PAGES, market_id
            )

        return all_trades

    def _bucketize(
        self, trades: list[dict[str, Any]], *, interval: str
    ) -> pd.DataFrame:
        """Convert raw trades into OHLC-equivalent bars at ``interval``.

        Each input trade must expose at minimum a timestamp, a price and
        a size. Polymarket's payload uses different field names across
        endpoint versions, so we accept the common variants.
        """
        empty = pd.DataFrame(
            columns=["time", "open", "high", "low", "close", "volume", "mid", "trades"]
        )

        if not trades:
            return empty

        rows = []
        for t in trades:
            ts = _coerce_ts(t)
            price = _coerce_float(t, ("price", "p", "executionPrice"))
            size = _coerce_float(t, ("size", "amount", "shares", "qty")) or 0.0
            if ts is None or price is None:
                # Skip malformed records but never crash a backtest.
                continue
            rows.append({"time": ts, "price": price, "size": size})

        if not rows:
            return empty

        df = pd.DataFrame(rows).sort_values("time")
        df = df.set_index("time")
        agg = df["price"].resample(interval).ohlc()
        agg["volume"] = df["size"].resample(interval).sum()
        agg["mid"] = df["price"].resample(interval).last()
        agg["trades"] = df["price"].resample(interval).count()
        agg = agg.dropna(subset=["open"]).reset_index()
        # Forward-fill the close-derived mid so resamples without trades
        # carry the previous mark — useful for walk-forward windows.
        agg["mid"] = agg["mid"].ffill()
        return agg[["time", "open", "high", "low", "close", "volume", "mid", "trades"]]


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _has_parquet_engine() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import fastparquet  # noqa: F401
        return True
    except ImportError:
        return False


def _write_cache_df(path: Path, df: pd.DataFrame) -> None:
    if _has_parquet_engine():
        df.to_parquet(path, index=False)
    else:
        df.to_pickle(path)


def _read_cache(path: Path) -> pd.DataFrame:
    if _has_parquet_engine():
        try:
            return pd.read_parquet(path)
        except Exception:
            pass
    return pd.read_pickle(path)


def _coerce_ts(record: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "ts", "time", "createdAt", "created_at"):
        if key not in record:
            continue
        raw = record[key]
        if raw is None:
            continue
        try:
            if isinstance(raw, (int, float)):
                # Heuristic: ms vs s.
                if raw > 1e12:
                    return datetime.fromtimestamp(raw / 1000.0, tz=timezone.utc)
                return datetime.fromtimestamp(float(raw), tz=timezone.utc)
            if isinstance(raw, str):
                # ISO 8601; tolerate trailing Z.
                cleaned = raw.replace("Z", "+00:00")
                dt = datetime.fromisoformat(cleaned)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
        except (ValueError, OSError):
            continue
    return None


def _coerce_float(record: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in record and record[key] is not None:
            try:
                return float(record[key])
            except (TypeError, ValueError):
                continue
    return None
