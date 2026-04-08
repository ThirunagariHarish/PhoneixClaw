# Phase 15.2 Implementation Notes — Robinhood Predictions Venue Adapter

**Phase:** 15.2 — Prediction Market Venue Adapters  
**Date:** 2025-01-20  
**Author:** Devin (implementation engineer)  
**Status:** ✅ Complete — all tests pass, lint clean

---

## Summary

Implemented the Robinhood Predictions venue adapter (paper mode) and wired it into the shared venue registry. Also extended the existing `PolymarketVenue` with the Phase-15 extended interface so both venues are accessible via a unified `get_venue()` entry point.

---

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `services/connector-manager/src/venues/robinhood_predictions.py` | **Created** | `RobinhoodPredictionsVenue` — paper-mode venue with 15 deterministic mock markets |
| `services/connector-manager/src/venues/polymarket_venue.py` | **Modified** | Added `fetch_markets`, `place_order`, `get_positions`, `venue_name`, `is_paper` (Phase-15 extended interface); added `httpx` import |
| `services/connector-manager/src/venues/__init__.py` | **Modified** | Added `RobinhoodPredictionsVenue` to exports |
| `shared/polymarket/venue_registry.py` | **Created** | `VENUE_REGISTRY` dict + `get_venue(name)` factory with deferred imports |
| `tests/unit/test_pm_venues.py` | **Created** | 31 unit tests covering both venues and the registry |

---

## Design Decisions & Deviations

### 1. Mock data is hardcoded, not seeded-random

The task spec said "deterministic (seeded or hardcoded)". I chose **hardcoded** over seeded-random because:
- Hard-coded markets are immediately readable in code review
- There's no risk of a `random.seed()` colliding with other test fixtures
- Prices, volumes, and dates were hand-crafted to be realistic rather than mechanically generated
- 15 markets across 4 categories (politics × 4, economics × 4, sports × 3, geopolitics × 4) were chosen for good categorical coverage

End-dates use a fixed anchor date (`2025-01-01T00:00:00Z`) so they never drift with wall-clock time.

### 2. Deferred imports in venue_registry.py

The task spec showed top-level imports in `venue_registry.py`. In practice, top-level importing `PolymarketVenue` cascades through `GammaClient → PolymarketBrokerAdapter → shared.polymarket.jurisdiction → shared.db.models` — a ~200ms import chain with SQLAlchemy model construction. I used **deferred imports** (imports inside `_registry()`, called lazily on first `get_venue()` invocation) to keep module load fast and avoid any future circular-import issues between `shared.*` and `services.*`. The public interface (`VENUE_REGISTRY` dict, `get_venue()`) is identical to the spec.

### 3. PolymarketVenue — `__new__` pattern in tests

Tests for `PolymarketVenue.fetch_markets` and `place_order` use `PolymarketVenue.__new__(PolymarketVenue)` to bypass `__init__` (which would construct a `GammaClient` and do network setup). This is safe because neither `fetch_markets` nor `place_order` touch `self._client` — they use `httpx.AsyncClient` directly. The pattern is consistent with the existing Phase-4 test style in `tests/unit/polymarket/`.

### 4. `scan()` delegate pattern in RobinhoodPredictionsVenue

The `MarketVenue` ABC requires `scan()` to be an async generator. `RobinhoodPredictionsVenue.scan()` wraps the same mock catalogue used by `fetch_markets()`, normalizing each record into a `MarketRow` for the `DiscoveryScanner`. This means the mock data is always consistent between the two call paths.

### 5. PolymarketVenue.get_positions() returns empty list

`PolymarketVenue` is a stateless wrapper around an HTTP client; it has no in-memory order store. `get_positions()` returns `[]`. Paper orders placed via `place_order()` return a receipt but are not persisted (the phase spec does not require persistence for `PolymarketVenue`). `RobinhoodPredictionsVenue`, by contrast, maintains an in-memory `_paper_orders` dict per instance.

---

## Test Results

```
31 passed in 0.18s   (tests/unit/test_pm_venues.py)
574 passed in 2.31s  (tests/unit/ full suite — no regressions)
```

### New tests breakdown

| Test | Coverage target |
|------|----------------|
| `test_robinhood_fetch_markets_returns_list` | Required fields present on all records |
| `test_robinhood_market_ids_are_unique` | No duplicate market_ids |
| `test_robinhood_prices_in_range` | yes_price / no_price ∈ [0.01, 0.99] |
| `test_robinhood_venue_field_is_set` | venue == "robinhood" on every record |
| `test_robinhood_categories_are_valid` | Only 4 valid category strings |
| `test_robinhood_fetch_markets_respects_limit` | limit parameter honoured |
| `test_robinhood_fetch_markets_default_limit` | Default limit=50 returns all 15 mock markets |
| `test_robinhood_get_market_returns_correct_record` | Correct record by market_id |
| `test_robinhood_get_market_raises_on_unknown_id` | KeyError on bad ID |
| `test_robinhood_place_order_paper_mode` | Receipt fields, paper=True |
| `test_robinhood_place_order_rejects_live` | ValueError when paper=False |
| `test_robinhood_place_order_rejects_invalid_side` | ValueError for bad side |
| `test_robinhood_place_order_rejects_non_positive_amount` | ValueError for amount ≤ 0 |
| `test_robinhood_place_order_no_side` | "no" side works |
| `test_robinhood_get_positions_empty_initially` | Empty on fresh instance |
| `test_robinhood_get_positions_tracks_placed_orders` | Orders accumulate |
| `test_robinhood_venue_name_property` | venue_name == "robinhood_predictions" |
| `test_robinhood_is_paper_property` | is_paper is True |
| `test_robinhood_name_class_attribute` | name class attr |
| `test_robinhood_scan_yields_market_rows` | MarketRow objects |
| `test_robinhood_scan_respects_limit` | scan limit |
| `test_polymarket_fetch_markets_handles_network_error` | Empty list on ConnectError |
| `test_polymarket_fetch_markets_handles_http_error` | Empty list on HTTPStatusError |
| `test_polymarket_fetch_markets_returns_list_on_success` | Parses JSON list |
| `test_polymarket_place_order_paper_mode` | Receipt returned |
| `test_polymarket_place_order_rejects_live` | ValueError when paper=False |
| `test_venue_registry_get_known_venue_robinhood` | Correct class returned |
| `test_venue_registry_get_known_venue_polymarket` | Correct class returned |
| `test_venue_registry_unknown_raises` | ValueError on bad name |
| `test_venue_registry_unknown_message_lists_known` | Error message lists known venues |
| `test_venue_registry_dict_populated_after_get` | VENUE_REGISTRY dict populated |

---

## Lint

```
ruff check: All checks passed (0 errors, 0 warnings)
```

---

## Open Risks

1. **Robinhood Predictions public API** — no public API has been announced as of Phase 15.2. When Robinhood opens their API, `_MOCK_MARKETS` in `robinhood_predictions.py` should be replaced with a real HTTP client (see the `PolymarketVenue` pattern). The switch will be backwards-compatible — the method signatures don't change.

2. **PolymarketVenue CLOB endpoint shape** — `fetch_markets` handles both `list` and `{"data": [...]}` response shapes from `https://clob.polymarket.com/markets`. If Polymarket changes their API schema again, the fallback will silently return `[]` (logged as WARNING). A schema test against the live API would catch drift early.

3. **In-memory paper orders** — `RobinhoodPredictionsVenue._paper_orders` is per-instance and non-persistent. If the connector-manager restarts, paper positions are lost. Phase 16+ should persist paper orders to `pm_orders` with `execution_type = "paper"`.
