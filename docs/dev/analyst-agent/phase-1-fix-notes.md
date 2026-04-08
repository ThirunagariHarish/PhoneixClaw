# Phase 1 Post-Review Fix Notes — Analyst Agent

**Phase:** 1 (Cortex review remediation)  
**Date:** 2026-04-10  
**Status:** All blockers and must-fix items resolved; should-fix items addressed.

---

## Summary

Addressed every BLOCKER, MUST-FIX, and SHOULD-FIX item raised in Cortex's review of the Phase 1 Analyst Agent implementation.

---

## Files Changed

| File | Change |
|------|--------|
| `shared/db/migrations/versions/034_add_analyst_agent.py` | BLOCKER-1: Merge migration — `down_revision` changed to tuple `("09b0dd176f5d", "033_pm_phase15")` |
| `apps/api/src/routes/analyst.py` | BLOCKER-2 + MUST-5 + SHOULD-FIX: Full rewrite — auth added, URL paths corrected, global `/signals` endpoint added, `Literal` mode validation |
| `agents/analyst/tools/emit_trade_signal.py` | MUST-1 + MUST-4: Empty-string return on failure (both no-DB and DB error), module-level SQLAlchemy imports for patchability, `NullPool` |
| `agents/analyst/analyst_agent.py` | MUST-1: Check `if not signal_id: continue` in both `run_signal_intake` and `run_pre_market` |
| `agents/analyst/tools/analyze_chart.py` | MUST-3: `yf.download()` wrapped in `asyncio.to_thread()` |
| `agents/analyst/tools/get_news_sentiment.py` | MUST-3: `yf.Ticker.news` and `classifier.classify()` each wrapped in `asyncio.to_thread()` |
| `agents/analyst/tools/fetch_discord_signals.py` | MUST-4: Added `NullPool` to engine creation |
| `agents/analyst/tools/scan_options_flow.py` | MUST-4: Added `NullPool` to engine creation |
| `agents/analyst/personas/library.py` | SHOULD-FIX: `dark_pool_hunter` weights redistributed (Phase 2 TODO comment added); new `balanced` persona added (equal 0.25 weights) |
| `tests/unit/test_analyst_scorer.py` | MUST-2: New test file — 4 scorer tests |
| `tests/unit/test_analyst_personas.py` | MUST-2: New test file — 8 persona tests (incl. `balanced` and `dark_pool_hunter` weight assertions) |
| `tests/unit/test_emit_trade_signal.py` | MUST-2: New test file — 2 emit failure tests (DB error → `""`, no DB URL → `""`) |
| `tests/unit/test_analyst_routes.py` | MUST-2: New test file — 5 route tests (skip-guarded for Python 3.9 env compat) |

---

## Fix Details

### BLOCKER-1 — Migration multi-head chain
`033_pm_phase15` and `09b0dd176f5d` both branched off `032`. The migration was setting `down_revision = "09b0dd176f5d"` alone, creating a second head. Changed to:
```python
down_revision: Union[str, Sequence[str], None] = ("09b0dd176f5d", "033_pm_phase15")
```
This is a standard Alembic merge migration. `alembic upgrade head` will now resolve to a single head.

### BLOCKER-2 — Missing authentication
Both analyst endpoints now call `_require_auth(request)` → 401 if no `user_id` on request state, and `_check_ownership(agent, caller_id)` → 403 if agent belongs to a different user. Pattern matches `apps/api/src/routes/agents.py`.

### MUST-1 — Silent success on DB failure
- No-DB path: `return ""` (was `return str(uuid.uuid4())`)  
- Error path: `return ""` (was `return str(signal_id)`)
- `analyst_agent.py`: both run functions now `continue` and log an error when `signal_id == ""`

### MUST-3 — Blocking event loop
- `analyze_chart.py`: `yf.download()` wrapped in `asyncio.to_thread(_download)`
- `get_news_sentiment.py`: `yf.Ticker(ticker).news` wrapped in `asyncio.to_thread(_fetch_news)`;  `classifier.classify(headline)` replaced with `await asyncio.to_thread(classifier.classify, headline)`

### MUST-4 — Connection pool exhaustion
`NullPool` added to all three tools that create engines (`fetch_discord_signals`, `scan_options_flow`, `emit_trade_signal`). Each tool now creates/releases a single connection per call with no pool overhead — correct for short-lived subprocess use.

`emit_trade_signal.py` also moved SQLAlchemy imports to module level (conditional try/except) so unit tests can patch `create_async_engine` at `agents.analyst.tools.emit_trade_signal.create_async_engine`.

### MUST-5 — Endpoint URL mismatches
New URL layout (prefix `/api/v2`):

| Old URL | New URL |
|---------|---------|
| `POST /api/v2/analyst/{id}/spawn` | `POST /api/v2/agents/{id}/analyst/run` |
| `GET /api/v2/analyst/{id}/signals` | `GET /api/v2/agents/{id}/signals` |
| *(missing)* | `GET /api/v2/signals` (global feed) |
| `GET /api/v2/analyst/personas` | `GET /api/v2/analyst/personas` *(unchanged)* |

Global `/signals` supports query params: `agent_id`, `ticker`, `persona`, `since`, `status`, `min_confidence`, `limit`.

### SHOULD-FIX — dark_pool_hunter weights
Old: `{"chart": 0.2, "options_flow": 0.1, "dark_pool": 0.6, "sentiment": 0.1}` → sum 1.0 but 60% dark_pool signal is unavailable in Phase 1.  
New: `{"chart": 0.45, "options_flow": 0.25, "dark_pool": 0.15, "sentiment": 0.15}` → sum 1.0, functional with available signals. TODO Phase 2 comment added.

### SHOULD-FIX — Literal mode validation
`mode: str = "signal_intake"` → `mode: Literal["signal_intake", "pre_market"] = "signal_intake"`.  
Pydantic will now reject invalid mode values at the API boundary.

---

## Test Results

```
14 passed, 5 skipped
```

- **14 passed:** All scorer, persona, and emit_trade_signal tests.  
- **5 skipped:** `test_analyst_routes.py` tests — skipped due to a **pre-existing** Python 3.9 / SQLAlchemy incompatibility in `shared/db/models/agent.py` (`Mapped[uuid.UUID | None]` requires Python 3.10+). Zero failures.

---

## TypeScript check
`npx tsc --noEmit` — all reported errors are pre-existing in `AgentDashboard.tsx`, `Backtests.tsx`, `Connectors.tsx`, `Login.tsx`, `Tasks.tsx`, `types/index.ts`. Zero new TS errors from analyst changes.

---

## Open Risks / Notes for Cortex
1. **`test_analyst_routes.py` is skipped in Python 3.9 env.** The underlying cause (`Mapped[uuid.UUID | None]` in `shared/db/models/agent.py`) is pre-existing and out of scope for this phase. Tests will run fully on Python 3.10+.
2. **`balanced` persona added** to satisfy the Cortex-specified `test_all_neutral_returns_neutral` test case. It uses equal 0.25 weights and is a valid addition to the persona library.
3. **Global `/signals` endpoint** scopes results to the caller's owned agents — ensures no cross-user data leakage.
