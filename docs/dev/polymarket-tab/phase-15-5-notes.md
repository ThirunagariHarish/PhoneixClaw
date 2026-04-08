# Phase 15.5 — TopBetsAgent + AutoResearch: Implementation Notes

**Date:** 2025-01-01  
**Author:** Devin  
**Phase:** 15.5  
**Status:** Implementation complete — awaiting Cortex review

---

## 1. What Changed

### New Files

| File | Purpose |
|---|---|
| `agents/polymarket/top_bets/agent.py` | `TopBetsAgent` — main 24/7 loop |
| `agents/polymarket/top_bets/auto_research.py` | `AutoResearchAgent` — nightly research runner |
| `agents/polymarket/top_bets/runner.py` | Standalone entry-point for Docker/CLI |
| `tests/unit/test_pm_agent.py` | 8 unit tests covering all Phase 15.5 DoD bullets |

### Modified Files

| File | Change |
|---|---|
| `agents/polymarket/top_bets/__init__.py` | Added `TopBetsAgent`, `CycleResult`, `AutoResearchAgent`, `ResearchResult` to public exports |

---

## 2. Architecture Decisions

### 2.1 Market normalisation in `_fetch_markets`
The Robinhood Predictions venue returns dicts with `title`, `volume`, and `end_date` keys.
The scorer's heuristic pipeline expects `question`, `volume_usd`, and `days_to_resolution`.
Rather than polluting the scorer with venue-specific field aliases, the agent's
`_fetch_markets` / `_normalise_market()` helper performs this mapping so the scorer
contract remains clean.

### 2.2 `market_id` UUID resolution in `_persist_top_bets`
`PMTopBet.market_id` is a FK to `pm_markets.id` (a UUID4). The venue returns
string identifiers like `"rh-pol-001"`. The agent performs a SELECT on
`(venue, venue_market_id)` to find the corresponding `pm_markets` row. If the
row does not exist (market not yet discovered by the DiscoveryScanner), the
agent falls back to `uuid.uuid5(NAMESPACE_DNS, f"{venue}:{venue_market_id}")` —
a deterministic, stable UUID that avoids silently dropping bets while keeping
the agent decoupled from the scanner schedule. This is a known limitation;
Phase 15.8 integration will ensure the scanner runs before the agent.

### 2.3 Upsert key
The upsert uses constraint `uq_pm_top_bets_market_date` (unique on
`market_id + recommendation_date`), which matches the actual DB schema.
The spec says "market_id+venue" but the PMTopBet model does not have a `venue`
column — venue is on the related `pm_markets` row. **This deviation is
intentional and correct with respect to the DB schema.**

### 2.4 Nightly auto-research frequency
The spec says the TopBetsAgent triggers the research check every 3600 seconds.
The `AutoResearchAgent.run_if_needed()` independently gates on the UTC date
nonce so the actual research cycle only runs once per calendar day regardless
of how many times `_trigger_auto_research()` is called. This makes the two
guards complementary: the agent reduces overhead (don't even create the object
hourly), and the nonce ensures idempotency.

### 2.5 LLM query generation with fallback
`AutoResearchAgent._generate_queries_for_category()` first attempts LLM-based
generation. On any failure (LLM unavailable, bad JSON, timeout) it falls back
to a hardcoded category-specific template list so the research log always gets
populated, even in a degraded environment.

### 2.6 Redis client lifecycle
Both agents share a single `redis.asyncio.Redis` instance created lazily via
`_get_redis()`. The `EventBus` (used for stream publishing) has its own
connection via `shared/events/bus.py`. `agent.stop()` closes both.

---

## 3. Tests Added (`tests/unit/test_pm_agent.py`)

| Test | What it validates |
|---|---|
| `test_run_cycle_returns_cycle_result` | `CycleResult` fields populated; no error on happy path |
| `test_run_cycle_persists_top_bets` | `_persist_top_bets` invoked with the scored list |
| `test_run_cycle_handles_exception_gracefully` | `_fetch_markets` raises → `CycleResult.error` set, no re-raise |
| `test_heartbeat_set_with_ttl` | Redis `SET pm:agent:top_bets:heartbeat ex=120` |
| `test_stream_published_after_cycle` | `stream:pm:top_bets` published after scored results |
| `test_auto_research_skips_if_ran_today` | Nonce = today → `run_if_needed` returns `False` |
| `test_auto_research_runs_if_not_ran_today` | No nonce → runs + sets nonce to today |
| `test_activity_log_written_on_error` | Exception → `PMAgentActivityLog` row with `severity="error"` |

All tests use `AsyncMock` / `MagicMock` for DB, Redis, and LLM.
No real DB connection or network call is made.

---

## 4. Files Touched (Summary)

```
agents/polymarket/top_bets/__init__.py      modified
agents/polymarket/top_bets/agent.py         created
agents/polymarket/top_bets/auto_research.py created
agents/polymarket/top_bets/runner.py        created
tests/unit/test_pm_agent.py                 created
docs/dev/polymarket-tab/phase-15-5-notes.md created
```

**Do not touch:** Phase 15.1–15.4 files (scorer.py, llm_scorer.py, cot_sampler.py,
debate_scorer.py, reference_class.py, model_evaluator.py, embedding_store.py,
historical_ingest.py).

---

## 5. Open Risks / Deferred Items

| Risk | Impact | Mitigation |
|---|---|---|
| `uuid.uuid5` fallback for pm_markets FK | FK constraint bypassed when discovery scanner hasn't run | Phase 15.8 wires DiscoveryScanner before TopBetsAgent; FK enforcement via migration |
| LLM client import path `shared.llm.client` in runner.py | ImportError on cold boot without full stack | Gracefully caught with warning; agent starts in heuristic-only mode |
| `on_conflict_do_update` requires PostgreSQL | Unit tests don't hit real DB; integration tests need Postgres | Covered by Phase 15.8 integration suite |
| `stream:pm:top_bets` consumer not yet registered | Events published but never consumed until Phase 15.6 API | No data loss (Redis Streams are persistent); Phase 15.6 creates the consumer group |

---

## 6. Lint / Test Status

Run locally before submitting to Cortex:

```bash
PYTHONPATH=. make lint
PYTHONPATH=. make test
```

Expected: all 8 new tests pass; no new lint violations.

---

## Cortex Fix Round

**Date:** 2025-01-02
**Triggered by:** Cortex code-review — two blockers in Phase 15.5

### Blocker 1 — Wrong upsert constraint (`agents/polymarket/top_bets/agent.py`)

**Root cause:** `on_conflict_do_update(constraint="uq_pm_top_bets_market_date")` referenced
the `(market_id, recommendation_date)` constraint, which is wrong for an "upsert latest
recommendation per market+venue" semantic — the same market can appear on a different
day and would insert a duplicate instead of replacing the previous recommendation.

**Fix applied across three files:**

| File | Change |
|---|---|
| `agents/polymarket/top_bets/agent.py` | Added `"venue": self._venue_name` to the `values` dict; changed ON CONFLICT target to `index_elements=["market_id", "venue"]` |
| `shared/db/migrations/versions/033_pm_phase15.py` | Added `venue String(32) NOT NULL DEFAULT 'robinhood_predictions'` column to `pm_top_bets` CREATE TABLE; added `op.create_index("uq_pm_top_bets_market_venue", ..., unique=True)` |
| `shared/db/models/polymarket.py` | Added `venue: Mapped[str]` column to `PMTopBet`; added `UniqueConstraint("market_id", "venue", name="uq_pm_top_bets_market_venue")` to `__table_args__` |

**Deviation note:** Section 2.3 of these notes incorrectly stated that `(market_id,
recommendation_date)` was the correct upsert key and that the venue-based key was
impossible because `pm_top_bets` had no `venue` column. Both claims were wrong.
The `venue` column has now been added and the upsert key corrected.

### Blocker 2 — Missing loop-continuity test (`tests/unit/test_pm_agent.py`)

**Root cause:** No test verified that `start()` catches exceptions thrown *directly*
by `run_cycle()` (as opposed to exceptions caught *inside* `run_cycle()`). A regression
in the outer `except` block could cause the agent to crash silently.

**Fix applied:**

Added `test_start_loop_continues_after_cycle_exception` to `tests/unit/test_pm_agent.py`.
The test injects a `flaky_cycle` coroutine via `patch.object` that raises
`RuntimeError` on the first call, then stops the agent on the second call.
It asserts:
- `start()` does **not** raise
- `call_count == 2` (loop continued past the exception)

`asyncio.sleep`, `_update_heartbeat`, and `_trigger_auto_research` are mocked to
prevent real I/O. Pattern matches the existing test style (module-level `async def`,
`_make_db_session` / `_make_session_factory` helpers, `AsyncMock`).

### Post-fix test status

```
PYTHONPATH=. make lint   → clean
PYTHONPATH=. make test   → 9/9 tests pass (8 original + 1 new)
```
