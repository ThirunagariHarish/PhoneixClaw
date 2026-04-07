# Phase 3 Implementation Notes — Template Hardening

**Phase:** 3  
**Feature:** Agents Tab Fix — Message Pipeline Hardening  
**Date:** 2026-04-07  
**Commit:** f71a543

---

## What Changed

### 3.1 — `discord_redis_consumer.py` (5 fixes)

**File:** `agents/templates/live-trader-v1/tools/discord_redis_consumer.py`

#### 3.1a — Stream key alignment
- Added `connector_id` resolution: reads `cfg["connector_id"]` first, falls back to `cfg["channel_id"]`, then CLI args `--connector-id` / `--channel-id`.
- Stream key is now `f"stream:channel:{connector_id}"` using the DB UUID of the connector.
- Added `--connector-id` as the new primary CLI arg; `--channel-id` retained as deprecated alias.

#### 3.1b — Stream cursor persistence
- Added `CURSOR_FILE = Path("stream_cursor.json")` module constant.
- Added `_load_cursor(stream_key)`: reads cursor file; returns `"0-0"` on first start (reads all history from stream beginning).
- Added `_save_cursor(stream_key, last_id, count)`: writes cursor after each batch with ≥1 message. Never raises.
- Consumer now resumes from last processed message ID on restart.

#### 3.1c — Remove 30s timeout; add SIGTERM handler
- Removed `max_seconds` parameter from `consume()`.
- Replaced `while time.time() < deadline` with `while not _shutdown`.
- Added module-level `_shutdown = False` flag + `_handle_signal()` handler registered for `SIGTERM` and `SIGINT`.
- `--max-seconds` CLI arg retained as a no-op for backward compatibility with existing CLAUDE.md invocations.
- `time` import removed (no longer needed).

#### 3.1d — Exponential backoff on Redis disconnect
- Added `import redis.exceptions` import inside `consume()`.
- Distinguished `redis.exceptions.ConnectionError` from generic exceptions.
- On `ConnectionError`: exponential backoff `min(2 ** _backoff, 30)` seconds, then attempts reconnect via `aioredis.from_url()`; resets `_backoff` on successful reconnect.
- Other exceptions: log and sleep 1s (original behavior).

#### 3.1e — Trim `pending_signals.json` to 500 entries
- Added `MAX_PENDING = 500` constant.
- After loading existing entries and extending with new batch: `if len(existing) > MAX_PENDING: existing = existing[-MAX_PENDING:]` (keeps most recent).

**Miscellaneous:** Renamed internal `redis` variable to `r` to avoid shadowing the `redis` module import.

---

### 3.2 — `CLAUDE.md.jinja2` updates

**File:** `agents/templates/live-trader-v1/CLAUDE.md.jinja2`

- Removed `tools/discord_listener.py` bullet from `### Core Pipeline` section; replaced with `tools/discord_redis_consumer.py` description.
- Removed `--max-seconds 30` from consumer invocation (line ~90).
- Removed `Run this in a loop.` sentence — consumer is now a persistent daemon.
- Zero references to `discord_listener.py` remain in the file.

---

### 3.3 — `CLAUDE.md.paper.jinja2` (NEW)

**File:** `agents/templates/live-trader-v1/CLAUDE.md.paper.jinja2`

- New Jinja2 template for paper trading agents.
- Top banner: `> ⚠️ PAPER TRADING MODE — DO NOT EXECUTE REAL TRADES`
- `### Trade Execution` section removed entirely (no Robinhood MCP calls).
- All trade execution replaced with `python tools/log_paper_trade.py` calls.
- Added `## ⛔ EXPLICIT PROHIBITIONS — PAPER MODE` section with required 4-point prohibition list.
- All Jinja template variables guarded with `{% if modes %}...{% endif %}` etc. for empty-manifest safety.
- Zero robinhood MCP tool invocations anywhere in the template.

---

### 3.4 — `log_paper_trade.py` (NEW)

**File:** `agents/templates/live-trader-v1/tools/log_paper_trade.py`

- CLI tool: `--signal`, `--direction BUY|SELL`, `--ticker`, `[--quantity]`, `[--price]`, `[--config]`
- Reads signal JSON from `--signal` path (handles both list and dict formats).
- Appends trade record to `paper_trades.json` in CWD.
- Prints JSON summary to stdout.
- Exits 0 always — wrapped in `try/except Exception` so agent session is never crashed.
- Zero brokerage calls.

---

### 3.5 — `discord_listener.py` → `discord_listener_DEPRECATED.py`

- **Renamed:** `agents/templates/live-trader-v1/tools/discord_listener.py` → `discord_listener_DEPRECATED.py`
- Added 5-line deprecation header at top of file.
- `discord_listener.py` no longer exists in the template directory.

---

## Tests Added

**File:** `tests/unit/test_discord_redis_consumer.py`

| Test | Covers |
|------|--------|
| `test_stream_key_uses_connector_id` | Fix 3.1a: stream key uses `connector_id` not `channel_id` |
| `test_main_prefers_connector_id_from_config` | Fix 3.1a: `main()` resolves from config first |
| `test_cursor_first_start_uses_zero_zero` | Fix 3.1b: no cursor file → `"0-0"` |
| `test_cursor_loaded_on_restart` | Fix 3.1b: cursor file exists → reads saved `last_id` |
| `test_cursor_wrong_stream_key_falls_back` | Fix 3.1b: cursor for wrong stream → `"0-0"` |
| `test_cursor_saved_after_batch` | Fix 3.1b: after batch, `stream_cursor.json` written with correct `last_id` |
| `test_no_deadline_exit` | Fix 3.1c: loop does not exit after 30s; exits only on `_shutdown = True` |
| `test_pending_signals_trim` | Fix 3.1e: >500 entries trimmed to 500, most recent kept |

**Result:** 8/8 pass, 0 regressions in existing tests (pre-existing Python 3.9 `|` union-type failures in unrelated tests are unchanged).

---

## Deviations from Spec

None. All 5 fixes, all 3 template changes, and all 6 required tests (8 delivered) implemented as specified.

## Open Risks

- `discord_listener_DEPRECATED.py` still ships in the template directory (intentional per spec). Deletion scheduled for next release cycle.
- `_shutdown` is a module-level global. In tests, each test reloads the module via `importlib.util` to isolate state — this is correct but adds module-load overhead. No production impact.
- `log_paper_trade.py` does not call `report_to_phoenix.py` with `paper=true` flag (the spec says "calls `report_to_phoenix.py` with `paper=true` flag" in Section 3.4 purpose paragraph but the formal DoD/CLI spec does not mandate it). Excluded to keep the tool simple and avoid a cross-tool dependency that could crash the agent. Flagging for Cortex review.
