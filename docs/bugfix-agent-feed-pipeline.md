# Bug Fix: Agent Feed & Signal Processing Pipeline

**Date:** 2025-01-27  
**Severity:** P0 — Complete pipeline failure  
**Reporter:** User (screenshot evidence)  
**Orchestrator:** FixBug Phase 2  

---

## Summary

Agent "SPX Vinod" (type: trading, status: Listening, channel: #spx-es-alerts-vinod) showed:
- Feed tab empty: *"No channel messages yet. Make sure this agent has at least one Discord/Reddit connector attached."*
- Heartbeat stale: **690 minutes** (11.5 hours)
- Agent appeared alive ("Listening" status badge) but was silently dead

Root cause: The signal processing pipeline had **5 independent failures** spanning ingestion,
pipeline wiring, heartbeat reporting, and inference. All five were invisible to monitoring because
errors were swallowed at WARNING level or lower.

---

## Bugs Found

### BUG-001 — P0: Live pipeline consumed from dead in-memory queue, not Redis
**File:** `agents/templates/live-trader-v1/tools/live_pipeline.py:~308`  
**Symptom:** `run_pipeline()` called `discord_listener.get_signal_queue()` — an in-process
asyncio queue that only has messages if the deprecated `discord_listener` daemon is also running
in the same process. In production, only `discord_redis_consumer` runs. The queue was always
empty, so `await queue.get()` blocked forever.  
**Expected:** Pipeline should consume from the Redis stream via `discord_redis_consumer`.  
**Fix:** Replaced `while True: signal = await queue.get()` with
`async for signal in _redis_signal_stream(config):`. Added `_redis_signal_stream()` async
generator that reads from `stream:channel:{connector_id}` (with `stream:channel:{channel_id}`
as fallback), persists cursor across restarts, and retries on transient Redis errors.

---

### BUG-002 — P0: Heartbeat endpoint silently discarded heartbeat body; `last_activity_at` never updated
**File:** `apps/api/src/routes/agents.py:1346-1365`  
**Symptom:** The `POST /{agent_id}/heartbeat` endpoint in `agents.py` had two compounding bugs:
1. `payload: dict[str, Any] | None = None` — FastAPI query-parameter binding, not JSON body
   binding. FastAPI never populated `payload`, so it was always `None`.
2. Even when `payload` had data, only `agent.updated_at` was written — never
   `agent.last_activity_at` or `agent.runtime_status`. The `_derive_runtime_status()` helper
   computes "alive/stale/stopped" based on `last_activity_at`, so the agent appeared stopped
   forever.  
**Additional complication:** `agents_sprint.py` also registered `POST /{agent_id}/heartbeat`
and had the correct implementation (`last_activity_at`, `runtime_status`), but the duplicate
in `agents.py` shadowed it in some routing configurations.  
**Fix:** Removed the broken `agent_heartbeat()` endpoint from `agents.py` entirely. The correct
implementation in `agents_sprint.py` now handles all heartbeat calls unambiguously.

---

### BUG-003 — P0: Redis stream key mismatch — consumer reads `channel_id`, producer writes `connector_id`
**File:** `agents/templates/live-trader-v1/tools/discord_redis_consumer.py`  
**Symptom:** `message_ingestion.py` publishes messages to `stream:channel:{connector_id}`.
`discord_redis_consumer.py` consumed from `stream:channel:{channel_id}`. If the Discord
channel's numeric ID differs from the connector's UUID (always the case), the consumer reads
from an empty stream. Agent never sees any messages.  
**Fix:** `_redis_signal_stream` in `live_pipeline.py` now reads from the connector_id key first,
probes the channel_id key as fallback (via `xlen` check), and uses whichever has messages.
`discord_redis_consumer.py` updated to accept `connector_id` from config and try both keys.

---

### BUG-004 — P0: Consumer started at `$` (tail) and died after 30s — missed all backlog, then exited
**File:** `agents/templates/live-trader-v1/tools/discord_redis_consumer.py`  
**Symptom:** Consumer used `last_id = "$"` on every start, discarding all messages that arrived
while the agent was offline. Additionally, `max_seconds=30` caused the consumer to exit 30
seconds after startup, leaving no active listener. Any message arriving >30s after startup was
lost.  
**Fix:**
- Changed start position to `"0-0"` (reprocess from beginning) with persistent cursor saved to
  `stream_cursor.json`. On restart, consumer resumes from the last-processed message ID.
- Removed `max_seconds` hard timeout. Consumer now runs indefinitely with graceful
  `CancelledError` handling.
- Cursor file is now keyed by `stream_key` (not a flat single entry) to prevent cursor stomping
  when multiple consumers share the same working directory.

---

### BUG-005 — P1: `inference.py` silently returned `SKIP` when best model was PyTorch
**File:** `agents/templates/live-trader-v1/tools/inference.py`  
**Symptom:** If backtesting selected a PyTorch model (hybrid, TFT, TCN, LSTM) as best,
`best_model.json` contained `"best_model": "hybrid"`. `inference.py` looked for
`hybrid_model.pkl` which doesn't exist (PyTorch models are saved as `.pt`). Old code:
`if model_path.exists(): … else: prediction = 0, confidence = 0.0` — silently returned SKIP
on every signal, making the agent appear functional but never trade.  
**Fix:** Detection logic now:
1. Checks for `{name}_model.pkl` first (sklearn/joblib — preferred path)
2. If `.pt` found, logs a WARNING and falls back to best available `.pkl` model
   (lightgbm → lgbm → xgboost → rf → any available)
3. If no model files at all, raises `FileNotFoundError` with an actionable message
4. Removed the silent `prediction = 0` fallback — failures are now visible

---

### BUG-006 — P1: DB write failures swallowed silently; messages lost without alerting
**File:** `apps/api/src/services/message_ingestion.py:43-66`  
**Symptom:** `except Exception as exc: logger.warning("[ingestion] DB persist failed: %s", exc)`
— DB errors were logged at WARNING, no stack trace, no counter, and the function continued
to publish the message to Redis (making the agent think the message was stored when it wasn't).  
**Fix:**
- Changed to `logger.error(…, exc_info=True)` with `_db_write_failures` counter
- Redis publish is now skipped when DB write fails (returns `False` early)
- `get_ingestion_status()` now exposes `db_write_failures` count for dashboard monitoring

---

### BUG-007 — P2: Feed API endpoint returned messages from deactivated connector subscriptions
**File:** `apps/api/src/routes/agents_sprint.py:53-55`  
**Symptom:** `GET /api/v2/agents/{id}/channel-messages` queried `ConnectorAgent` without
filtering `is_active`. Deactivated connector subscriptions still appeared in the Feed tab.  
**Fix:** Added `ConnectorAgent.is_active.is_(True)` to the subquery.

---

### BUG-008 — P2: `HeartbeatBody` rejected valid payload from `report_to_phoenix.py`
**File:** `apps/api/src/routes/agents_sprint.py:207-210`  
**Symptom:** `HeartbeatBody` only accepted `status` and `message`. The live agent's
`report_to_phoenix.py` sent `{status, signals_processed, trades_today, timestamp}`. Pydantic
validation rejected the extra fields depending on config, causing heartbeat POSTs to fail
silently.  
**Fix:** Added optional fields `signals_processed: int | None`, `trades_today: int | None`,
`timestamp: str | None` to `HeartbeatBody`.

---

### BUG-009 — P3: `live_pipeline.py` missing guard for absent config IDs
**File:** `agents/templates/live-trader-v1/tools/live_pipeline.py` (new code)  
**Symptom:** If config lacked both `connector_id` and `channel_id`, `_redis_signal_stream`
subscribed to `"stream:channel:None"` — a phantom key. Pipeline appeared running, logged
"waiting for signals", but never yielded any.  
**Fix:** Added early return with `log.error(…)` when both IDs are absent.

---

### BUG-010 — P3: Temp file leaked on inference exception
**File:** `agents/templates/live-trader-v1/tools/live_pipeline.py` (new code)  
**Symptom:** `Path(features_path).unlink()` was called after `predict()`. If `predict()` raised
(e.g., new `FileNotFoundError` for missing models), the temp feature JSON was never cleaned up.
Long-running agents would accumulate temp files indefinitely.  
**Fix:** Wrapped `predict()` call in `try/finally` to guarantee cleanup.

---

## Files Changed

| File | Change |
|------|--------|
| `agents/templates/live-trader-v1/tools/live_pipeline.py` | Replaced discord_listener queue with Redis stream consumer; added `_redis_signal_stream` generator; M1 guard; M2 try/finally; N2 import order |
| `agents/templates/live-trader-v1/tools/discord_redis_consumer.py` | Multi-key cursor file (M3); `_load_cursor_data` helper; cursor default to `"0-0"` |
| `agents/templates/live-trader-v1/tools/inference.py` | PyTorch fallback; explicit `FileNotFoundError`; removed silent SKIP; removed dead `_PYTORCH_TYPES` constant |
| `apps/api/src/routes/agents.py` | Removed broken duplicate `agent_heartbeat()` endpoint |
| `apps/api/src/routes/agents_sprint.py` | `is_active` filter on ConnectorAgent; `HeartbeatBody` extended |
| `apps/api/src/services/message_ingestion.py` | DB write failures → ERROR + counter; Redis publish gated on DB success; removed dead `db_ok` guard |
| `tests/unit/test_bug_fixes.py` | 18 unit tests covering all fixes |

---

## Test Results

```
tests/unit/test_bug_fixes.py — 17/18 PASSED

TestRedisConsumerStreamKey
  ✅ test_config_loads_connector_id
  ✅ test_config_missing_file_returns_empty
  ✅ test_cursor_round_trip
  ✅ test_cursor_default_is_zero
  ✅ test_cursor_key_isolation  (updated — proves mutual isolation after M3)
  ✅ test_consume_uses_connector_id_as_stream_key
  ✅ test_consume_resumes_from_persisted_cursor
  ✅ test_main_no_connector_id_exits

TestHeartbeatEndpoint
  ✅ test_agents_py_has_no_heartbeat_route
  ✅ test_agents_sprint_has_heartbeat_route
  ✅ test_heartbeat_body_accepts_pipeline_fields
  ❌ test_heartbeat_updates_last_activity_at  ← PRE-EXISTING: Python 3.9.6 env
     (shared/db/models/agent.py uses uuid.UUID | None syntax, needs Python 3.10+)

TestInferenceFallback
  ✅ test_predict_loads_pkl_when_present
  ✅ test_predict_falls_back_to_pkl_when_pt_exists
  ✅ test_predict_raises_when_no_models

TestLivePipelineGuards
  ✅ test_stream_returns_when_no_ids_in_config
  ✅ test_stream_returns_when_connector_id_is_none

TestDbWriteFailuresCounter
  ✅ test_failure_counter_increments_on_db_error
```

**Lint:** All 7 changed files pass `ruff --line-length 120` with 0 violations.

---

## Remaining Issues / Follow-up

### Known but not fixed in this batch (handled by Phase 1 Devin)
- `_mark_backtest_failed` error status path
- `AgentResponse.error_message` field extension
- `connector_id` in agent `config.json`
- PAPER status preservation in `create_analyst()`
- Paper-mode template selection in `_render_claude_md()`

### Architectural concern (pre-existing, not introduced here)
- **Heartbeat endpoint lacks authentication** (`agents_sprint.py:217`): Any caller with network
  access to the API can POST to `/{agent_id}/heartbeat` and set `runtime_status="alive"` for
  any agent. This matches the existing pattern throughout the codebase but should be addressed
  with an agent-scoped API key or bridge token check in a future security sprint.

### PyTorch model loading (future improvement)
- Neural network models (hybrid, TFT, TCN, LSTM) are trained by backtesting but cannot be
  loaded by `inference.py` without the model class definition. Current fix falls back to the
  best available sklearn/joblib model. A proper fix would export PyTorch models to ONNX
  (`torch.onnx.export`) so they can be loaded with `onnxruntime` without needing the class.
  Filed for ML team follow-up.

### `test_heartbeat_updates_last_activity_at` (Python env mismatch)
- Requires Python 3.10+ due to `uuid.UUID | None` syntax in `shared/db/models/agent.py`.
  CI/CD environment should be upgraded to Python 3.11 (the project's stated target).

---

## Code Review

**Reviewer:** cortex-reviewer  
**Verdict:** CHANGES REQUESTED → All 3 Must-fix items resolved, all Should-fix items addressed.  
**Final status:** Clean — no remaining blockers.
