# Project Phoenix v2 — Architecture & Infrastructure Plan

**Version:** 1.0.0
**Date:** March 3, 2026
**Status:** Draft
**Reference:** [PRD v2.1.0](PRD.md)

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Infrastructure Topology](#2-infrastructure-topology)
3. [Service Architecture](#3-service-architecture)
4. [Database Architecture](#4-database-architecture)
5. [Event Bus & Message Flow](#5-event-bus--message-flow)
6. [OpenClaw Instance Architecture](#6-openclaw-instance-architecture)
7. [Networking & Security](#7-networking--security)
8. [Deployment Pipeline](#8-deployment-pipeline)
9. [Monitoring & Observability](#9-monitoring--observability)
10. [Scaling Strategy](#10-scaling-strategy)

---

## 1. System Architecture Overview

### 1.1 Three-Plane Architecture

Phoenix v2 is organized into three logical planes:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          CONTROL PLANE                                  │
│                                                                         │
│  React Dashboard ◄──► FastAPI Backend ◄──► PostgreSQL / Redis           │
│       (Vite)           (Uvicorn)           (App state)                  │
│                             │                                           │
│                    ┌────────┴─────────┐                                 │
│                    │  Orchestrator    │                                  │
│                    │  (BullMQ worker) │                                  │
│                    └────────┬─────────┘                                 │
│                             │                                           │
│                    ┌────────┴─────────┐                                 │
│                    │  Event Bus       │                                  │
│                    │  (Redis Streams) │                                  │
│                    └────────┬─────────┘                                 │
└─────────────────────────────┼───────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        EXECUTION PLANE                                  │
│                                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │ OC Instance A │  │ OC Instance B│  │ OC Instance C│  │OC Inst. D  │ │
│  │ Strategy Lab  │  │ Data/Research│  │ Risk/Promote │  │Live Trading│ │
│  │ + Bridge API  │  │ + Bridge API │  │ + Bridge API │  │+ Bridge API│ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────┼───────────────────────────────────────────┐
│                       SHARED SERVICES                                   │
│                                                                         │
│  ┌─────────┐  ┌──────────────┐  ┌───────────────┐  ┌────────────────┐ │
│  │  MinIO   │  │ TimescaleDB  │  │   Execution   │  │ Observability  │ │
│  │(Artifacts│  │(Market data, │  │   Service     │  │ (Prometheus,   │ │
│  │ backtest │  │ metrics,     │  │ (Alpaca/IBKR/ │  │  Grafana,      │ │
│  │ results) │  │ trade logs)  │  │  Robinhood)   │  │  Loki)         │ │
│  └─────────┘  └──────────────┘  └───────────────┘  └────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

**Control Plane** -- The user-facing layer. Runs the React dashboard, FastAPI backend, PostgreSQL for application state, Redis for caching/queuing/event bus, and the Orchestrator worker that manages agent lifecycle state machines. All deployed on a single Coolify server.

**Execution Plane** -- The intelligence layer. Four logical OpenClaw instances run on separate VPS nodes. Each instance hosts multiple AI agents with their own workspaces, skills, and tools. A Bridge Service sidecar on each node exposes a REST API for remote management by the Control Plane. All decision-making, strategy evaluation, and code generation happen here.

**Shared Services** -- Infrastructure that both planes consume. MinIO stores backtest artifacts and trained models. TimescaleDB stores time-series market data and metrics. The Execution Service places orders via broker APIs. Observability tools collect metrics and logs from all planes.

### 1.2 Design Principles

| Principle | Implementation |
|---|---|
| Intelligence in OpenClaw | Dashboard is display-only. All reasoning, evaluation, and trading logic runs in OpenClaw agents. |
| Queue-based execution | Agents never call broker APIs directly. Trade intents go through a queue with validation and risk checks. |
| Fail-safe defaults | Circuit breakers, hard stop-losses, and a global kill switch are non-negotiable safety nets. |
| Idempotent operations | Every trade intent has a unique ID. The execution service deduplicates. |
| Secrets never leave backend | API keys are encrypted at rest (Fernet). The frontend only sees masked previews. |
| Agent isolation | Each OpenClaw agent has its own workspace. No cross-contamination of state or memory. |
| Skill reuse | Skills are authored once in a central repository and synced to all instances. |

### 1.3 End-to-End Data Flow

```
User Action (create agent, configure connector)
    │
    ▼
Dashboard (React) ──POST──► Backend API (FastAPI)
    │                              │
    │                         Validates + writes to PostgreSQL
    │                              │
    │                         Enqueues job to Redis (BullMQ)
    │                              │
    │                              ▼
    │                     Orchestrator Worker
    │                     (state machine, retries)
    │                              │
    │                         Publishes to Event Bus (Redis Streams)
    │                              │
    │              ┌───────────────┼───────────────┐
    │              ▼               ▼               ▼
    │       OpenClaw A       OpenClaw B       OpenClaw D
    │       (builds strategy) (fetches data)  (trades live)
    │              │               │               │
    │              └───────┬───────┘               │
    │                      │                       │
    │              Agent evaluates signal           │
    │              using skills                     │
    │                      │                       │
    │              POST /api/v2/trade-intents       │
    │                      │                       │
    │                      ▼                       │
    │              Execution Service                │
    │              (validate + risk check)          │
    │                      │                       │
    │                      ▼                       │
    │              Broker API (Alpaca)              │
    │              (place order)                    │
    │                      │                       │
    │                      ▼                       │
    │              Order filled ──► Position created │
    │                      │                       │
    │              Published to Event Bus            │
    │                      │                       │
    ◄──── WebSocket push ──┘
    │
Dashboard updates in real-time
```

---

## 2. Infrastructure Topology

### 2.1 Physical Deployment

```
                    ┌─────────────────────────────┐
                    │      INTERNET / CDN          │
                    │    phoenix.yourdomain.com     │
                    └──────────────┬───────────────┘
                                   │ HTTPS (Let's Encrypt)
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    NODE 1: COOLIFY SERVER                             │
│                    (Primary Application Server)                       │
│                                                                      │
│  ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ ┌───────────┐ │
│  │  Dashboard  │ │ Backend  │ │PostgreSQL│ │ Redis  │ │   MinIO   │ │
│  │  (nginx +  │ │  API     │ │   16 +   │ │  7     │ │  (S3 API) │ │
│  │  React)    │ │ (FastAPI)│ │TimescaleDB│ │        │ │           │ │
│  │  :3080     │ │  :8011   │ │  :5432   │ │ :6379  │ │ :9000     │ │
│  └────────────┘ └──────────┘ └──────────┘ └────────┘ └───────────┘ │
│                                                                      │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────────┐ │
│  │Orchestrator │ │  Execution   │ │   Global     │ │ Connector   │ │
│  │  Worker     │ │  Service     │ │   Monitor    │ │  Manager    │ │
│  └─────────────┘ └──────────────┘ └──────────────┘ └─────────────┘ │
│                                                                      │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────────┐ │
│  │  Backtest   │ │  Skill Sync  │ │  Automation  │ │  Agent Comm │ │
│  │  Runner     │ │  Service     │ │  Scheduler   │ │  Router     │ │
│  └─────────────┘ └──────────────┘ └──────────────┘ └─────────────┘ │
│                                                                      │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐                  │
│  │ Prometheus  │ │   Grafana    │ │     Loki     │                  │
│  │  :9090      │ │   :3000      │ │   :3100      │                  │
│  └─────────────┘ └──────────────┘ └──────────────┘                  │
│                                                                      │
│                    WireGuard Interface: 10.0.1.1                      │
└──────────────────────────────────────────────────────────────────────┘
          │ WireGuard VPN (encrypted tunnel)
          │
    ┌─────┼────────────────┬───────────────────┐
    │     │                │                   │
    ▼     ▼                ▼                   ▼
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ NODE 2: OC-A   │ │ NODE 3: OC-B   │ │ NODE 4: OC-C/D │
│ Strategy Lab   │ │ Data/Research  │ │ Risk + Trading │
│                │ │                │ │                │
│ OpenClaw       │ │ OpenClaw       │ │ OpenClaw (x2)  │
│ Bridge :18800  │ │ Bridge :18800  │ │ Bridge :18800  │
│                │ │                │ │ Bridge :18801  │
│ WG: 10.0.1.10 │ │ WG: 10.0.1.11 │ │ WG: 10.0.1.12 │
└────────────────┘ └────────────────┘ └────────────────┘
```

### 2.2 Node Specifications

| Node | Role | Provider | Plan | CPU | RAM | Disk | Monthly Cost |
|---|---|---|---|---|---|---|---|
| Node 1 | Coolify Server (all core services) | Hetzner | CX42 | 8 vCPU | 16 GB | 160 GB SSD | ~$28 |
| Node 2 | OC Instance A: Strategy Lab | Hetzner | CX32 | 4 vCPU | 8 GB | 80 GB SSD | ~$14 |
| Node 3 | OC Instance B: Data & Research | Hetzner | CX32 | 4 vCPU | 8 GB | 80 GB SSD | ~$14 |
| Node 4 | OC Instance C+D: Risk + Live Trading | Hetzner | CX42 | 8 vCPU | 16 GB | 160 GB SSD | ~$28 |
| **Total** | | | | **24 vCPU** | **48 GB** | **480 GB** | **~$84/mo** |

**Rationale**:
- Node 1 needs the most resources because it runs PostgreSQL, Redis, MinIO, all backend services, and the observability stack.
- Node 4 hosts two OpenClaw instances (Risk and Live Trading) because they need to communicate with low latency for real-time risk checks during trade execution.
- Nodes 2 and 3 can be smaller because Strategy Lab and Data/Research are not latency-sensitive.

**Alternative: Minimal Setup** (for development/testing):
- Combine all OpenClaw instances onto a single VPS (Hetzner CX42, ~$28) for 2-node total (~$56/mo).

**Alternative: Maximum Setup** (for production with many agents):
- Dedicated VPS per OpenClaw instance (4 nodes) + larger Coolify server (CX52, 16 vCPU / 32 GB) = ~$140/mo.

### 2.3 Domain and DNS

| Record | Type | Value | Purpose |
|---|---|---|---|
| `phoenix.yourdomain.com` | A | Coolify server public IP | Dashboard + API |
| `api.phoenix.yourdomain.com` | CNAME | `phoenix.yourdomain.com` | API (optional separate subdomain) |
| `grafana.phoenix.yourdomain.com` | A | Coolify server public IP | Monitoring dashboard |

All HTTPS certificates are provisioned automatically by Coolify via Let's Encrypt.

---

## 3. Service Architecture

### 3.1 Service Registry

All services on the Coolify server communicate via Docker network. OpenClaw instances communicate via WireGuard VPN. Primary applications live under `apps/` (Backend API in `apps/api`, Dashboard in `apps/dashboard`). Auth is consolidated into the Backend API (routes under `/auth` on port 8011); a separate Auth Service on port 8001 is optional for future split.

| Service | Technology | Port | Replicas | Memory Limit | Depends On |
|---|---|---|---|---|---|
| **Dashboard** | React 18 + Vite 5 + nginx | 3080 (ext) → 80 (int) | 1 | 256 MB | API Gateway |
| **Backend API** | Python 3.12 + FastAPI + Uvicorn (includes `/auth`) | 8011 | 1 | 512 MB | PostgreSQL, Redis |
| **Orchestrator Worker** | Python 3.12 + BullMQ consumer | internal | 1 | 512 MB | Redis, PostgreSQL |
| **Execution Service** | Python 3.12 + FastAPI | 8021 | 1 | 384 MB | Redis, PostgreSQL |
| **Global Position Monitor** | Python 3.12 | internal | 1 | 256 MB | Redis, PostgreSQL |
| **Connector Manager** | Python 3.12 | internal | 1 | 384 MB | Redis, PostgreSQL, Kafka (optional) |
| **Backtest Runner** | Python 3.12 + Docker-in-Docker | internal | 1 | 1024 MB | MinIO, PostgreSQL |
| **Skill Sync Service** | Python 3.12 | internal | 1 | 128 MB | MinIO, Redis |
| **Automation Scheduler** | Python 3.12 | internal | 1 | 256 MB | Redis, PostgreSQL |
| **Agent Communication Router** | Python 3.12 | internal | 1 | 256 MB | Redis (Streams) |
| **WebSocket Gateway** | Python 3.12 + FastAPI | 8031 | 1 | 256 MB | Redis |
| **PostgreSQL** | PostgreSQL 16 + TimescaleDB | 5432 | 1 | 2048 MB | - |
| **Redis** | Redis 7 (alpine) | 6379 | 1 | 512 MB | - |
| **MinIO** | MinIO (latest) | 9000/9001 | 1 | 512 MB | - |
| **Prometheus** | Prometheus | 9090 | 1 | 256 MB | - |
| **Grafana** | Grafana | 3000 | 1 | 256 MB | Prometheus |
| **Loki** | Grafana Loki | 3100 | 1 | 256 MB | - |

**Per OpenClaw VPS Node**:

| Service | Technology | Port | Memory |
|---|---|---|---|
| OpenClaw Runtime | Node.js (OpenClaw) | 18790 | 2-4 GB |
| Bridge Service | Python 3.12 + FastAPI | 18800 | 256 MB |

### 3.2 Service Interaction Diagram

```
                           Dashboard (:3080)
                               │
                          nginx reverse proxy
                         /api → :8011, /auth → :8011, /ws → :8031
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
              Backend API (:8011)  WS Gateway (:8031)
                    │                │
                    │                │
                    ▼                │
                    PostgreSQL (:5432)     │
                         │                │
                    Redis (:6379) ◄────────┘
                    ┌────┤ (pub/sub, streams, BullMQ)
                    │    │
                    ▼    ▼
           Orchestrator  Event Bus (Redis Streams)
                    │         │
                    │    ┌────┼────────┬────────────┐
                    │    ▼    ▼        ▼            ▼
                    │   OC-A  OC-B    OC-C         OC-D
                    │   (WG)  (WG)    (WG)         (WG)
                    │                               │
                    ▼                               ▼
             Execution Svc (:8021)          Broker APIs
                    │                    (Alpaca, IBKR...)
                    ▼
              MinIO (:9000) ── Backtest Runner
```

### 3.3 nginx Routing (Dashboard)

Carried over from existing `services/dashboard-ui/nginx.conf`:

| Path | Upstream | Notes |
|---|---|---|
| `/` | Static files (`/usr/share/nginx/html`) | SPA fallback to `index.html` |
| `/api/` | `backend-api:8011` | REST API proxy |
| `/auth/` | `backend-api:8011` | Auth endpoints (consolidated in Backend API) |
| `/ws/` | `ws-gateway:8031` | WebSocket upgrade |
| `/health` | Direct 200 JSON | Load balancer health |
| `/assets/*` | Static files | 30-day cache |

Security headers: HSTS, X-Content-Type-Options, X-Frame-Options, XSS-Protection. Gzip enabled for text, JSON, JS, SVG.

---

## 4. Database Architecture

### 4.1 PostgreSQL Schema

**PostgreSQL 16 with TimescaleDB extension** for time-series data.

**Application Tables** (standard PostgreSQL):

```sql
-- Core entities
users (id, email, password_hash, mfa_secret, role, is_active, created_at, updated_at)
trading_accounts (id, user_id FK, broker_type, mode, credentials_enc, balance, buying_power, status, created_at)
openclaw_instances (id, name, host, port, role, status, agent_count, cpu_usage, memory_usage, last_heartbeat, created_at)

-- Agent entities
agents (id, name, type, status, instance_id FK, data_source_config JSONB, skills TEXT[],
        risk_config JSONB, monitor_agent_id FK, account_id FK, user_id FK, created_at, updated_at)
agent_backtests (id, agent_id FK, status, started_at, completed_at, total_signals, trades_taken,
                 total_pnl, win_rate, sharpe_ratio, max_drawdown, profit_factor, equity_curve JSONB,
                 trade_log_url, artifacts_url, created_at)
skills (id, name, category, description, version, skill_md_content TEXT, tools_required TEXT[],
        created_at, updated_at)
agent_skills (agent_id FK, skill_id FK)  -- M:N join

-- Trade entities
trade_intents (id, agent_id FK, ticker, action, instrument_type, quantity, price_target,
               stop_loss, take_profit, reasoning TEXT, source_message TEXT, status,
               fill_price, broker_order_id, error TEXT, created_at, filled_at)
positions (id, account_id FK, agent_id FK, ticker, side, quantity, entry_price, current_price,
           unrealized_pnl, stop_loss, take_profit, monitor_agent_id FK, exit_price,
           exit_reason, realized_pnl, opened_at, closed_at)

-- Connector and config entities
connectors (id, type, name, config_enc BYTEA, status, user_id FK, last_sync, created_at)
connector_agents (connector_id FK, agent_id FK)  -- M:N join
api_key_entries (id, key_type, name, credentials_enc BYTEA, status, last_used, last_tested,
                 user_id FK, created_at, updated_at)

-- Task and automation entities
tasks (id, title, description TEXT, assigned_agent_id FK, created_by_user_id FK,
       created_by_agent_id FK, status, priority, kanban_column, labels TEXT[],
       due_date, output TEXT, created_at, updated_at)
automations (id, name, cron_expression, agent_role, instance_id FK, task_description TEXT,
             delivery_channel, active BOOLEAN, last_run, next_run, user_id FK, created_at)

-- Dev Agent entities
dev_incidents (id, agent_id FK, issue_type, severity, diagnosis TEXT, action_taken TEXT,
               code_diff TEXT, outcome TEXT, rl_reward FLOAT, status, created_at, resolved_at)

-- Communication entities
agent_messages (id, from_agent_id FK, to_agent_id FK, intent, data JSONB,
                response_to FK, timestamp)

-- Logging and metrics
agent_logs (id, agent_id FK, timestamp, level, message TEXT, context JSONB, session_id)
audit_log (id, user_id FK, action, target_type, target_id, details JSONB, timestamp)
```

### 4.2 TimescaleDB Hypertables

For high-volume time-series data that needs efficient range queries and retention policies:

```sql
-- Market data cache (optional, for backtesting)
CREATE TABLE market_bars (
    time        TIMESTAMPTZ NOT NULL,
    ticker      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,  -- '1m', '5m', '1h', '1d'
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    close       NUMERIC,
    volume      BIGINT
);
SELECT create_hypertable('market_bars', 'time');

-- Performance metrics (per-agent, per-account, daily rollups)
CREATE TABLE performance_metrics (
    time          TIMESTAMPTZ NOT NULL,
    entity_type   TEXT NOT NULL,  -- 'agent', 'account', 'source'
    entity_id     UUID NOT NULL,
    metric_type   TEXT NOT NULL,  -- 'pnl', 'win_rate', 'sharpe', 'drawdown'
    value         NUMERIC
);
SELECT create_hypertable('performance_metrics', 'time');

-- Agent heartbeat snapshots
CREATE TABLE agent_heartbeats (
    time          TIMESTAMPTZ NOT NULL,
    instance_id   UUID NOT NULL,
    agent_id      UUID NOT NULL,
    status        TEXT,
    pnl_today     NUMERIC,
    positions     JSONB,
    current_task  TEXT
);
SELECT create_hypertable('agent_heartbeats', 'time');
```

**Retention Policies**:
- `market_bars`: 2 years (for backtesting)
- `performance_metrics`: 1 year
- `agent_heartbeats`: 30 days
- `agent_logs`: 90 days

### 4.3 Redis Usage

| Purpose | Redis Feature | Key Pattern | TTL |
|---|---|---|---|
| API response cache | Key-value | `cache:<endpoint>:<params>` | 30-60 seconds |
| User sessions | Key-value | `session:<user_id>` | 24 hours |
| Job queue | BullMQ (List + Sorted Set) | `bull:<queue_name>:*` | Until processed |
| Event bus | Redis Streams | `stream:<topic>` | Trimmed to 10,000 entries |
| Rate limiting | Sorted Set | `ratelimit:<key>` | Sliding window |
| Agent status cache | Hash | `agent:<id>:status` | 2 minutes |
| Circuit breaker state | Key-value | `circuit_breaker:<account_id>` | Until reset |
| Pub/sub for WebSocket | Pub/Sub channels | `ws:<channel>` | N/A (fire and forget) |

### 4.4 MinIO Bucket Structure

| Bucket | Contents | Retention |
|---|---|---|
| `phoenix-backtests` | Backtest result JSON, trade logs, equity curves | 1 year |
| `phoenix-skills` | Central skill repository (SKILL.md files) | Permanent |
| `phoenix-models` | Trained ML models (pickle, ONNX, PyTorch) | Permanent |
| `phoenix-code` | Agent-generated code bundles, strategy code | 1 year |
| `phoenix-reports` | Performance reports, daily summaries | 1 year |

---

## 5. Event Bus & Message Flow

### 5.1 Technology Choice: Redis Streams

**Decision**: Use Redis Streams as the primary event bus. NATS is the fallback if scale demands exceed Redis capabilities.

| Criterion | Redis Streams | NATS |
|---|---|---|
| Operational complexity | Zero (already running Redis) | New service to deploy and manage |
| Persistence | Append-only log with trimming | JetStream persistence available |
| Consumer groups | Native support | Native support |
| Throughput | ~100K msg/s (sufficient for trading) | ~10M msg/s (overkill for this use case) |
| Latency | Sub-millisecond | Sub-millisecond |
| Ecosystem | Part of Redis, same client library | Separate client library |

Redis Streams gives us event bus functionality without adding a new service. We already depend on Redis for caching and BullMQ. Only if we exceed ~50 OpenClaw instances or ~100K events/second would we need to migrate to NATS.

### 5.2 Stream Topics

| Stream Name | Publisher(s) | Consumer(s) | Purpose |
|---|---|---|---|
| `stream:trade-intents` | OpenClaw agents (via API) | Execution Service | Trade orders to place |
| `stream:agent-events` | OpenClaw Bridge | Orchestrator, Dashboard API | Agent status changes, lifecycle events |
| `stream:position-updates` | Execution Service, Monitoring Agents | Dashboard API, Global Monitor | Position opens, closes, PnL changes |
| `stream:heartbeats` | OpenClaw Bridge (every 60s) | Dashboard API | Instance health, agent statuses |
| `stream:agent-messages` | Agent Communication Router | Target OpenClaw Bridge | Inter-agent communication |
| `stream:backtest-progress` | Backtest Runner | Dashboard API | Backtest status and progress |
| `stream:connector-events` | Connector Manager | Dashboard API, OpenClaw agents | New messages from data sources |
| `stream:dev-agent-events` | Dev Agent (OC Instance C) | Dashboard API | Incidents, fixes, RL updates |
| `stream:automation-triggers` | Automation Scheduler | Orchestrator | Scheduled task triggers |
| `stream:alerts` | Global Monitor, Dev Agent | Dashboard API, Notification Service | System alerts |

### 5.3 Consumer Groups

Each consuming service creates a consumer group so that messages are load-balanced across replicas and acknowledged after processing:

```
XGROUP CREATE stream:trade-intents execution-service $ MKSTREAM
XGROUP CREATE stream:agent-events orchestrator-group $ MKSTREAM
XGROUP CREATE stream:agent-events dashboard-api-group $ MKSTREAM
XGROUP CREATE stream:position-updates global-monitor-group $ MKSTREAM
XGROUP CREATE stream:heartbeats dashboard-api-group $ MKSTREAM
```

### 5.4 Message Schema

All messages follow a consistent envelope:

```json
{
  "id": "evt_<ulid>",
  "type": "trade_intent.created",
  "source": "oc-live-trading-01/agent-echo",
  "timestamp": "2026-03-03T14:30:00.000Z",
  "data": { ... },
  "metadata": {
    "correlation_id": "job_<ulid>",
    "instance_id": "oc-live-trading-01",
    "agent_id": "agent-echo"
  }
}
```

---

## 6. OpenClaw Instance Architecture

### 6.1 Per-Instance Layout

Each OpenClaw VPS runs:

```
/opt/phoenix/
├── openclaw/                        # OpenClaw installation
│   ├── openclaw.json                # Multi-agent config (agents, bindings)
│   └── agents/
│       ├── live-trader-stocks/      # Agent workspace
│       │   ├── AGENTS.md            # Role, goals, instructions
│       │   ├── SOUL.md              # Personality, communication style
│       │   ├── TOOLS.md             # Allowed tools
│       │   ├── MEMORY.md            # Long-term knowledge
│       │   ├── HEARTBEAT.md         # Periodic tasks (strategy agents)
│       │   └── sessions/            # Session transcripts (JSONL)
│       ├── live-trader-options/
│       ├── trade-monitor/
│       └── incident-recovery/
│
├── skills/
│   └── phoenix/                     # Synced from central repo
│       ├── data/
│       ├── analysis/
│       ├── strategy/
│       ├── execution/
│       ├── risk/
│       ├── utility/
│       └── advanced/
│
├── bridge/                          # Bridge Service (sidecar)
│   ├── main.py                      # FastAPI app
│   ├── requirements.txt
│   └── Dockerfile
│
└── scripts/
    ├── sync-skills.sh               # Cron job to pull skills from MinIO
    ├── health-check.sh
    └── startup.sh
```

### 6.2 OpenClaw Configuration

**openclaw.json** (example for Instance D: Live Trading):
```json
{
  "agents": {
    "list": [
      { "id": "live-trader-stocks", "workspace": "/opt/phoenix/openclaw/agents/live-trader-stocks" },
      { "id": "live-trader-options", "workspace": "/opt/phoenix/openclaw/agents/live-trader-options" },
      { "id": "trade-monitor", "workspace": "/opt/phoenix/openclaw/agents/trade-monitor" },
      { "id": "incident-recovery", "workspace": "/opt/phoenix/openclaw/agents/incident-recovery" }
    ]
  },
  "bindings": [
    { "agentId": "live-trader-stocks", "match": { "channel": "api", "topic": "stock-signals" } },
    { "agentId": "live-trader-options", "match": { "channel": "api", "topic": "option-signals" } },
    { "agentId": "trade-monitor", "match": { "channel": "api", "topic": "position-updates" } }
  ],
  "model": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514"
  }
}
```

### 6.3 Bridge Service API

The Bridge Service is a lightweight FastAPI sidecar that the Control Plane uses to manage agents remotely:

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Instance health (CPU, memory, uptime, agent count) |
| `/heartbeat` | GET | All agent statuses, positions, PnL, recent trades |
| `/agents` | GET | List agents on this instance |
| `/agents` | POST | Create new agent (write config files, register in openclaw.json) |
| `/agents/:id` | GET | Agent detail (status, metrics, current task) |
| `/agents/:id` | PUT | Update agent config files |
| `/agents/:id` | DELETE | Remove agent |
| `/agents/:id/pause` | POST | Pause agent |
| `/agents/:id/resume` | POST | Resume agent |
| `/agents/:id/logs` | GET | Stream recent agent logs |
| `/skills/sync` | POST | Trigger skill pull from MinIO |

### 6.4 Skill Sync Mechanism

```
Central Skill Repo (MinIO: phoenix-skills bucket)
         │
    ┌────┴────────────────────────────────────┐
    │  Every 5 minutes (cron on each VPS):    │
    │                                          │
    │  1. aws s3 sync s3://phoenix-skills/     │
    │     /opt/phoenix/skills/phoenix/         │
    │     --endpoint-url http://10.0.1.1:9000  │
    │                                          │
    │  2. Compare checksums with last sync     │
    │                                          │
    │  3. If changes detected:                 │
    │     - Log changed skills                 │
    │     - Publish skill-updated event        │
    │       to Event Bus                       │
    └─────────────────────────────────────────┘
```

Skills in `~/.openclaw/skills/` (managed skills folder) have second-highest precedence in OpenClaw's skill resolution order, below workspace-level skills but above bundled skills.

---

## 7. Networking & Security

### 7.1 WireGuard VPN Topology

Hub-and-spoke from the Coolify server to all OpenClaw VPS nodes:

```
Node 1 (Coolify) ── 10.0.1.1/24
    │
    ├── Peer: Node 2 (OC-A) ── 10.0.1.10/32
    ├── Peer: Node 3 (OC-B) ── 10.0.1.11/32
    └── Peer: Node 4 (OC-C/D) ── 10.0.1.12/32
```

**Configuration (Node 1 -- Coolify server)**:
```ini
[Interface]
Address = 10.0.1.1/24
PrivateKey = <server_private_key>
ListenPort = 51820

[Peer]  # Node 2: OC-A
PublicKey = <node2_public_key>
AllowedIPs = 10.0.1.10/32
Endpoint = <node2_public_ip>:51820

[Peer]  # Node 3: OC-B
PublicKey = <node3_public_key>
AllowedIPs = 10.0.1.11/32
Endpoint = <node3_public_ip>:51820

[Peer]  # Node 4: OC-C/D
PublicKey = <node4_public_key>
AllowedIPs = 10.0.1.12/32
Endpoint = <node4_public_ip>:51820
```

All traffic between the Coolify server and OpenClaw nodes travels through the encrypted WireGuard tunnel. OpenClaw Bridge Services listen only on the WireGuard interface (10.0.1.x), not on public IPs.

### 7.2 Firewall Rules

**Node 1 (Coolify) -- Public Ports**:

| Port | Protocol | Source | Service |
|---|---|---|---|
| 22 | TCP | Admin IP only | SSH |
| 80 | TCP | Any | HTTP (redirect to 443) |
| 443 | TCP | Any | HTTPS (Dashboard + API) |
| 51820 | UDP | OpenClaw node IPs | WireGuard |

**Nodes 2-4 (OpenClaw) -- Public Ports**:

| Port | Protocol | Source | Service |
|---|---|---|---|
| 22 | TCP | Admin IP only | SSH |
| 51820 | UDP | Coolify server IP | WireGuard |

All other ports are blocked. Bridge Services (18800) and OpenClaw (18790) are accessible only via the WireGuard network.

### 7.3 Authentication & Authorization

**External (Dashboard users)**:
- JWT tokens issued by Auth Service (existing `services/auth-service/`)
- Access token: 60-minute expiry, stored in memory
- Refresh token: 7-day expiry, stored in localStorage
- MFA: TOTP (existing implementation)
- RBAC: 5 roles (admin, manager, trader, viewer, custom) with 20 granular permissions

**Internal (service-to-service)**:
- Bridge Service calls authenticated with a shared secret token (`X-Bridge-Token` header)
- The Coolify server is the only allowed client (enforced by WireGuard network + token)
- Redis requires password authentication
- PostgreSQL requires password authentication (credentials in environment variables)
- MinIO access via access key + secret key

### 7.4 Credential Security

- All API keys and broker credentials stored encrypted using Fernet symmetric encryption
- Encryption key (`CREDENTIAL_ENCRYPTION_KEY`) stored as environment variable, never in code
- Frontend never receives raw credentials, only masked previews (last 4 characters)
- Key rotation: re-encrypt all credentials when the encryption key is rotated
- Reuses existing `shared/crypto/credentials.py` from Phoenix v1

### 7.5 OpenClaw Sandboxing

- Agent code execution (Python scripts, ML model training) runs in Docker containers with no host access
- Docker socket not exposed to agents
- Network access limited to the WireGuard network and allowed API endpoints
- File system access limited to agent workspace directory
- Tool allowlists enforced per agent via TOOLS.md

---

## 8. Deployment Pipeline

### 8.0 Source repository and deployment

- **Source code:** PhoenixClaw organization repository (e.g. `PhoenixClaw/phoenix`). All builds and deployments use this repo as the source of truth.
- **Do not push to the earlier/original repository.** All pushes go to the PhoenixClaw org repo only.

### 8.1 CI/CD Pipeline

```
Developer pushes to main branch
         │
         ▼
GitHub Actions triggered
         │
         ├── Run linters (ruff, mypy, eslint)
         ├── Run unit tests (pytest, vitest)
         ├── Run integration tests
         │
         ▼ (all pass)
Build Docker images
         │
         ├── phoenixv2/dashboard:latest
         ├── phoenixv2/api:latest
         ├── phoenixv2/orchestrator:latest
         ├── phoenixv2/execution:latest
         ├── phoenixv2/backtest-runner:latest
         ├── phoenixv2/connector-manager:latest
         ├── phoenixv2/global-monitor:latest
         ├── phoenixv2/skill-sync:latest
         ├── phoenixv2/automation-scheduler:latest
         ├── phoenixv2/agent-comm-router:latest
         ├── phoenixv2/ws-gateway:latest
         └── phoenixv2/openclaw-bridge:latest
         │
         ▼
Push to GitHub Container Registry (ghcr.io)
         │
         ▼
Coolify webhook triggered
         │
         ▼
Coolify pulls latest images and redeploys
         │
         ▼
Health checks pass → traffic routed to new containers
```

### 8.2 Coolify Docker Compose

The Coolify deployment uses a single `docker-compose.coolify.yml` with all services. Key patterns from the existing production compose:

- All application services use `restart: unless-stopped`
- Resource limits (memory) set per service
- Environment variables injected via Coolify UI (not committed to repo)
- Shared Docker network for inter-service communication
- Named volumes for PostgreSQL (`pg-data`) and Redis (`redis-data`)

### 8.3 OpenClaw VPS Deployment

Each OpenClaw VPS is provisioned with a deployment script:

```bash
#!/bin/bash
# deploy-openclaw.sh -- Run on each OpenClaw VPS

# 1. Install dependencies
apt update && apt install -y docker.io wireguard python3.12 python3.12-venv nodejs npm

# 2. Configure WireGuard
cp wg0.conf /etc/wireguard/
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0

# 3. Install OpenClaw
npm install -g @openclaw/cli
openclaw onboard --skip-channel

# 4. Deploy Bridge Service
cd /opt/phoenix/bridge
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 5. Set up systemd services
cp openclaw.service /etc/systemd/system/
cp bridge.service /etc/systemd/system/
systemctl enable openclaw bridge
systemctl start openclaw bridge

# 6. Set up skill sync cron
echo "*/5 * * * * /opt/phoenix/scripts/sync-skills.sh" | crontab -
```

### 8.4 Deployment Sequence (Full)

| Step | Action | Prerequisite |
|---|---|---|
| 1 | Provision Coolify server (Hetzner CX42) | Hetzner account |
| 2 | Install Coolify on Node 1 | Node 1 provisioned |
| 3 | Provision OpenClaw VPS nodes (2-3 nodes) | Hetzner account |
| 4 | Configure WireGuard VPN on all nodes | All nodes provisioned |
| 5 | Deploy PostgreSQL + TimescaleDB on Coolify | Coolify installed |
| 6 | Deploy Redis on Coolify | Coolify installed |
| 7 | Deploy MinIO on Coolify | Coolify installed |
| 8 | Run database migrations (`alembic upgrade head`) | PostgreSQL running |
| 9 | Deploy Backend API on Coolify (includes Auth at `/auth`) | PostgreSQL, Redis running |
| 10 | Deploy Dashboard on Coolify | Backend API running |
| 11 | Deploy Orchestrator, Execution Service, Global Monitor | PostgreSQL, Redis running |
| 12 | Deploy remaining services (Connector Manager, Backtest Runner, etc.) | Core services running |
| 13 | Install OpenClaw on each VPS node | WireGuard configured |
| 14 | Deploy Bridge Service on each VPS node | OpenClaw installed |
| 15 | Register OpenClaw instances via dashboard | Bridge Service running |
| 16 | Upload initial skill catalog to MinIO | MinIO running |
| 17 | Trigger skill sync on all instances | Skills in MinIO |
| 18 | Configure connectors (Discord, Alpaca) via dashboard | All services running |
| 19 | Create first test agent and run backtest | Everything operational |

### 8.5 Rollback Strategy

- **Application services**: Coolify maintains previous image versions. One-click rollback to last deployment.
- **Database**: Alembic downgrade scripts for every migration. Test downgrades before deploying upgrades.
- **OpenClaw agents**: Agent config changes are version-controlled in the central repository. Rollback by reverting and syncing.
- **Skills**: MinIO versioning enabled. Revert to previous skill version by restoring from MinIO version history.

---

## 9. Monitoring & Observability

### 9.1 Metrics Collection

**Prometheus** scrapes metrics from all services every 15 seconds:

| Source | Endpoint | Key Metrics |
|---|---|---|
| Backend API | `/metrics` | Request count, latency, error rate |
| Execution Service | `/metrics` | Orders placed, fill rate, rejection rate |
| Global Monitor | `/metrics` | Portfolio value, drawdown, circuit breaker state |
| Orchestrator | `/metrics` | Jobs processed, queue depth, failure rate |
| OpenClaw Bridge | `/metrics` | Agent count, heartbeat latency, agent errors |
| PostgreSQL | `postgres_exporter` | Connections, query time, table sizes |
| Redis | `redis_exporter` | Memory usage, connected clients, stream lengths |
| Node Exporter | `:9100` (per VPS) | CPU, memory, disk, network |

### 9.2 Grafana Dashboards

| Dashboard | Panels |
|---|---|
| **System Overview** | CPU/memory per node, disk usage, network throughput, service health |
| **Trading Operations** | Total PnL (real-time), trade count, fill rate, average latency signal-to-order |
| **Agent Performance** | Per-agent PnL, win rate, trade frequency, error rate, status distribution |
| **Infrastructure** | PostgreSQL connections and query time, Redis memory and stream depth, MinIO storage |
| **Circuit Breaker** | Account-level loss tracking, breaker state, position count, exposure by sector |
| **OpenClaw Instances** | Per-instance agent count, CPU, memory, heartbeat latency, skill sync status |
| **Dev Agent** | Incident count, fix success rate, RL reward curve, action distribution |

### 9.3 Logging

**Loki** aggregates logs from all services:

- Application logs shipped via Docker logging driver (`loki` driver) or Promtail sidecar
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Structured JSON log format with fields: `timestamp`, `service`, `level`, `message`, `trace_id`
- OpenClaw agent logs shipped by Bridge Service to Loki

**Log Retention**: 30 days in Loki, 90 days in PostgreSQL `agent_logs` table.

### 9.4 Alerting Rules

| Alert | Condition | Severity | Notification |
|---|---|---|---|
| Service Down | Health check fails for 2 minutes | Critical | Discord + Email |
| Circuit Breaker Open | `circuit_breaker_state != CLOSED` | Critical | Discord + Telegram + Email |
| Agent Error | Agent error rate > 5% in 5 minutes | Warning | Discord |
| High Latency | Signal-to-order > 30 seconds | Warning | Dashboard |
| Database Full | Disk usage > 85% | Warning | Email |
| OpenClaw Instance Down | Heartbeat missing for 3 minutes | Critical | Discord + Email |
| Daily Loss Limit | Account daily loss > 3% | Warning | Discord + Telegram |
| Emergency Stop | Portfolio loss > 10% | Critical | All channels + kill switch |

### 9.5 Heartbeat Monitoring

The 1-minute heartbeat cycle provides continuous system awareness:

```
Every 60 seconds:
    │
    ├── Backend API sends GET /heartbeat to each Bridge Service
    │   (via WireGuard: http://10.0.1.10:18800/heartbeat)
    │
    ├── Each Bridge collects:
    │   - Agent statuses (running, paused, error)
    │   - Current positions per agent
    │   - PnL per agent (today)
    │   - Last trade per agent
    │   - Instance CPU/memory
    │
    ├── Backend aggregates all responses
    │
    ├── Writes to agent_heartbeats hypertable (TimescaleDB)
    │
    ├── Updates agent status cache in Redis
    │
    └── Pushes delta to connected WebSocket clients
```

If a heartbeat fails 3 consecutive times (3 minutes), the instance is marked offline and an alert fires.

---

## 10. Scaling Strategy

### 10.1 Horizontal Scaling

| Component | Scaling Method | Trigger |
|---|---|---|
| OpenClaw agents | Add more VPS nodes with OpenClaw instances | Agent count > 20 per instance, or CPU > 80% |
| Backend API | Run multiple Uvicorn workers (already supports `--workers N`) | Request latency > 500ms |
| Orchestrator | Run multiple worker processes (BullMQ supports competing consumers) | Job queue depth > 100 |
| Execution Service | Run 2 replicas with deduplication | Order volume > 100/minute |
| Backtest Runner | Run multiple Docker-in-Docker workers | Backtest queue depth > 5 |

### 10.2 Vertical Scaling

| Component | Current | Upgrade Path |
|---|---|---|
| Coolify server | CX42 (8 vCPU / 16 GB) | CX52 (16 vCPU / 32 GB) → dedicated server |
| OpenClaw VPS | CX32 (4 vCPU / 8 GB) | CX42 (8 vCPU / 16 GB) for more agents per instance |
| PostgreSQL | Shared on Coolify | Dedicated VPS with NVMe SSD for better IOPS |

### 10.3 Database Scaling

| Strategy | When | Implementation |
|---|---|---|
| Connection pooling | > 50 concurrent connections | Deploy PgBouncer in front of PostgreSQL |
| Read replicas | Read queries dominate and latency increases | PostgreSQL streaming replication to read-only replica |
| Table partitioning | `agent_logs` > 100M rows | Partition by month using TimescaleDB |
| Archive old data | Disk usage > 80% | Move data older than retention period to MinIO (Parquet) |

### 10.4 Event Bus Scaling

| Strategy | When | Implementation |
|---|---|---|
| Redis Streams trimming | Stream length > 100K entries | `XTRIM stream:* MAXLEN ~ 10000` on a schedule |
| Separate Redis instances | Redis memory > 75% | Dedicated Redis for event bus, separate for cache/BullMQ |
| Migrate to NATS | > 50 instances or > 100K events/sec | Deploy NATS cluster, update all publishers/consumers |

### 10.5 Scaling Milestones

| Users / Agents | Infrastructure | Estimated Cost |
|---|---|---|
| 1 user, 5-10 agents | 2 nodes (Coolify + 1 OC VPS) | ~$56/mo |
| 1 user, 20-40 agents | 4 nodes (Coolify + 3 OC VPS) | ~$84/mo |
| 3-5 users, 50-100 agents | 6 nodes (larger Coolify + 5 OC VPS) | ~$200/mo |
| 10+ users, 200+ agents | Dedicated servers + NATS cluster | ~$500+/mo |
