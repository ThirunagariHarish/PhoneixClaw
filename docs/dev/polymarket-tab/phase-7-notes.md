# Phase 7 — Backtest loader (F10)

## What changed
- New `PolymarketBacktestLoader` in `services/backtest-runner/src/loaders/polymarket_loader.py`.
- Pulls historical trades from Gamma `/trades` (paginated, `start_ts`/`end_ts`/`offset`/`limit` params) and buckets them into OHLC-equivalent bars at a configurable interval (default `1min`).
- Output schema: `time, open, high, low, close, volume, mid, trades` — a superset of `services/backtest-runner/src/data_loader.py` columns so existing walk-forward consumers stay compatible.
- On-disk cache keyed by `(market_id, interval, start, end)` under `PM_BACKTEST_CACHE_DIR` (default `/tmp/phoenix-pm-backtest-cache`). Parquet when `pyarrow`/`fastparquet` is importable, otherwise pickle. Cache write failures are logged but never break a backtest. `force_refresh=True` bypasses the cache.
- Sync `httpx.Client` so the loader can be driven from the sync walk-forward engine without an event loop. Tests inject `httpx.MockTransport`.
- Defensive parsing: tolerates multiple Gamma field spellings (`timestamp|ts|time|createdAt|created_at`, `price|p|executionPrice`, `size|amount|shares|qty`), numeric ts in seconds or milliseconds, ISO strings with `Z`, and wrapped `{"data": [...]}` envelopes. Malformed records are skipped.

## Files touched
- `services/backtest-runner/src/loaders/__init__.py` (new, empty)
- `services/backtest-runner/src/loaders/polymarket_loader.py` (new)
- `tests/unit/polymarket/test_pm_backtest_loader.py` (new, 14 tests)

## Tests added
14 unit tests covering: OHLC bucketing math, pagination termination on short page, `{"data": [...]}` envelope, empty-window schema, parquet/pickle cache hit, `force_refresh` bypass, HTTP 5xx, transport error, non-JSON body, non-list payload, malformed-record skipping, numeric ts coercion (s + ms), inverted-window validation, walk-forward column compatibility smoke.

## Commands
- `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/polymarket/ -q` — 125 passed (14 new + 111 pre-existing).
- `.venv/bin/ruff check` on all touched files — clean (2 auto-fixed import-order / unused-import issues during iteration).

## Deviations from the plan
- Phase 7 spec says "on-disk parquet cache". I kept parquet as the preferred format but added a pickle fallback because the dev environment does not have `pyarrow`/`fastparquet` installed and Phase 7 should not introduce a new hard dependency without Atlas sign-off. Cache format is internal; swapping back to parquet-only is a one-line change once the dep is added. Flagging for Build review.
- Phase 7 also mentions a "sample backtest of `sum_to_one_arb` archetype (synthetic strategy) runs end-to-end and writes a `backtests` row" as part of DoD. That end-to-end integration test (`tests/integration/backtest/test_pm_walk_forward.py`) requires the `sum_to_one_arb` agent which lands in Phase 8, plus DB wiring — out of scope for a pure loader phase. Leaving a stub for Phase 8 to pick up; unit-level walk-forward column compatibility is covered by `test_load_bars_walk_forward_compatible_columns`.

## Open risks
- Gamma `/trades` query parameter names (`start_ts`/`end_ts`) are inferred from public docs; the exact spelling may differ once we wire against live Gamma. Because the loader is thin and all HTTP is behind one method (`_fetch_trades`), this is a single-line adjustment with no schema impact.
- `MAX_PAGES=200` × `page_limit=500` = 100k trades per window hard cap. Adequate for minute-bucketed backtests on a single market; revisit if we ever want tick-level multi-day replay.

## Handoff
- Files: `/Users/harishkumar/Projects/TradingBot/ProjectPhoneix/services/backtest-runner/src/loaders/polymarket_loader.py`, `/Users/harishkumar/Projects/TradingBot/ProjectPhoneix/services/backtest-runner/src/loaders/__init__.py`, `/Users/harishkumar/Projects/TradingBot/ProjectPhoneix/tests/unit/polymarket/test_pm_backtest_loader.py`.
- Ready for Cortex review. Do not merge into Phase 8 work until review lands.
