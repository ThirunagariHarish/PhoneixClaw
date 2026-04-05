# System Architecture — Claude Code Agent Platform

## Overview

Phoenix Claw is a multi-agent trading platform where **Claude Code instances on VPS machines** serve as the intelligence plane. The Phoenix dashboard and API act as the control plane. Agents are autonomous Claude Code projects that listen to Discord channels, run trained ML models, and execute trades via Robinhood.

## Planes

### Control Plane (this repo)

| Component | Role |
|-----------|------|
| `apps/dashboard/` | React UI — agent management, metrics, chat, token monitoring |
| `apps/api/` | FastAPI — CRUD, agent lifecycle, gateway orchestration |
| `shared/db/` | Postgres — agents, trades, metrics, VPS instances |
| Agent Gateway | New module in API — SSH-based communication with VPS |

### Intelligence Plane (remote VPS)

| Component | Role |
|-----------|------|
| Claude Code CLI | Runtime for agents — orchestrates tools, writes code |
| Backtesting Agent | Pre-built project shipped to VPS; runs ETL + training |
| Live Trading Agents | Created by backtesting agent; listen to Discord, trade via Robinhood |

### Shared Services

| Component | Role |
|-----------|------|
| Postgres | Persistent state for both planes |
| Redis | Event bus, caching, pub/sub for real-time updates |
| MinIO | Model artifact storage (optional; can also use VPS filesystem) |

## Communication Flow

```
Dashboard --HTTP--> Phoenix API --SSH--> VPS (Claude Code)
                        |                    |
                        v                    v
                    Postgres            Agent Project/
                                          CLAUDE.md
                                          tools/
                                          models/
                                          skills/
```

### API Gateway → VPS Protocol

1. **Registration**: User adds VPS in Network tab with host + SSH credentials
2. **Health Check**: Gateway SSHs to VPS, runs `claude --version` and checks disk/memory
3. **Ship Agent**: `scp -r agents/backtesting/ user@vps:~/agents/backtesting/`
4. **Run Command**: `ssh user@vps "cd ~/agents/backtesting && claude --print 'run backtest for channel SPX-alerts'"`
5. **Stream Output**: SSH session streams stdout back; gateway parses progress events
6. **Callback**: Agent writes results to a JSON file; gateway polls or agent calls back via HTTP

### Agent → Phoenix API Protocol

Live agents call back to Phoenix API to:
- Register themselves (`POST /api/v2/agents` with `source=backtesting`)
- Report trades (`POST /api/v2/trades`)
- Report metrics (`POST /api/v2/agents/{id}/metrics`)
- Report health (`POST /api/v2/agents/{id}/heartbeat`)

## Directory Layout on VPS

```
~/agents/
  backtesting/              # Shipped from repo; one per VPS
    CLAUDE.md               # Backtesting orchestration instructions
    tools/                  # Python scripts for ETL, enrichment, training
    skills/                 # Reusable skill definitions
    output/                 # Backtesting results (temporary)
  
  live/
    spx-alerts/             # Created by backtesting agent
      CLAUDE.md             # Live trading instructions
      models/               # Trained model artifacts (.pkl, .pt)
      tools/                # Inference, TA, Robinhood MCP
      skills/               # Discord listener, trade execution
      config.json           # Channel, thresholds, risk params
      trades.log            # Local trade journal
    
    aapl-swings/            # Another analyst channel
      ...
```

## Token Optimization Architecture

```
                         ┌─────────────────────┐
                         │   Claude Code CLI    │
                         │                      │
  Routine decisions ───> │  claude-haiku (fast) │ <── Discord msg parsing
  Complex analysis ────> │  claude-sonnet       │ <── Error recovery, chat
                         │                      │
                         │  Python scripts ─────│──── ML inference (no tokens)
                         │  robin_stocks ───────│──── Trade execution (no tokens)
                         │  yfinance ───────────│──── Market data (no tokens)
                         └─────────────────────┘
```

Most compute happens in **Python scripts** invoked by Claude Code, not in LLM calls. The LLM orchestrates which scripts to run and handles edge cases.

## Service Dependency Map

| Service | Postgres | Redis | Kafka | MinIO | VPS (SSH) |
|---------|----------|-------|-------|-------|-----------|
| phoenix-api | Required | Required | - | - | Via gateway |
| phoenix-ws-gateway | - | Required | - | - | - |
| phoenix-execution | Required | Required | - | - | - |
| phoenix-position-monitor | Required | - | Producer | - | - |
| phoenix-automation | Required | Required | - | - | - |
| phoenix-connector-manager | Required | Required | - | - | - |
| phoenix-backtest-runner | Required | - | - | Required | - |
| phoenix-global-monitor | Required | Required | - | - | - |
| phoenix-orchestrator | Required | Required | - | - | - |
| phoenix-comms | - | Required | - | - | - |
| phoenix-skill-sync | - | - | - | Required | - |
| phoenix-agent-comm | Required | Required | - | - | - |

## Deployment Topology

```
┌─────────────────────────────────────────────────────────────┐
│  Coolify VPS (69.62.86.166) — cashflowus.com               │
│                                                              │
│  Traefik (TLS termination)                                   │
│    └── nginx (port 80)                                       │
│          ├── /          → phoenix-dashboard                  │
│          ├── /api/      → phoenix-api                        │
│          ├── /ws/       → phoenix-ws-gateway                 │
│          └── /auth/     → phoenix-api                        │
│                                                              │
│  Infrastructure:                                             │
│    ├── postgres (TimescaleDB)                                │
│    ├── redis                                                 │
│    └── minio                                                 │
│                                                              │
│  Background Services:                                        │
│    ├── phoenix-execution                                     │
│    ├── phoenix-position-monitor                              │
│    ├── phoenix-automation                                    │
│    ├── phoenix-orchestrator                                  │
│    ├── phoenix-global-monitor                                │
│    ├── phoenix-connector-manager                             │
│    ├── phoenix-backtest-runner                               │
│    ├── phoenix-skill-sync                                    │
│    ├── phoenix-agent-comm                                    │
│    └── phoenix-comms                                         │
│                                                              │
│  Observability:                                              │
│    ├── prometheus                                            │
│    ├── grafana                                               │
│    ├── loki + promtail                                       │
│    └── node-exporter, postgres-exporter, redis-exporter      │
└─────────────────────────────────────────────────────────────┘
          │
          │ SSH (port 22)
          ▼
┌─────────────────────────────────────────────────────────────┐
│  Agent VPS(es) — Claude Code Instances                       │
│                                                              │
│  ~/agents/backtesting/    ← shipped by gateway               │
│  ~/agents/live/spx-alerts/  ← created by backtesting agent  │
│  ~/agents/live/aapl-swings/ ← created by backtesting agent  │
│                                                              │
│  Each live agent:                                            │
│    - Discord listener (long-running Python)                  │
│    - ML models (.pkl, .pt)                                   │
│    - Robinhood MCP server                                    │
│    - Heartbeat → Phoenix API                                 │
└─────────────────────────────────────────────────────────────┘
```

## Failure and Retry Sequences

### Scenario: SSH Connection to VPS Fails

```
Phoenix API                   VPS
    │                          │
    │── SSH connect ──────────>│ TIMEOUT
    │                          │
    │  (retry 1, after 5s)     │
    │── SSH connect ──────────>│ TIMEOUT
    │                          │
    │  (retry 2, after 15s)    │
    │── SSH connect ──────────>│ TIMEOUT
    │                          │
    │  Mark instance UNREACHABLE in DB
    │  Notify user via WebSocket
    │  Return 502 to dashboard
```

Retry policy: 3 attempts with exponential backoff (5s, 15s, 45s). After 3 failures, mark instance as `UNREACHABLE` and alert the user.

### Scenario: Agent Crashes on VPS

```
Live Agent (VPS)              Phoenix API
    │                            │
    │── heartbeat ──────────────>│  ✓ (every 60s)
    │── heartbeat ──────────────>│  ✓
    │   CRASH                    │
    │                            │  (no heartbeat for 3 minutes)
    │                            │  Mark agent UNRESPONSIVE
    │                            │  Attempt SSH health check
    │                            │── SSH: check process ──>│
    │                            │<── not running ─────────│
    │                            │── SSH: restart agent ──>│
    │                            │<── started ─────────────│
    │                            │  Mark agent RUNNING
```

### Scenario: Robinhood Order Fails

```
Decision Engine          Robinhood MCP          Robinhood API
    │                        │                       │
    │── place_order ────────>│                       │
    │                        │── POST order ────────>│
    │                        │<── 400 insufficient ──│
    │                        │                       │
    │<── error: insufficient │
    │    buying power        │
    │                        │
    │  Log failed attempt    │
    │  Report to Phoenix     │
    │  Do NOT retry (not     │
    │  transient error)      │
```

Retryable errors (network timeout, 5xx): retry up to 2 times with 3s delay.
Non-retryable errors (insufficient funds, invalid order, auth failure): fail immediately, log, report.

## End-to-End Live Trade Data Flow

```
1. Analyst posts in Discord    ──────> Discord API
                                          │
2. Discord listener (Python)   <──────────┘
   - Regex pre-filter
   - Priority detection
   - Write to pending_signals.json
                │
3. Decision Engine (Python)
   a. Parse signal (ticker, side, price)
   b. Enrich with live market data (yfinance)
   c. Run ML classifier (model.predict())
   d. Check pattern matches
   e. Apply price buffer
   f. Run risk checks (confidence, position limits, daily loss)
                │
   TRADE decision? ─── No ──> Log skip reason, report to Phoenix
                │
               Yes
                │
4. Robinhood MCP
   a. Place limit order with buffer
   b. Attach stop-loss order
   c. Monitor fill (poll every 2s)
                │
5. Position Monitor (Python daemon)
   - Every 60s: check price vs stops
   - Every 5m: full TA scan (RSI, MACD, volume)
   - Partial exit ladder at profit targets
   - Trailing stop adjustment
   - Swing trade overnight hold logic
                │
6. Report to Phoenix API
   - POST /api/v2/agents/{id}/live-trades
   - POST /api/v2/agents/{id}/metrics
   - POST /api/v2/agents/{id}/heartbeat
                │
7. Dashboard displays real-time via WebSocket
```

## Configuration Hierarchy

Configuration flows from multiple sources with this precedence (highest first):

1. **Runtime commands** — `POST /api/v2/agents/{id}/command` (e.g., pause, change mode)
2. **Agent config.json** — Per-agent settings on VPS
3. **Environment variables** — `.env` on VPS
4. **Defaults** — Hardcoded in tool scripts
