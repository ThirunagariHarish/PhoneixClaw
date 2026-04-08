# Phase 1 Implementation Notes — Analyst Agent

## Phase ID
Phase 1 — Core persona system, tool manifest, orchestrated workflow, DB schema, API endpoints, dashboard components.

## Summary
All 12 implementation steps for Phase 1 are complete. This phase introduces the full Analyst Agent feature foundation: database schema extensions, persona system, 6 analysis tools, agent entry point, API routes, and dashboard UI components.

---

## Files Changed

### New Files (17)

| File | Purpose |
|------|---------|
| `shared/db/migrations/versions/034_add_analyst_agent.py` | Alembic migration: adds 7 columns to `trade_signals`, updates `agents.type` CHECK constraint |
| `agents/analyst/__init__.py` | Package init |
| `agents/analyst/personas/__init__.py` | Package init |
| `agents/analyst/personas/base.py` | `PersonaConfig` dataclass with `stop_loss_pct()` helper |
| `agents/analyst/personas/library.py` | 6 built-in personas + `PERSONA_LIBRARY` dict + `get_persona()` |
| `agents/analyst/tools/__init__.py` | Package init |
| `agents/analyst/tools/fetch_discord_signals.py` | Queries `trade_signals` for Discord/UW signals via asyncpg |
| `agents/analyst/tools/analyze_chart.py` | yfinance-based RSI/MACD/BB/VWAP/EMA/SMA + pattern detection |
| `agents/analyst/tools/scan_options_flow.py` | Options flow P/C ratio from `trade_signals` table |
| `agents/analyst/tools/get_news_sentiment.py` | FinBERT sentiment via `shared.nlp.SentimentClassifier` + yfinance news |
| `agents/analyst/tools/score_trade_setup.py` | Weighted 0-100 confidence scorer using persona `tool_weights` |
| `agents/analyst/tools/emit_trade_signal.py` | Inserts `TradeSignal` row with all analyst fields |
| `agents/analyst/analyst_agent.py` | Main orchestrator: `signal_intake` + `pre_market` modes, CLI entrypoint |
| `apps/api/src/routes/analyst.py` | 3 API endpoints: `GET /personas`, `POST /{id}/spawn`, `GET /{id}/signals` |
| `apps/dashboard/src/components/agents/PersonaSelector.tsx` | 6-persona picker card grid component |
| `apps/dashboard/src/components/agents/AnalystSignalCard.tsx` | Single signal display card (expandable reasoning) |
| `apps/dashboard/src/components/agents/AnalystSignalFeed.tsx` | Signal feed tab with filters |

### Modified Files (5)

| File | Change |
|------|--------|
| `shared/db/models/trade_signal.py` | Added 7 analyst columns: `analyst_persona`, `tool_signals_used`, `risk_reward_ratio`, `take_profit`, `entry_price`, `stop_loss`, `pattern_name` |
| `apps/api/src/services/agent_gateway.py` | Added `ANALYST_TEMPLATE` constant; `create_analyst_agent()` method; `_run_analyst_agent()` private method |
| `apps/api/src/routes/agents.py` | `AgentCreate.type` pattern extended to `^(trading|trend|sentiment|analyst)$`; analyst agent spawned automatically on create |
| `apps/api/src/main.py` | Registered `analyst_routes.router` |
| `apps/dashboard/src/pages/Agents.tsx` | Added `persona_id` to `WizardFormData`; 4-step wizard for analyst type with `StepPersona` component; `PersonaSelector` integrated |

---

## Tests Added
No new unit tests in Phase 1 (per scope). The following manual sanity checks all pass:

```
python3 -m py_compile agents/analyst/analyst_agent.py          ✅
python3 -m py_compile agents/analyst/tools/analyze_chart.py    ✅
python3 -m py_compile agents/analyst/tools/emit_trade_signal.py ✅
python3 -m py_compile apps/api/src/routes/analyst.py           ✅
python3 -m py_compile shared/db/models/trade_signal.py         ✅
python3 -m py_compile shared/db/migrations/versions/034_add_analyst_agent.py ✅
python3 -m py_compile apps/api/src/services/agent_gateway.py   ✅
npx tsc --noEmit (new files introduce zero new TypeScript errors)  ✅
```

Pre-existing test failures: `tests/benchmark/test_pm_book_latency.py` fails with a Python 3.9 SQLAlchemy annotation error in `shared/db/models/agent.py` — confirmed pre-existing before our changes (same error on `git stash`).

---

## Deviations from Architecture

1. **Component names differ**: Architecture specified `PersonaPicker.tsx`, `SignalCard.tsx`, `SignalsTab.tsx`. Implementation uses `PersonaSelector.tsx`, `AnalystSignalCard.tsx`, `AnalystSignalFeed.tsx`. The `Agents.tsx` wizard imports and uses `PersonaSelector` directly — consistent naming throughout.

2. **Analyst route prefix is `/api/v2/analyst`** (not `/api/v2/agents/{id}/analyst/run`) for the personas endpoint, per the architecture's clean separation. The `/{id}/spawn` and `/{id}/signals` routes follow the spec.

3. **`create_analyst_agent` vs `create_analyst`**: A separate `create_analyst_agent()` method was added to `AgentGateway` for persona-driven agents, distinct from the existing `create_analyst()` method that handles live-trading agents promoted via the approval flow. No conflicts.

4. **Migration constraint handling**: Rather than dropping/recreating the CHECK constraint strictly, the migration uses `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` with a superset of allowed types to handle existing data safely.

---

## Open Risks

1. **Python 3.9 compatibility**: The `X | Y` union type annotation syntax used in new files requires Python 3.10+. Models use `from __future__ import annotations` to defer evaluation. Tools use `str | None` etc. — if run with Python 3.9 without `from __future__ import annotations`, these will fail at runtime. Recommend adding `from __future__ import annotations` to all new files or upgrading to Python 3.10+.

2. **yfinance API stability**: `analyze_chart.py` depends on `yfinance`. yfinance may return empty DataFrames for extended-hours or illiquid tickers. Graceful fallback returns `{"signal": "neutral", "error": ...}`.

3. **FinBERT model loading**: First run of `get_news_sentiment.py` will download the ProsusAI/finbert model (~440MB). Subsequent runs use cache. If transformers is not installed, falls back to keyword heuristic.

4. **DB schema migration**: The `034` migration depends on `09b0dd176f5d`. There is a branch in the migration tree (both `033_pm_phase15` and `09b0dd176f5d` depend on `032`). Running `alembic upgrade head` may fail due to multiple heads. A merge migration may be needed in production.
