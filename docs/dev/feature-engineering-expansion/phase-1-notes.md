# Phase 1 Notes: Foundation + Gap Analysis + Unusual Whales Extension

## What Changed

### Part A: BaseDataClient foundation
- Created `shared/data/base_client.py` -- abstract base class for all new data clients
- Implements: singleton via `get_instance()`, disk caching (JSON) with configurable TTL under `/tmp/phoenix_cache/<name>/`, `_is_cache_fresh()`, `_safe_float()` / `_safe_int()`, `_http_get()` sync HTTP with timeout, rate limiting (configurable requests/minute), abstract `get_features()` contract

### Part B: Gap Analysis module
- Created `shared/data/gap_analysis.py` -- pure OHLCV computation, no external API
- 16 features: `gap_pct_new`, `gap_direction`, `gap_filled`, `gap_fill_pct`, `weekend_gap`, `overnight_return`, `avg_gap_fill_rate_20d`, `gap_persistence_score`, `consecutive_gap_days`, `gap_vs_atr_ratio`, `avg_gap_size_20d`, `gap_std_20d`, `gap_zscore`, `max_gap_20d`, `gap_reversal_rate_20d`, `gap_continuation_pct`
- Two entry points: `compute_gap_features()` (single dict) and `compute_gap_features_batch()` (DataFrame)
- Named `gap_pct_new` to avoid collision with the existing `gap_pct` field in the pipeline

### Part C: Unusual Whales Extension
- Extended `shared/unusual_whales/models.py` with 6 new Pydantic models: `DarkPoolFlow`, `CongressionalTrade`, `InsiderTrade`, `ShortInterest`, `InstitutionalHolding`, `VolSurface`
- Extended `shared/unusual_whales/client.py` with 7 new async methods: `get_dark_pool()`, `get_congressional_trades()`, `get_insider_trades()`, `get_short_interest()`, `get_institutional_activity()`, `get_volatility_surface()`, `get_all_extended_features()`
- `get_all_extended_features()` returns a flat dict of 28 feature floats (NaN-safe)
- All methods follow existing cache and error handling patterns

### Part D: Pipeline Integration
- `agents/backtesting/tools/enrich.py`: Added Category 13 (gap features) and Category 14 (extended UW features with temporal leakage guard -- NaN for trades >5 days old)
- `agents/templates/live-trader-v1/tools/enrich_single.py`: Added sections 14 (gap features) and 15 (extended UW features, always live so no leakage guard needed)
- Both pipelines use feature flag env vars: `FEATURE_GAP_ANALYSIS`, `FEATURE_UW_EXTENDED` (default: "true")

## Files Created
- `shared/data/base_client.py`
- `shared/data/gap_analysis.py`
- `tests/unit/test_gap_analysis.py` (15 tests)
- `tests/unit/test_unusual_whales_extended.py` (20 tests)

## Files Modified
- `shared/unusual_whales/models.py` -- added 6 Pydantic models
- `shared/unusual_whales/client.py` -- added 7 async methods + import updates
- `agents/backtesting/tools/enrich.py` -- added Category 13 + 14
- `agents/templates/live-trader-v1/tools/enrich_single.py` -- added sections 14 + 15

## Tests Added
- 15 gap analysis tests covering: key presence, gap up/down/no-gap, fill detection, weekend gap, NaN safety, as_of_idx, batch mode, batch-single consistency, empty/None inputs, NaN data handling
- 20 UW extended tests covering: model defaults, each endpoint mocked, error fallback, get_all_extended_features (full, total failure, partial failure), cache behavior

## Deviations
- Named the gap percentage feature `gap_pct_new` instead of overriding the existing `gap_pct` to preserve backward compatibility (the PRD spec says "the existing gap_pct value remains unchanged and new features are additive")
- Used `from datetime import ...` inside the async method rather than at module level to avoid import side effects in the client module (datetime is only needed for feature computation, not for basic client operation)

## Open Risks
- Python 3.9 on the system default does not support `type | None` syntax used in the existing UW cache module -- tests must run with Python 3.13 (`/opt/homebrew/bin/python3.13`). This is a pre-existing issue, not introduced by this phase.
- Pre-existing lint issues in the enrich files (E501 line length, F811, F401) were not touched to minimize diff footprint.
