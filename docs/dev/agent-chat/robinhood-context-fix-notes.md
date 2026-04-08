# Agent Chat — Robinhood Context Fix

**Phase:** 1 + 2 combined  
**Date:** 2026-04-08  
**Bug:** Chat tab on live approved agents replied "I don't have a live Robinhood connection"

---

## What Changed

### Root Cause
`chat_responder.py` spawned an isolated Claude Code session with only `["Bash", "Read"]` tools and no MCP config or credentials. The live agent's Robinhood MCP wiring (written by `agent_gateway._write_claude_settings`) only existed in the agent's own persistent workdir, not in the ephemeral per-message chat workdir.

---

## Files Touched

| File | Type | Description |
|------|------|-------------|
| `apps/api/src/services/robinhood_context_fetcher.py` | **NEW** | Phase 1: fetches live portfolio data via robin_stocks before spawning chat session |
| `apps/api/src/services/chat_responder.py` | **MODIFIED** | Phase 1+2: injects live portfolio into context, wires MCP tools for live agents |
| `tests/unit/test_robinhood_context_fetcher.py` | **NEW** | 18 unit tests covering fetcher + chat_responder injection |

---

## Phase 1 — Context Injection

New service `RobinhoodContextFetcher`:
- Checks `agent.status` against `LIVE_AGENT_STATUSES = {"RUNNING", "APPROVED"}` — no-ops for paper/pending agents
- Loads `agent.config["robinhood_credentials"]` (stored plaintext in agent config JSON)
- Calls `robin_stocks.robinhood` in a `run_in_executor` thread (blocking I/O off event loop):  `rh.account.get_open_stock_positions()` + `rh.profiles.load_portfolio_profile()`
- Uses `pyotp.TOTP(totp_secret).now()` when `totp_secret` is present
- Always calls `rh.authentication.logout()` in `finally` block
- Returns `LivePortfolioContext` dataclass with `.to_dict()` for JSON serialization
- **Graceful fallback mandatory**: any exception → `error` field set, no crash, chat continues

In `chat_responder._prepare_workdir`:
- Accepts `live_portfolio: dict | None` parameter
- Merges `live_portfolio` into `agent_context.json` under key `"live_portfolio"` when not None

In `chat_responder._build_prompt`:
- New `has_live_portfolio` flag → adds `## LIVE Portfolio Data` section telling Claude to use the context data and NOT say it lacks a connection
- If `live_portfolio.error` is set, Claude reports the actual error message

---

## Phase 2 — MCP Access in Chat Session

In `chat_responder._prepare_workdir` (when `rh_creds` provided):
- Calls `agent_gateway._write_claude_settings(work_dir, rh_creds, paper_mode=False)` → writes `.claude/settings.json` with Robinhood MCP server config
- Copies `robinhood_mcp.py` from `agents/templates/live-trader-v1/tools/` into `work_dir/tools/`

In `chat_responder.respond_to_chat`:
- Detects live agent: `agent_status in {"RUNNING", "APPROVED"}` AND has username+password creds
- Adds read-only MCP tools to `allowed_tools`:
  ```python
  ["Bash", "Read", "mcp__robinhood__robinhood_login", "mcp__robinhood__get_positions",
   "mcp__robinhood__get_account", "mcp__robinhood__get_quote",
   "mcp__robinhood__get_account_snapshot", "mcp__robinhood__get_nbbo",
   "mcp__robinhood__get_watchlist", "mcp__robinhood__get_order_status"]
  ```
- **Order-placement tools deliberately excluded** from chat — read-only only
- Adds system prompt section instructing Claude to call `robinhood_login` first

---

## Tests Added

`tests/unit/test_robinhood_context_fetcher.py` — 18 tests:

| Class | Tests |
|-------|-------|
| `TestRobinhoodContextFetcherNonLive` | 8 — non-live statuses return empty context without error |
| `TestRobinhoodContextFetcherGracefulFallback` | 3 — login error, positions error, missing package |
| `TestRobinhoodContextFetcherPositionMapping` | 2 — position dict shape, to_dict serializable |
| `TestChatResponderLivePortfolioInjection` | 5 — workdir context file, paper agent no-op, prompt sections |

**Key mock technique:** `_rh_mock(mock_rh)` sets `parent_package.robinhood = mock_rh` AND `sys.modules["robin_stocks.robinhood"] = mock_rh` — needed because `import robin_stocks.robinhood as rh` returns the parent package's `.robinhood` attribute, not the raw sys.modules entry.

---

## Deviations from Plan

None — implementation follows the plan exactly. Phase 1 (context injection) and Phase 2 (MCP wiring) were combined into a single PR since they touch the same function.

---

## Open Risks

1. **robin_stocks login latency**: Each chat message on a live agent now makes a synchronous Robinhood API call before spawning Claude. Login + positions takes ~2-4s. The existing `CHAT_REPLY_TIMEOUT_SECONDS=120` provides ample headroom, but the user will notice slightly longer response times.

2. **TOTP timing**: `pyotp.TOTP.now()` generates a code valid for 30s. If the robin_stocks login takes longer than the TOTP window, authentication may fail. The `error` field in `LivePortfolioContext` will surface this gracefully — Claude will report the error rather than silently failing.

3. **Credential exposure via error messages**: The `_fetch_sync` catches all exceptions and stores `str(exc)` in the `error` field. If robin_stocks ever includes credentials in exception messages, they would appear in `agent_context.json` (only in the ephemeral workdir, not persisted). Risk is low but worth monitoring.

4. **Pre-existing test suite failures**: 34 test collection errors in Python 3.9 environment due to `A | B` union syntax in other modules. These are pre-existing and unrelated to this fix.

---

## Cortex Fix Round

**Date:** 2026-04-08 (post-review)
**Blockers resolved:** 2 (CRITICAL + MUST-FIX)

### Blocker 1 Fixed — Plaintext credentials persist on disk forever (CRITICAL)

**Root cause:** `_prepare_workdir` writes `.claude/settings.json` with plaintext `RH_USERNAME`, `RH_PASSWORD`, `RH_TOTP_SECRET` into `CHAT_SESSIONS_DIR/<agent_id>/<stamp>/`. There was no cleanup — workdirs accumulated forever.

**Fix applied in `chat_responder.respond_to_chat`:**
- Wrapped the entire block from `work_dir = _prepare_workdir(...)` through the session execution in a `try/finally`
- `finally` calls `shutil.rmtree(work_dir, ignore_errors=True)` — fires whether the session succeeds, times out, or the SDK import fails
- `except Exception: pass` inside the `finally` ensures cleanup failure can never propagate and break the chat response

### Blocker 2 Fixed — `str(exc)` may embed credentials (MUST-FIX)

**Root cause:** Three sites used `error=str(exc)` with no sanitization. If `rh.login(username, password)` raised an HTTP 401 that echoed the request body, credentials would flow into `agent_context.json`.

**Fix applied:**
- Added `_sanitize_error(exc, creds=None)` as a module-level helper in `robinhood_context_fetcher.py`:
  - Formats as `ClassName: message` (caps message at 200 chars)
  - Replaces any credential value (username, password, totp_secret) found in the message with `***`
- `robinhood_context_fetcher.py` line 73 (outer fallback): `_sanitize_error(exc)` — no creds in scope
- `robinhood_context_fetcher.py` line 181 (`_fetch_sync` inner catch): `_sanitize_error(exc, creds)` — creds in scope
- `chat_responder.py` live-portfolio error fallback: inline-imports `_sanitize_error` and uses `_sanitize_error(fetch_exc)` — no creds available at that call site

### Tests Added (6 new)

| Class | Test | Asserts |
|-------|------|---------|
| `TestWorkdirCleanup` | `test_workdir_cleaned_up_after_session` | `work_dir` does not exist on disk after `respond_to_chat` returns, even when `claude_agent_sdk` is unavailable (early-return path) |
| `TestSanitizeError` | `test_error_sanitization_removes_credentials` | password `"hunter2"` absent from output; `***` present |
| `TestSanitizeError` | `test_error_sanitization_caps_length` | output ≤ `len("ClassName: ") + 200` chars |
| `TestSanitizeError` | `test_error_sanitization_includes_type_prefix` | output starts with `ClassName:` |
| `TestSanitizeError` | `test_error_sanitization_scrubs_username_and_totp` | username and totp_secret values scrubbed |
| `TestSanitizeError` | `test_error_sanitization_no_creds_is_safe` | works correctly when called without creds arg |

All 24 tests pass. Ruff reports no issues.
