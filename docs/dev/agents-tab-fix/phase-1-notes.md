# Phase 1 Implementation Notes — Backend Fixes

**Phase:** 1 (Backend Fixes)  
**Feature:** Agents Tab Bug-Fix + Message Pipeline Hardening  
**Date:** 2025-01-28  
**Author:** Devin  
**Tech Plan:** `docs/tech-plan-agents-tab-fix.md`

---

## Summary of Changes

### 1.1 — Fix `_mark_backtest_failed()` in `agent_gateway.py`

**File:** `apps/api/src/services/agent_gateway.py`  
**Lines changed:** ~2116–2117

- Changed `agent.status = "CREATED"` → `agent.status = "ERROR"` (the bug: wrong status on backtest failure)
- Added `agent.error_message = error_msg` in the `if agent:` block to write the human-readable error into the new DB column (added by Phase 4 migration 032)

**Also:** in `_mark_backtest_completed()` (~line 2084), added `agent.error_message = None` to clear any prior error on retry success.

---

### 1.2 — Extend `AgentResponse` with `error_message` field

**File:** `apps/api/src/routes/agents.py`  
**Lines changed:** ~65, ~110

- Added `error_message: str | None = None` to `AgentResponse` Pydantic model
- Added `error_message=a.error_message` mapping in `AgentResponse.from_model()`
- The new field is nullable and backward-compatible — all existing API clients receive `"error_message": null` unless an agent is in `ERROR` state

---

### 1.3 — Add `connector_id` and `paper_mode` to analyst `config.json`

**File:** `apps/api/src/services/agent_gateway.py`  
**Function:** `_prepare_analyst_directory()` (~line 708–725)

- After building `agent_config` dict, extracts `connector_id` from `agent.config.get("connector_ids")`:
  ```python
  connector_ids = agent.config.get("connector_ids") or [] if agent.config else []
  primary_connector_id = connector_ids[0] if connector_ids else ""
  agent_config["connector_id"] = primary_connector_id
  ```
  Empty string is correct for backtest/trend agents (Phase 3 consumer will log a warning and exit cleanly).
- Added `agent_config["paper_mode"] = agent.status == "PAPER"`
- Wrapped Robinhood credential injection in `if rh_creds and not agent_config["paper_mode"]:` guard — paper agents must never receive broker credentials

---

### 1.4 — Fix paper-agent status preservation in `create_analyst()`

**File:** `apps/api/src/services/agent_gateway.py`  
**Function:** `create_analyst()` (~line 489)

- Replaced unconditional `agent.status = "RUNNING"` with:
  ```python
  if agent.status != "PAPER":
      agent.status = "RUNNING"
  # PAPER agents: status stays "PAPER"; only worker_status changes
  ```
- Added `trading_mode="paper" if agent.status == "PAPER" else "live"` to the `AgentSession(...)` constructor call, writing the new Phase 4 column

---

### 1.5 — Select paper-mode CLAUDE.md template in `_render_claude_md()`

**File:** `apps/api/src/services/agent_gateway.py`  
**Function:** `_render_claude_md()` (~line 737)

- Added `is_paper = agent.status == "PAPER"` and `template_name = "CLAUDE.md.paper.jinja2" if is_paper else "CLAUDE.md.jinja2"`
- Updated template path construction and `env.get_template()` call to use `template_name`
- Fallback for missing template now writes a mode-appropriate minimal content:
  - Paper mode: includes the safety banner `"⚠️ PAPER TRADING MODE — DO NOT EXECUTE REAL TRADES"` (AC2.5.1)
  - Live mode: existing fallback content unchanged
- Note: `CLAUDE.md.paper.jinja2` does not exist yet — Phase 3 creates it. If the file is absent the safe fallback content is used (no crash)

---

## Tests Added

**New file:** `tests/unit/test_agent_gateway_error_path.py`

| Test | Assertion |
|------|-----------|
| `TestMarkBacktestFailed::test_mark_backtest_failed_sets_error_status` | `agent.status == "ERROR"` after call |
| `TestMarkBacktestFailed::test_mark_backtest_failed_writes_error_message` | `agent.error_message == error_msg` |
| `TestMarkBacktestFailed::test_mark_backtest_failed_sets_backtest_status_failed` | `bt.status == "FAILED"` |
| `TestMarkBacktestFailed::test_mark_backtest_failed_commits` | `db.commit()` called once |
| `TestMarkBacktestCompleted::test_mark_backtest_completed_clears_error` | `agent.error_message is None` |
| `TestMarkBacktestCompleted::test_mark_backtest_completed_sets_backtest_complete_status` | `agent.status == "BACKTEST_COMPLETE"` |
| `TestPrepareAnalystDirectory::test_prepare_analyst_dir_includes_connector_id` | `config.json` has `connector_id` key |
| `TestPrepareAnalystDirectory::test_prepare_analyst_dir_empty_connector_ids_uses_empty_string` | `connector_id == ""` when no connectors |
| `TestPrepareAnalystDirectory::test_prepare_analyst_dir_paper_mode_no_robinhood` | No `robinhood_credentials` in paper config |
| `TestPrepareAnalystDirectory::test_prepare_analyst_dir_live_agent_receives_robinhood` | Live agent receives credentials |
| `TestPrepareAnalystDirectory::test_prepare_analyst_dir_paper_mode_flag_true` | `paper_mode == True` for PAPER agents |
| `TestCreateAnalystPaperStatus::test_create_analyst_preserves_paper_status` | `agent.status == "PAPER"` unchanged |
| `TestCreateAnalystPaperStatus::test_create_analyst_live_agent_becomes_running` | `agent.status == "RUNNING"` for live |
| `TestCreateAnalystPaperStatus::test_create_analyst_paper_session_has_trading_mode_paper` | `AgentSession.trading_mode == "paper"` |
| `TestCreateAnalystPaperStatus::test_create_analyst_live_session_has_trading_mode_live` | `AgentSession.trading_mode == "live"` |
| `TestAgentResponseErrorMessage::test_error_message_populated_when_error_status` | `AgentResponse.error_message` populated |
| `TestAgentResponseErrorMessage::test_error_message_is_none_when_running` | `error_message is None` for live |
| `TestAgentResponseErrorMessage::test_error_message_field_declared_on_agent_response` | Field exists in `model_fields` |

**Result:** 17/17 pass on Python 3.13 (project runtime)

**Note on test environment:** The project requires Python 3.11+ (model files use `X | Y` union syntax at runtime). Tests run with `python3.13`. The system Python 3.9 cannot load these tests; this is a pre-existing constraint across all model-importing tests in the project (see `test_migration_031.py` for the same pattern).

---

## Files Touched

| File | Change |
|------|--------|
| `apps/api/src/services/agent_gateway.py` | 1.1, 1.3, 1.4, 1.5 logic changes |
| `apps/api/src/routes/agents.py` | 1.2 `AgentResponse.error_message` field |
| `tests/unit/test_agent_gateway_error_path.py` | New unit test file (17 tests) |
| `docs/dev/agents-tab-fix/phase-1-notes.md` | This file |

---

## Deviations from Tech Plan

None. All five sub-tasks implemented exactly as specified.

---

## Open Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| `CLAUDE.md.paper.jinja2` does not exist | Low | Robust fallback with safety banner; addressed in Phase 3 |
| Paper mode forces `current_mode = "paper"` via existing credential-check logic | Low | The `agent_config["paper_mode"]` flag is the authoritative signal; the credential check path is independently safe |
| `connector_id` empty string for backtest agents | Low | Consumer in Phase 3 will log warning and exit cleanly per Atlas design |
