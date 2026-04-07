# PRD: Agents Tab Bug-Fix + Message Pipeline Hardening

**Status:** Draft  
**Author:** Nova (PM)  
**Date:** 2025-01-28  
**Stakeholders:** Atlas (Architect), Devin (Developer), Cortex (Reviewer)

---

## 1. Problem Statement

The Agents tab is the primary surface for managing the full agent lifecycle — from creation through backtesting, paper trading, and live promotion. Two clusters of bugs currently make this lifecycle non-functional for end users. First, the agent creation wizard hard-blocks users from creating a backtesting agent unless they have pre-configured Discord connectors and channels, even though backtesting does not require live Discord connectivity; and when the Claude Code SDK is unavailable or misconfigured, the resulting failure is silent — the agent hangs in `BACKTESTING` status indefinitely with no actionable feedback in the UI. Second, once an agent is approved and enters paper trading mode, it never receives Discord channel messages: the ingestion service publishes to a Redis stream keyed by `connector_id`, while the agent-side consumer subscribes to a stream keyed by `channel_id`; the consumer also starts at the latest stream offset (missing all backlogged messages) and exits after 30 seconds, making reliable message delivery structurally impossible. Together these two bugs prevent users from completing any agent lifecycle end-to-end.

---

## 2. Goals

What success looks like — all items are measurable via the acceptance criteria in Section 5.

| # | Goal |
|---|------|
| G1 | A user can create and launch a backtesting agent through the 3-step wizard with no pre-existing Discord connector. |
| G2 | When the Claude Code SDK is unavailable, the UI displays a human-readable error on the agent card within one polling cycle (≤ 10 s); the agent does **not** remain stuck in `BACKTESTING` forever. |
| G3 | A paper-trading agent receives 100 % of Discord messages published to its configured channel from the moment it is started, with no missed messages due to stream-key mismatch or offset positioning. |
| G4 | The paper-trading message consumer remains alive for the full lifetime of the agent session — it does not terminate after 30 seconds. |
| G5 | There is exactly one authoritative Discord-to-agent message path in the `live-trader-v1` template; the ambiguous legacy tool is removed or clearly inert. |
| G6 | Paper trading and live trading agent sessions are driven by distinct instruction sets so that paper mode cannot accidentally execute real trades. |

---

## 3. Out of Scope

The following are explicitly **not** changing in this work item:

- **UX redesign** — the 3-step wizard layout, step labels, and visual design are frozen.
- **Message ingestion architecture** — the centralized `message_ingestion.py` daemon and its Redis fan-out strategy are not being re-architected; only the stream key alignment and consumer lifecycle are being fixed.
- **Backtesting ML pipeline** — the heavy ML pipeline itself is not being refactored; the only change is gating it correctly so it does not fire prematurely or silently fail.
- **New connector types** — no new connector integrations.
- **Agent promotion to live trading** — the `/promote` endpoint and live trading flow are out of scope for this fix cycle (the endpoint exists and is separately verified as functional).
- **UI component library or dashboard theming.**

---

## 4. Success Metrics

| Metric | Baseline (current) | Target |
|--------|-------------------|--------|
| % of agent creation attempts that reach `BACKTESTING` status without a pre-existing connector | ~0 % (hard-blocked by wizard) | 100 % |
| Time-to-visible-error when Claude SDK is unavailable | Indefinite (no UI signal) | ≤ 10 s (within one polling cycle) |
| % of paper-trading Discord messages delivered to agent consumer | ~0 % (stream key mismatch) | ≥ 99 % |
| Paper-trading consumer uptime during active session | ≤ 30 s per invocation | Session lifetime (persistent) |
| Competing Discord tool files in `live-trader-v1/tools/` | 2 (`discord_listener.py` + `discord_redis_consumer.py`) | 1 authoritative file |

---

## 5. User Stories

### Problem Cluster 1: Agent Creation

---

#### Story 1.1 — Create a backtesting agent without a pre-existing Discord connector
**As a** trader who has not yet configured a Discord connector,  
**I want** to create a backtesting agent through the 3-step wizard using only a name and agent type,  
**so that** I can evaluate agent strategy performance before connecting a live Discord channel.

**Priority:** P0  
**File refs:** `apps/dashboard/src/pages/Agents.tsx:1314-1327`

**Acceptance Criteria:**

| # | Given | When | Then |
|---|-------|------|------|
| AC1.1.1 | User has zero configured connectors | User enters a name and selects any non-`trading` type | The "Next" button on wizard step 0 is enabled |
| AC1.1.2 | User completes the 3-step wizard with no connector | User clicks "Create Agent" on step 3 | Agent record is created in DB with status `BACKTESTING`; no 400/422 error is returned |
| AC1.1.3 | Agent type is `trading` | User has not selected a Discord connector + channel | "Next" on step 0 remains disabled (existing behaviour preserved for trading type) |

**Dependencies:** None — frontend-only logic change.

---

#### Story 1.2 — Receive visible error feedback when Claude Code SDK is unavailable
**As a** trader,  
**I want** to see a clear error message on the agent card when the Claude SDK cannot start the backtesting run,  
**so that** I know the issue requires admin action (e.g., install the SDK, set `ANTHROPIC_API_KEY`) and do not wait indefinitely.

**Priority:** P0  
**File refs:** `apps/api/src/services/agent_gateway.py:234-244`

**Acceptance Criteria:**

| # | Given | When | Then |
|---|-------|------|------|
| AC1.2.1 | Claude Code SDK is not installed or `ANTHROPIC_API_KEY` is unset | Agent creation triggers backtesting | Agent status transitions to `ERROR` (not stuck in `BACKTESTING`) within one DB write cycle |
| AC1.2.2 | Agent is in `ERROR` status | Dashboard polls agent list | Agent card displays a human-readable error message (e.g., "Claude SDK unavailable: ANTHROPIC_API_KEY not set") |
| AC1.2.3 | SDK becomes available later | Admin installs SDK and retries | A retry / re-run action is available on the agent card (exact UX TBD by Atlas) |

**Dependencies:** Requires that the `agents` polling query returns the `error_message` field, and that the agent card component renders it.

---

#### Story 1.3 — Backtest agent creation does not trigger full ML pipeline prematurely
**As a** platform operator,  
**I want** new agent creation to enqueue backtesting work only after validating that required prerequisites (SDK, config) are met,  
**so that** the system does not waste compute and does not produce a misleading `RUNNING` backtest record for a job that will immediately fail.

**Priority:** P1  
**File refs:** `apps/api/src/routes/agents.py:157-271`

**Acceptance Criteria:**

| # | Given | When | Then |
|---|-------|------|------|
| AC1.3.1 | Prerequisites pass (SDK available, config valid) | Agent is created | Backtest job is enqueued and `AgentBacktest.status = RUNNING` as today |
| AC1.3.2 | Prerequisites fail (SDK unavailable) | Agent is created | `AgentBacktest.status` is set to `FAILED` (not `RUNNING`), with a descriptive `error_reason` field populated |
| AC1.3.3 | — | Either outcome | The API `POST /api/v2/agents` returns HTTP 201 in both cases (creation succeeds; backtest failure is async) |

**Dependencies:** Story 1.2 (error status write path must exist first).

---

### Problem Cluster 2: Paper Trading Message Pipeline

---

#### Story 2.1 — Paper trading agent reads messages from the correct Redis stream key
**As a** paper-trading agent,  
**I want** to subscribe to the Redis stream that the ingestion service actually publishes to for my configured channel,  
**so that** I receive every Discord message relevant to my channel without any silent loss.

**Priority:** P0  
**File refs:** `apps/api/src/services/message_ingestion.py:88-90`, `agents/templates/live-trader-v1/tools/discord_redis_consumer.py:57`

**Acceptance Criteria:**

| # | Given | When | Then |
|---|-------|------|------|
| AC2.1.1 | Ingestion service publishes a message to `stream:channel:{connector_id}` | Paper agent's consumer is running | Consumer receives the message |
| AC2.1.2 | Ingestion also publishes to `stream:channel:{channel_id}` (when `channel_id ≠ connector_id`) | Paper agent's consumer is running | Consumer does not receive duplicate messages |
| AC2.1.3 | A new paper agent is started | Consumer initialises | Consumer subscribes to the correct stream key derived from the agent's `connector_id` (primary key per ingestion contract) |

**Dependencies:** DB migration not required; config/env-var or code change only.

---

#### Story 2.2 — Paper trading agent receives messages published before it started (no missed history)
**As a** paper-trading agent,  
**I want** to replay any messages that were published to my channel's Redis stream before my consumer started,  
**so that** I do not miss signals that arrived during a brief restart window.

**Priority:** P1  
**File refs:** `agents/templates/live-trader-v1/tools/discord_redis_consumer.py:60`

**Acceptance Criteria:**

| # | Given | When | Then |
|---|-------|------|------|
| AC2.2.1 | 5 messages are published to the stream before the consumer starts | Consumer starts | Consumer reads all 5 backlogged messages (offset starts from `0-0` on first start, or from the persisted cursor on restart) |
| AC2.2.2 | Agent is restarted mid-session | Consumer restarts | Consumer resumes from the last acknowledged stream ID, not from `$` |
| AC2.2.3 | — | Consumer acknowledges a message | Last-read stream ID is persisted (DB or local file) so restarts are safe |

**Dependencies:** Requires a mechanism to persist the last-read stream cursor per agent (DB column or agent work-dir file — decision for Atlas).

---

#### Story 2.3 — Paper trading message consumer runs for the full agent session lifetime
**As a** paper-trading agent,  
**I want** the Discord message consumer to stay running as long as the agent session is active,  
**so that** messages are not dropped because the consumer timed out after 30 seconds.

**Priority:** P0  
**File refs:** `agents/templates/live-trader-v1/tools/discord_redis_consumer.py:39,62`

**Acceptance Criteria:**

| # | Given | When | Then |
|---|-------|------|------|
| AC2.3.1 | Paper agent session is active | 31 seconds have elapsed since consumer started | Consumer is still running and processing new messages |
| AC2.3.2 | Agent session is terminated (status → `STOPPED` or `PAUSED`) | — | Consumer exits cleanly within 5 seconds of the termination signal |
| AC2.3.3 | Consumer encounters a transient Redis disconnect | — | Consumer reconnects with exponential back-off (max 30 s) and resumes without data loss |

**Dependencies:** Story 2.1 (correct stream key must be set before a persistent consumer is meaningful).

---

#### Story 2.4 — Single authoritative Discord message tool in the live-trader-v1 template
**As a** developer maintaining the agent template,  
**I want** exactly one Discord message ingestion tool file in `live-trader-v1/tools/`,  
**so that** agent CLAUDE.md instructions unambiguously call the correct tool and there is no risk of both tools running concurrently.

**Priority:** P1  
**File refs:** `agents/templates/live-trader-v1/tools/discord_listener.py`, `agents/templates/live-trader-v1/tools/discord_redis_consumer.py`

**Acceptance Criteria:**

| # | Given | When | Then |
|---|-------|------|------|
| AC2.4.1 | Template is deployed | Agent CLAUDE.md references a Discord tool | Only `discord_redis_consumer.py` is present and referenced; `discord_listener.py` is either deleted or renamed with a `_DEPRECATED` suffix and never invoked |
| AC2.4.2 | — | `discord_listener.py` is removed/deprecated | No existing agent session breaks (verified by integration test or manual smoke test) |

**Dependencies:** Story 2.1 must be resolved first so the surviving tool is the correct one.

---

#### Story 2.5 — Paper trading agent operates in an isolated, no-trade mode
**As a** trader approving an agent for paper trading,  
**I want** the paper-trading agent session to be driven by instructions that explicitly prohibit real trade execution,  
**so that** I can safely evaluate the agent's signal quality without financial risk.

**Priority:** P1  
**File refs:** `apps/api/src/services/agent_gateway.py:489` (CLAUDE.md selection logic)

**Acceptance Criteria:**

| # | Given | When | Then |
|---|-------|------|------|
| AC2.5.1 | Agent status is `PAPER` | Gateway launches the agent session | The agent receives a CLAUDE.md (or equivalent instruction set) that contains an explicit "paper mode" directive preventing calls to any live order-execution tool |
| AC2.5.2 | Agent status is `RUNNING` (live) | Gateway launches the agent session | The agent receives the standard live-trading CLAUDE.md with full trade execution enabled |
| AC2.5.3 | — | Both modes | The mode selection is logged in `agent_sessions` and visible in the Agents tab session detail |

**Dependencies:** DB migration may be required if `agent_sessions` does not currently store `mode` (paper vs. live). New migration is acceptable per user constraints.

---

## 6. Constraints (confirmed by user)

| # | Constraint |
|---|-----------|
| C1 | The existing 3-step agent creation wizard layout must not change — bug fixes only, no UX redesign. |
| C2 | The message pipeline fix is surgical: correct the stream key mismatch and make the consumer persistent. No full messaging-layer redesign. |
| C3 | New database migrations are acceptable. |

---

## 7. Risks & Dependencies

| Risk | Severity | Notes |
|------|----------|-------|
| **Stream cursor persistence adds a new DB column or file I/O path** | Medium | Atlas must decide whether to persist `last_stream_id` in the `agent_sessions` table or in the agent's work-dir `config.json`. Either approach requires a migration or a file contract. See Story 2.2. |
| **Deprecating `discord_listener.py` may break existing live agents** | High | Any currently-running agent whose `CLAUDE.md` references `discord_listener.py` will break on restart. A migration script or fallback alias may be needed. Devin must audit `CLAUDE.md` templates before removing the file. |
| **Paper-mode CLAUDE.md must be provisioned into the agent work-dir** | Medium | The gateway currently selects a single template. If no separate paper-mode template exists, it must be created as part of this work. Atlas owns the template path decision. |
| **`canAdvance` change must not regress trading-type wizard** | Low | The fix for Story 1.1 must preserve the existing connector+channel requirement for `type === 'trading'`. Covered by AC1.1.3. |
| **SDK preflight errors are already written to DB but not surfaced in UI** | Low | The backend already logs SDK errors (confirmed at `agent_gateway.py:234-244`). The main gap is the frontend polling query not returning/rendering the `error_reason` field. Low risk if the API contract is extended carefully. |
| **`/api/v2/agents/{id}/promote` endpoint exists in code** | Low | Build orchestrator initially flagged this as missing; code recon confirmed the endpoint is present at `agents.py:913`. Atlas/Devin should verify it is correctly registered and reachable in all deployment environments before closing this as a non-issue. |

---

## 8. Open Questions

None — all user-facing constraints have been confirmed. The following are **implementation decisions** deferred to Atlas:

1. Where to persist the Redis stream cursor for Story 2.2 (DB column vs. agent work-dir file)?
2. What is the naming convention and storage path for a paper-mode `CLAUDE.md`?
3. Should `discord_listener.py` be deleted immediately or aliased for one release cycle before removal?

---

*This document is the contract for Atlas (system design) and Devin (implementation). Do not implement from this document directly — Atlas must produce an architecture and tech plan first.*
