# PRD: Phase B — Agent Wake-on-Discord AI Flow Verification + Observability Hardening

Version: 1.0 | Status: Draft | Date: 2026-04-18 | Author: Nova-PM

## Problem Statement

The AI-driven trade flow (Discord message → agent wake → LLM decision → broker order) is implemented across multiple services, but has not been end-to-end verified as a single system. Gaps in error handling, retries, circuit breakers, dead-letter queues, correlation IDs, and observability metrics are suspected but not cataloged. The user's ask is **verification + hardening**, not a rewrite.

## Goals

1. **Source-level trace**: document every hop from Discord message arrival to final trade record + sub-agent spawn.
2. **Gap inventory**: catalog every missing error-handling / retry / observability capability with severity.
3. **Fix all Sev-1 and Sev-2 gaps** before go-live.
4. **Observability dashboard**: surface the core metrics needed to operate this flow in production.
5. **Sub-agent verification**: confirm position-monitor sub-agents are spawned and sell signals route correctly.

## Non-Goals

- Rewriting any service or tool
- Changing tool interfaces or agent templates
- Pipeline engine (Phase A)
- Backtesting (Phase C)
- OpenClaw (Phase F)
- Performance benchmarking (Phase E)
- UI redesigns
- New agent types or tools

## Expected End-to-End Flow (per CLAUDE.md + predecessor findings)

1. Discord message arrives via bot gateway
2. `services/discord-ingestion/` persists to `channel_messages` and publishes to a Redis stream
3. AgentGateway (`apps/api/src/services/agent_gateway.py`) consumes stream and wakes the correct agent
4. Claude Code session starts in the agent's sandboxed working directory
5. Agent reads signal file → calls tools in sequence:
   - `parse_signal.py`
   - `enrich_single.py`
   - `inference.py`
   - agent reasoning + learned rules
   - `risk_check.py`
   - `technical_analysis.py`
   - `execute_trade.py`
6. Robinhood MCP places order → Phoenix records trade
7. Position-monitor sub-agent spawned per trade
8. Sell signals routed from primary agent to sub-agent

## Verification Plan — 15-Hop Checklist

Each hop is verified by identifying the exact file/function that implements it and confirming the handoff is wired.

| Hop | From → To | File / Function | Verification |
|---|---|---|---|
| 1 | Discord message → DB persist | `services/discord-ingestion/src/main.py` | Unit coverage, log inspection, DB write verified |
| 2 | DB persist → Redis stream publish | `services/discord-ingestion/src/main.py` | XADD visible in Redis; stream key documented |
| 3 | Redis stream → signal_listener.py | `agents/.../signal_listener.py` | Consumer group present; XREADGROUP running |
| 4 | signal_listener.py → agent wake | `apps/api/src/services/agent_gateway.py` | Agent session launch instrumented |
| 5 | Agent → parse_signal.py | Agent template tool | Input file parsed; output dict in expected shape |
| 6 | Agent → enrich_single.py | Agent template tool | 200+ market features attached |
| 7 | Agent → inference.py | Agent template tool | TRADE/SKIP verdict + confidence |
| 8 | Agent → risk_check.py | Agent template tool | Position/exposure limits enforced |
| 9 | Agent → technical_analysis.py | Agent template tool | TA confirmation emitted |
| 10 | Agent → execute_trade.py | Agent template tool | Order intent constructed |
| 11 | execute_trade.py → Robinhood MCP | MCP client | Order placed, order_id returned |
| 12 | execute_trade.py → Phoenix API trade record | API endpoint | Trade row written, FK to agent/connector |
| 13 | execute_trade.py → spawn sub-agent | AgentGateway sub-agent API | Sub-agent session spawned per trade |
| 14 | Sub-agent lifecycle | Position-monitor template | Heartbeat, poll cadence, auto-shutdown on flat |
| 15 | Sell signal routing: primary → sub-agent | Routing mechanism | Sub-agent receives sell directive and acts |

## Gap Analysis Template

For each hop, Atlas produces entries in this shape:

```
Gap-ID: B-GAP-<nn>
Hop: <1..15>
Severity: Sev-1 (data loss / silent failure) | Sev-2 (observability) | Sev-3 (nice-to-have)
Category: ErrorHandling | Retry | CircuitBreaker | DLQ | Logging | Metrics | CorrelationID | SubAgent
Location: <file>:<function>:<line>
Impact: <what breaks / what we can't see>
Proposed Fix: <concrete change>
```

## Functional Requirements

### F-1: End-to-End Trace Document
Write `docs/architecture/agent-wake-flow-trace.md` containing the 15-hop checklist above with exact file/function references filled in from source inspection.

### F-2: Gap Inventory
Write `docs/prd/phase-b-gap-inventory.md` containing every gap found with severity, category, location, impact, and proposed fix.

### F-3: Correlation ID Propagation
Every message entering the system gets a `correlation_id` (UUID4) carried through all structured logs and downstream messages: Discord ingestion → Redis stream → agent session → tool calls → broker call → trade record.

### F-4: Dead-Letter Queue (DLQ)
File-based DLQ for signals that fail parse / enrich / inference. Operator can inspect, replay, or discard failed signals.

### F-5: Circuit Breakers & Retries
External calls (Robinhood MCP, Phoenix API, LLM inference) wrapped in three-state circuit breaker with exponential backoff. Failure modes documented.

### F-6: Observability Dashboard
Reuse existing Grafana stack if available; otherwise choose minimal path. Dashboard shows:
- Messages ingested per second
- Redis stream lag (per consumer group)
- Agents launched per minute
- Tool-call latency p50/p95/p99 (per tool)
- Trade execution success rate
- Sub-agent spawn rate
- Circuit breaker state (closed/open/half-open) per dependency
- DLQ size

### F-7: Sub-Agent Verification
Confirm sub-agent spawning logic exists and is wired; confirm sell-signal routing channel (Redis stream, API call, or shared file) is functional. If any piece is missing, treat as Sev-1.

## Acceptance Criteria

1. `docs/architecture/agent-wake-flow-trace.md` exists, every hop has a file/function reference.
2. `docs/prd/phase-b-gap-inventory.md` exists with every gap cataloged.
3. Every Sev-1 and Sev-2 gap is fixed in code; tests added.
4. Grafana dashboard exists and shows the seven metric categories in F-6.
5. Correlation IDs appear in all structured logs for a single signal's path, end-to-end.
6. DLQ exists; failed signals appear in it; operator tool to inspect/replay exists.
7. Circuit breakers wrap all external calls with documented failure modes.
8. Sub-agent spawning verified via integration test: one trade → one sub-agent process.
9. Sell-signal routing verified via integration test: primary agent emits sell → sub-agent acts.
10. End-to-end smoke test: post a known signal to a test Discord channel → trade recorded → sub-agent spawned → no ERROR logs.
11. Full regression suite green.

## Dependencies

- Redis Streams infrastructure
- AgentGateway service
- Claude Code SDK
- Robinhood MCP tooling
- Existing observability stack (discover during architecture)

## Risks

| # | Risk | Mitigation |
|---|---|---|
| B-R1 | Hidden race conditions surface only under load | Structured concurrency test + soak test before go-live |
| B-R2 | Missing retries only observable under failure | Inject fault scenarios in integration test suite |
| B-R3 | Claude session cold-start latency high | Measure and document; warm-pool optimization is out-of-scope for Phase B |
| B-R4 | Sub-agent routing not implemented | Verify immediately at architecture phase; if missing, escalate to Sev-1 and add to build scope |
| B-R5 | Observability stack not standardized | Atlas picks minimum-viable stack; defer full platform choice |

## Open Questions for Atlas

1. Observability stack: existing Grafana/Prometheus, or build minimum-viable stack?
2. DLQ mechanism: Redis stream, file-based, or Postgres table?
3. Trace-ID propagation: custom header, W3C traceparent, or structured log field only?
4. Sub-agent session linking: shared file, Redis pub/sub, or AgentGateway routing API?
5. Agent heartbeat mechanism: DB column update, Redis key TTL, or process presence?
6. Circuit breaker placement: in-process per tool, or gateway-level?
7. Redis stream lag metric: client-computed (last read ID vs stream tail) or server-reported?
8. Smoke-test environment: shared staging channel or isolated per-PR channel?

## Out of Scope

- Pipeline engine (Phase A)
- Backtesting flow verification (Phase C)
- OpenClaw removal (Phase F)
- Performance benchmarking (Phase E)
- UI redesigns
- New agent types or tools

## Handoff to Atlas

Atlas produces: filled-in trace doc (hop-by-hop file refs), filled-in gap inventory, observability architecture (metrics + dashboards + DLQ + trace-ID design), sub-agent routing design if missing.
