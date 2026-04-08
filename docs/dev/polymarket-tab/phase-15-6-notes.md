# Phase 15.6 — API Endpoints Implementation Notes

**Phase:** 15.6  
**Status:** Complete  
**Author:** Devin  
**Date:** 2025-07-10

---

## What Changed

### New Route Modules (6 files created)

| File | Endpoints | Description |
|------|-----------|-------------|
| `apps/api/src/routes/pm_top_bets.py` | 5 | Top bets list, detail, summary, execute, feedback |
| `apps/api/src/routes/pm_chat.py` | 3 | SSE chat stream, history GET/DELETE |
| `apps/api/src/routes/pm_agents.py` | 3 | Agent health, activity log, manual cycle trigger |
| `apps/api/src/routes/pm_research.py` | 2 | Auto-research trigger, research logs |
| `apps/api/src/routes/pm_venues.py` | 3 | List venues, fetch live markets, sync to DB |
| `apps/api/src/routes/pm_pipeline.py` | 5 | On-demand score, calibration, feedback, models, config |

**Total: 21 endpoints** (one above spec — `GET /api/v2/pm/top-bets/{bet_id}` counts separately from summary)

### Updated

- `apps/api/src/main.py` — added imports + `app.include_router()` calls for all 6 new route modules

### Tests Created

- `apps/api/tests/test_pm_endpoints.py` — 42 tests covering all routes; uses the same FakeSession pattern as `test_polymarket_routes.py`

---

## Endpoint Inventory

### pm_top_bets (`/api/v2/pm/top-bets`)
- `GET /` — list top bets, paginated; filterable by `venue` + `category` query params
- `GET /summary` — aggregate stats: total_active, avg_confidence, top_category, venues_active (**note: registered before `/{bet_id}` to avoid FastAPI routing ambiguity**)
- `GET /{bet_id}` — single bet with full scorer details (bull/bear args, reference class, etc.)
- `POST /{bet_id}/execute` — paper order execution; validates `amount_usd` (1–1000) + `side` (yes|no); returns `paper=true` (live execution deferred to Phase 16)
- `PUT /{bet_id}/feedback` — thumbs up/down; persists note into `PMTopBet.reasoning`

### pm_chat (`/api/v2/pm/chat`)
- `POST /` — accepts `{message, context_market_id?}`, returns `StreamingResponse` with `media_type="text/event-stream"`. Frame format: `data: {"chunk": "...", "done": false}\n\n`. Falls back to a stub generator when Claude SDK credentials are absent.
- `GET /history` — last 50 messages for user's deterministic session UUID (`uuid5(DNS, "pm-chat-{user_id}")`)
- `DELETE /history` — hard-delete all chat messages for session

### pm_agents (`/api/v2/pm/agents`)
- `GET /health` — reads `pm:agent:*:heartbeat` Redis keys; degrades gracefully when Redis is unavailable (falls back to DB `PMAgentActivityLog`). Status: `healthy` (key exists) | `degraded` (key missing, last activity <10 min) | `dead` (otherwise)
- `GET /activity` — last 100 `PMAgentActivityLog` rows
- `POST /cycle` — triggers `TopBetsAgent.run_cycle()` via `asyncio.ensure_future`; returns 202 with `{triggered: bool, message: str}`

### pm_research (`/api/v2/pm/research`)
- `POST /trigger` — schedules `AutoResearchAgent.run()` via `asyncio.ensure_future`; returns 202
- `GET /logs` — last 20 `PMStrategyResearchLog` rows

### pm_venues (`/api/v2/pm/venues`)
- `GET /` — lists `polymarket`, `robinhood_predictions`, `kalshi` (coming soon) with live probe of importability
- `GET /{venue}/markets` — calls `venue.fetch_markets()` via `venue_registry.get_venue()`; normalises outcomes to `yes_price`/`no_price`
- `POST /{venue}/sync` — upserts live markets into `pm_historical_markets` via `INSERT ... ON CONFLICT DO UPDATE`

### pm_pipeline (`/api/v2/pm/pipeline`)
- `POST /score` — on-demand pipeline scoring; tries `TopBetScorer.score_batch()`, falls back to stub when scorer is unavailable
- `GET /calibration` — last 10 `PMCalibrationSnapshot` rows; computes `accuracy = 1 - brier_score`
- `POST /feedback` — appends `[outcome:yes/no]` note to `PMTopBet.reasoning` for Brier tracking
- `GET /models` — all `PMModelEvaluation` rows ordered by `brier_score` ascending
- `GET /config` — reads `agents/polymarket/top_bets/config.yaml`; returns defaults if unavailable

---

## Key Design Decisions

1. **`/summary` before `/{bet_id}`** — FastAPI matches routes in registration order. The literal path `/summary` must be registered before the parameterised `/{bet_id}` to avoid it being matched as a UUID-looking bet_id. This is handled in the router definition order.

2. **SSE persistence pattern** — Because `StreamingResponse` is a generator, the assistant message cannot be committed to DB until the generator is exhausted. A separate `get_session()` call inside the generator tail handles this. If it fails, the stream still completes cleanly (warning only).

3. **LLM fallback** — `_generate_llm_response()` tries `shared.llm.claude_client.ClaudeClient` first; falls back to a deterministic stub generator. This keeps all tests green without requiring real credentials.

4. **Redis graceful degradation** — `pm_agents.py` wraps all Redis calls in try/except. If Redis is unavailable, health status is derived from `PMAgentActivityLog` timestamps only.

5. **Venue sync upsert** — Uses PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` (native dialect insert) to avoid read-before-write on large market sets.

6. **Paper-only execution** — `POST /execute` always returns `paper=true`. Live Robinhood execution is gated to Phase 16 per architecture spec §12.

---

## Files Touched

**Created:**
- `apps/api/src/routes/pm_top_bets.py`
- `apps/api/src/routes/pm_chat.py`
- `apps/api/src/routes/pm_agents.py`
- `apps/api/src/routes/pm_research.py`
- `apps/api/src/routes/pm_venues.py`
- `apps/api/src/routes/pm_pipeline.py`
- `apps/api/tests/test_pm_endpoints.py`
- `docs/dev/polymarket-tab/phase-15-6-notes.md`

**Modified:**
- `apps/api/src/main.py` — 7-line import block + 6 `include_router` calls appended after `polymarket_routes` and `analyst_routes`

---

## Tests Added

42 new tests in `apps/api/tests/test_pm_endpoints.py`:

| Group | Count | Coverage |
|-------|-------|----------|
| pm_top_bets | 10 | list, list with data, summary, single bet, 404, execute, invalid inputs, auth |
| pm_chat | 6 | history empty, history with data, delete, SSE stream, done frame, auth |
| pm_agents | 6 | health structure, health values, activity, empty activity, cycle, auth |
| pm_research | 4 | logs with data, empty logs, trigger, auth |
| pm_venues | 7 | list, structure, unknown venue 404, coming-soon 503, sync 404, sync 503, auth |
| pm_pipeline | 9 | score by question, missing input 422, calibration, empty calibration, models, empty models, config, feedback 404, auth |

**Result: 42 passed, 0 failed**

---

## Deviations from Spec

| Item | Spec | Implemented | Reason |
|------|------|-------------|--------|
| Feedback storage | "stored in PMTopBet" (no field specified) | Appended to `PMTopBet.reasoning` | No dedicated `user_feedback` field exists in the model; `reasoning` is the closest appropriate text field. Atlas should add a JSONB `user_feedback` column in Phase 15.8 if needed. |
| `POST /chat` assistant persistence | "Persist assistant response" | Persists via a secondary `get_session()` call in the generator tail | Cannot use the request's `DbSession` after `StreamingResponse` generator yields; secondary session is a correct pattern for SSE. |

---

## Open Risks

1. **`reasoning` field length** — PMTopBet.reasoning is Text (unbounded), but accumulating feedback notes without a dedicated column is not ideal for querying. Recommend adding `user_feedback: JSONB` column in Phase 15.8 migration.
2. **`asyncio.ensure_future` in `POST /cycle` and `POST /research/trigger`** — These fire-and-forget calls work correctly when the event loop is running, but the scheduled coroutine may be garbage-collected in edge cases. Phase 15.8 should wire these through the orchestrator's task queue instead.
3. **`pm_chat` secondary session** — The fallback `get_session()` import inside the SSE generator is an internal detail that bypasses the dependency injection system. This is acceptable for Phase 15 but should be refactored to a proper background task in Phase 16.
