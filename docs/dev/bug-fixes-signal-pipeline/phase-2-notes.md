# Phase 2 Bug-Fix Notes — Signal Pipeline Restoration

**Phase**: Bug-fix batch (P0/P1/P2)
**Date**: 2025-06-01
**Agent**: SPX Vinod heartbeat 690m stale + Feed tab "No channel messages yet"

---

## Summary

8 fixes across 6 production files + 1 new test file. All ruff checks pass;
15 unit tests pass.

---

## FIX 1 (P0) — `discord_redis_consumer.py`

**Problem**: Consumer read from `stream:channel:{channel_id}` but ingestion
publishes to `stream:channel:{connector_id}`. Cursor was `"$"` (miss backlog).
30-second hard timeout meant agent stopped listening after 30 s every loop.

**What changed**:
- The file was already updated by Phase 1 to the correct implementation:
  - Uses `stream:channel:{connector_id}` as the primary stream key
  - Falls back to `stream:channel:{channel_id}` for backward compatibility
  - Runs indefinitely with SIGTERM/SIGINT shutdown flag
  - Cursor persists to `stream_cursor.json` keyed by stream_key so restarts resume
- Updated docstring to document the dual-key resolution and cursor behaviour
- `--max-seconds` flag kept as no-op for backward compatibility with old templates

**Files touched**: `agents/templates/live-trader-v1/tools/discord_redis_consumer.py`

---

## FIX 2 (P0) — `live_pipeline.py`

**Problem**: `run_pipeline()` imported `discord_listener.get_signal_queue()` (old
in-memory queue — not wired up). Signals were never delivered.

**What changed**:
- Removed `from discord_listener import get_signal_queue`
- Added `_redis_signal_stream(config)` — an async generator that:
  - Resolves `stream:channel:{connector_id}` / fallback `stream:channel:{channel_id}`
  - Calls `_load_cursor(stream_key)` / `_save_cursor(stream_key, last_id, count)` (Phase 1 API)
  - Yields one signal dict per Redis entry, indefinitely
- `run_pipeline()` now does `async for signal in _redis_signal_stream(config):`

**Files touched**: `agents/templates/live-trader-v1/tools/live_pipeline.py`

---

## FIX 3 (P0) — `agents.py` heartbeat duplicate removed

**Problem**: `agents.py` (registered first in `main.py`) had its own
`/{agent_id}/heartbeat` endpoint that shadowed `agents_sprint.py`'s better
implementation. The shadow endpoint did NOT update `last_activity_at` or
`runtime_status`, so the UI showed staleness 690m.

**What changed**:
- Deleted `agent_heartbeat()` function from `apps/api/src/routes/agents.py`
- `agents_sprint.py`'s `post_heartbeat()` now handles all heartbeat calls
  (it already sets `last_activity_at` and `runtime_status = "alive"`)

**Files touched**: `apps/api/src/routes/agents.py`

---

## FIX 4 (P0) — `HeartbeatBody` field alignment

**Problem**: `HeartbeatBody` in `agents_sprint.py` only accepted `status` and
`message`. The live-trader tool sends `signals_processed`, `trades_today`,
`timestamp` — these were silently dropped, causing Pydantic validation warnings
and potential 422 responses on strict validators.

**What changed**:
- Added optional fields to `HeartbeatBody`:
  - `signals_processed: int | None = None`
  - `trades_today: int | None = None`
  - `timestamp: str | None = None`

**Files touched**: `apps/api/src/routes/agents_sprint.py`

---

## FIX 5 (P1) — `inference.py` PyTorch model fallback

**Problem**: When `best_model.json` names a PyTorch model (lstm, tft, tcn,
hybrid), `inference.py` checked for `{name}_model.pkl`, didn't find it, and
silently returned `prediction=0/SKIP` with `confidence=0.0`.

**What changed**:
- Check `{name}_model.pkl` first (existing behaviour)
- If not found, check `{name}_model.pt`
- If `.pt` found → search for sklearn/lgbm fallback in preference order:
  `lightgbm → lgbm → xgboost → rf → random_forest → logistic → any *.pkl`
- Log WARNING clearly when falling back
- If neither `.pkl` nor `.pt` exists → raise `FileNotFoundError` with clear message
- `used_model_name` tracked through fallback path and returned in result dict

**Files touched**: `agents/templates/live-trader-v1/tools/inference.py`

---

## FIX 6 (P1) — `message_ingestion.py` silent DB error

**Problem**: DB write failures in `_persist_message()` were logged as WARNING
and swallowed; message was still published to Redis (false positive — agent
thinks message is persisted when it isn't).

**What changed**:
- Changed `logger.warning(...)` to `logger.error(..., exc_info=True)` for full traceback
- Added module-level `_db_write_failures: int = 0` counter
- `_persist_message()` now returns `bool` (True = DB+Redis OK, False = skip Redis)
- Redis publish and trigger fan-out only run when `db_ok is True`
- Counter exposed in `get_ingestion_status()`
- Redis publish error upgraded from WARNING to ERROR with exc_info

**Files touched**: `apps/api/src/services/message_ingestion.py`

---

## FIX 7 (P2) — Feed endpoint `is_active` filter

**Problem**: `get_channel_messages()` returned messages from ALL `connector_agents`
rows including deactivated ones, which could show stale/irrelevant feed entries.

**What changed**:
- Added `ConnectorAgent.is_active.is_(True)` to the connector subquery
- (`and_` was already imported in the file)

**Files touched**: `apps/api/src/routes/agents_sprint.py`

---

## FIX 8 (P2) — CLAUDE.md.jinja2 contradiction

**Problem**: Template referenced `discord_listener.py` alongside Redis consumer.

**Resolution**: Template was already clean (Phase 1 updated it). No change needed.
Verified: `grep discord_listener CLAUDE.md.jinja2` → no matches.

---

## Tests Added

**File**: `tests/unit/test_bug_fixes.py` — 15 tests, all passing

| Class | Tests | What it covers |
|-------|-------|----------------|
| `TestRedisConsumerStreamKey` | 8 | `_config()`, `_load_cursor()`, `_save_cursor()`, `consume()` stream key selection, cursor resume, `main()` exit |
| `TestHeartbeatEndpoint` | 4 | agents.py has no heartbeat, sprint has it, HeartbeatBody fields, last_activity_at updated |
| `TestInferenceFallback` | 3 | .pkl loaded normally, .pt→fallback.pkl, no-models raises FileNotFoundError |

---

## Lint

All 7 changed files pass `ruff check` (line-length 120, target py311).
Pre-existing E402/E501 violations in `agents.py` are unchanged.

---

## Open Risks

- `live_pipeline.py` `_redis_signal_stream` imports `discord_redis_consumer` at
  call time (inside the async generator body). If the tools dir isn't on
  `sys.path` when launched, this will fail at runtime. Mitigation: CLAUDE.md
  run loop launches from the agent workspace where tools/ is adjacent.
- `_db_write_failures` counter is in-process only; resets on container restart.
  For production visibility wire it into the Prometheus metrics endpoint.
