# Phoenix Architecture

## High-Level Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          USER (You)                                  │
│   ┌────────────┐    ┌────────────┐    ┌───────────────┐            │
│   │  Dashboard │    │  WhatsApp  │    │  Terminal     │            │
│   │  (React)   │    │  (replies) │    │  (SSH/docker) │            │
│   └─────┬──────┘    └──────┬─────┘    └───────┬───────┘            │
└─────────┼──────────────────┼──────────────────┼────────────────────┘
          │                  │                  │
          │ REST + WS        │ Webhook          │ docker exec
          ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       PHOENIX API (FastAPI)                          │
│   ┌──────────────────────────────────────────────────────────────┐ │
│   │  Routes: agents, trades, positions, agent-messages,          │ │
│   │          chat, morning-routine, whatsapp_webhook, ...        │ │
│   └──────────────────────────────────────────────────────────────┘ │
│   ┌──────────────────────────────────────────────────────────────┐ │
│   │  Services:                                                    │ │
│   │   • AgentGateway       (spawns Claude Code sessions)         │ │
│   │   • NotificationDispatcher (DB + WS + WhatsApp)              │ │
│   │   • MorningRoutineOrchestrator                               │ │
│   └──────────────────────────────────────────────────────────────┘ │
└──────┬─────────────────────┬────────────────┬─────────────────────┘
       │                     │                │
       │                     │                │
       ▼                     ▼                ▼
┌──────────┐         ┌──────────────┐    ┌──────────────────────┐
│PostgreSQL│         │ Redis        │    │ Claude Code Sessions │
│  29+     │         │ • Streams    │    │  (one per agent)     │
│  tables  │         │ • Pub/Sub    │    │                      │
└──────────┘         │ • Cache      │    │  Each session is a   │
                     └──────────────┘    │  separate process    │
                                         │  with its own        │
                                         │  working directory   │
                                         └──────────────────────┘
                                                  │
                            ┌─────────────────────┼─────────────────────┐
                            ▼                     ▼                     ▼
                    ┌───────────────┐   ┌──────────────────┐   ┌─────────────┐
                    │ Backtester    │   │ Live Analyst     │   │ Sub-Agents  │
                    │ (one-shot)    │   │ (continuous)     │   │ (per pos.)  │
                    └───────┬───────┘   └────────┬─────────┘   └──────┬──────┘
                            │                    │                    │
                            ▼                    ▼                    ▼
                    ┌───────────────────────────────────────────────────┐
                    │              External Services                    │
                    │                                                   │
                    │  Discord  •  Reddit  •  Twitter  •  Unusual      │
                    │  Robinhood  •  yfinance  •  Anthropic API        │
                    │  WhatsApp Cloud API  •  OpenAI                   │
                    └───────────────────────────────────────────────────┘
```

---

## The Three Layers

### 1. Control Plane (FastAPI + Postgres + Redis + Dashboard)

**Purpose:** Orchestrate agents, persist state, serve UI, dispatch notifications.

**Components:**
- **FastAPI app** (`apps/api/`) — REST API + WebSocket gateway
- **PostgreSQL** — single source of truth for all state
- **Redis** — pub/sub for inter-agent messages, streams for WebSocket events, cache for hot data
- **React Dashboard** (`apps/dashboard/`) — Vite + Tailwind + Radix UI

**Key files:**
- `apps/api/src/main.py` — FastAPI app + router registration
- `apps/api/src/services/agent_gateway.py` — Claude Code session lifecycle
- `apps/api/src/services/notification_dispatcher.py` — Multi-channel notifications
- `shared/db/models/` — SQLAlchemy ORM models
- `shared/db/migrations/` — Alembic migrations

### 2. Execution Plane (Claude Code Agents)

**Purpose:** Run the actual trading intelligence.

Each agent is a `claude-agent-sdk` Python `query()` invocation that spawns a Claude Code subprocess with:
- A working directory (e.g. `/app/data/live_agents/{id}/`)
- A `CLAUDE.md` instructions file
- A `tools/` subfolder of Python scripts the agent can call via `Bash`
- A `config.json` with credentials and parameters
- `permission_mode="dontAsk"` so the agent runs unattended
- `allowed_tools=["Bash", "Read", "Write", "Edit", "Grep", "Glob"]`

**Where they live:**
Currently all agents run as subprocesses inside the `phoenix-api` Docker container. The API process spawns them via `claude_agent_sdk.query()` and tracks them in the `_running_tasks` dict + `agent_sessions` table.

For the future, the AgentSession model has `host_name` and `pid` fields ready for distributing agents across multiple VPS nodes.

**Agent types:**
| Type | Lifecycle | Template |
|---|---|---|
| Backtester | One-shot (~15-30 min) | `agents/backtesting/` |
| Analyst | Continuous (until stopped) | `agents/templates/live-trader-v1/` |
| Position monitor | Continuous (until position closes) | `agents/templates/position-monitor-agent/` |
| Unusual Whales | Continuous polling | `agents/templates/unusual-whales-agent/` |
| Social Sentiment | Continuous polling | `agents/templates/social-sentiment-agent/` |
| Strategy | Continuous polling | `agents/templates/strategy-agent/` |
| Supervisor | Daily (one-shot) | `agents/templates/supervisor-agent/` |

### 3. Data Plane (External APIs + ML Models + Storage)

**Purpose:** Market data, broker execution, model artifacts.

- **yfinance** — historical OHLCV (with disk cache in `output/price_cache/`)
- **Robinhood** — broker via `robin_stocks` Python lib + custom MCP server (`robinhood_mcp.py`)
- **Discord API** — for the analyst to monitor channels
- **Reddit (PRAW)** — for the social sentiment agent
- **Twitter API v2 (tweepy)** — for the social sentiment agent
- **Unusual Whales API** — options flow data
- **Anthropic API** — Claude Code SDK + LLM pattern analysis
- **OpenAI** (optional) — alternative LLM
- **Meta WhatsApp Cloud API** — outbound notifications + inbound webhook

---

## State Machine

Every agent goes through this lifecycle:

```
              ┌─────────┐
              │ CREATED │ ◄── User creates agent in dashboard
              └────┬────┘
                   │ Backtest spawned
                   ▼
            ┌─────────────┐
            │ BACKTESTING │ ◄── Claude Code session running pipeline
            └──────┬──────┘
                   │ Pipeline complete + manifest loaded
                   ▼
        ┌────────────────────┐
        │ BACKTEST_COMPLETE  │ ◄── User reviews metrics in dashboard
        └─────────┬──────────┘
                  │ POST /approve
                  ▼
            ┌──────────┐         ┌─────────┐
            │ APPROVED │ or      │  PAPER  │
            └─────┬────┘         └────┬────┘
                  │ Auto-spawn live    │ Auto-spawn live
                  ▼                    ▼
              ┌─────────┐
              │ RUNNING │ ◄── Claude Code session live
              └────┬────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
        ▼          ▼          ▼
   ┌─────────┐ ┌──────┐  ┌────────┐
   │ PAUSED  │ │ERROR │  │STOPPED │
   └─────┬───┘ └──────┘  └────────┘
         │ POST /resume
         ▼
     [back to RUNNING]
```

---

## Inter-Agent Communication

Agents share knowledge through **two transport layers**:

### 1. Persistent (DB + REST)
Source of truth for audit trail and replay.

```
Agent A                                          Agent B
   │                                                │
   │ POST /api/v2/agent-messages                    │
   │ {from, to, intent, data}                       │
   ▼                                                │
┌──────────────────┐                                │
│  agent_messages  │                                │
│  (Postgres)      │                                │
└──────────────────┘                                │
                                                    │
                       Agent B periodically polls:  │
                       GET /api/v2/agent-messages?  │
                       to_agent_id=B&status=pending │
                                                    ▼
                                              [reads message]
                                                    │
                                                    │ PATCH /mark-read
                                                    ▼
                                              [marked READ]
```

### 2. Real-time (Redis Pub/Sub)
For instant delivery to agents with active subscribers.

When `POST /api/v2/agent-messages` is called, the route ALSO publishes to:
- `phoenix:agent-knowledge:{to_agent_id}` (direct)
- `phoenix:agent-knowledge:broadcast` (if `to_agent_id` is null)

The `RedisAgentTransport` consumer (in `services/agent-comm/src/redis_transport.py`) can subscribe and deliver messages instantly.

### Knowledge Intents (standardized)

Defined in `services/agent-comm/src/protocol.py`:

```python
class KnowledgeIntent(str, Enum):
    MARKET_BRIEFING = "market_briefing"
    POSITION_UPDATE = "position_update"
    RISK_ALERT = "risk_alert"
    EXIT_SIGNAL = "exit_signal"
    STRATEGY_INSIGHT = "strategy_insight"
    HEADLINE_ALERT = "headline_alert"
    UNUSUAL_FLOW = "unusual_flow"
    SELL_SIGNAL = "sell_signal"
    MORNING_RESEARCH = "morning_research"
    PATTERN_ALERT = "pattern_alert"
    MARKET_REGIME = "market_regime"
```

---

## Notification Dispatch

Notifications fan out from one source to multiple channels:

```
report_backtest_progress(event_type=trade_entry)
              │
              ▼
   NotificationDispatcher.dispatch()
              │
       ┌──────┼──────────┬─────────┐
       ▼      ▼          ▼         ▼
   ┌─────┐ ┌────────┐ ┌──────┐ ┌────────┐
   │ DB  │ │  WS    │ │WhatsApp│ │Twitter│
   │     │ │(Redis  │ │        │ │(future)│
   │     │ │Stream) │ │        │ │        │
   └─────┘ └────────┘ └──────┘ └────────┘
              │
              ▼
        Dashboard subscribes to
        WS channel, gets push update
```

---

## Risk Chain

Every trade goes through 3 layers before execution:

```
Signal from Discord/UW/Reddit/Strategy
              │
              ▼
   ┌─────────────────────┐
   │ 1. Agent-Level Risk │ ── Per-agent: position size, daily limits
   └──────────┬──────────┘
              │ pass
              ▼
   ┌─────────────────────┐
   │ 2. Execution Risk   │ ── Per-trade: stop loss valid, price reasonable
   └──────────┬──────────┘
              │ pass
              ▼
   ┌─────────────────────┐
   │ 3. Global Risk      │ ── Account-wide: total exposure, drawdown
   └──────────┬──────────┘
              │ pass
              ▼
        BROKER EXECUTION
        (Robinhood MCP)
              │
              ▼
       Spawn position
       monitor sub-agent
```

Source: `services/execution/src/risk_chain.py`

---

## Sandboxing & Permissions

Each agent has a `.claude/settings.json` that locks down what it can do:

```json
{
  "permissions": {
    "allow": [
      "Bash(python *)", "Bash(python3 *)", "Bash(pip *)",
      "Bash(curl *)", "Read", "Write", "Edit", "Grep", "Glob"
    ],
    "deny": [
      "Bash(rm -rf /)", "Bash(rm -rf ~)",
      "Bash(git push --force *)", "Bash(shutdown *)", "Bash(reboot *)"
    ]
  },
  "hooks": {
    "SessionStart": [{"command": "python3 tools/report_to_phoenix.py --event session_start"}],
    "Stop": [{"command": "python3 tools/report_to_phoenix.py --event session_stop"}]
  }
}
```

This means an agent CANNOT:
- Access files outside its working directory (cwd is locked to `data/live_agents/{id}/`)
- Run destructive commands
- Push git changes
- Access other agents' data

But CAN:
- Run any Python script in `tools/`
- Make HTTP calls to Phoenix API and external services
- Read/write its own working directory

---

## Deployment

Deployed via Coolify on a VPS:

- `docker-compose.coolify.yml` defines the service stack
- `apps/api/Dockerfile` builds the API container
- `apps/api/entrypoint.sh` runs migrations on container startup, then `uvicorn`
- Coolify auto-deploys on git push to `main`

---

## Module Map

```
apps/
├── api/
│   ├── src/
│   │   ├── main.py                  # FastAPI app
│   │   ├── routes/                  # 30+ route modules
│   │   ├── services/
│   │   │   ├── agent_gateway.py     # Spawn/manage Claude Code sessions
│   │   │   └── notification_dispatcher.py
│   │   ├── middleware/              # Auth, rate limit, error handling
│   │   └── tests/
│   ├── Dockerfile
│   └── entrypoint.sh                # Auto-migration script
│
└── dashboard/                       # React + Vite frontend

shared/
├── db/
│   ├── engine.py                    # SQLAlchemy async engine
│   ├── models/                      # ORM models (29+ tables)
│   └── migrations/                  # Alembic migrations 001-013
├── kafka_utils/                     # Kafka producer/consumer/DLQ
├── crypto/                          # Fernet encryption for credentials
├── whatsapp/sender.py               # Meta Cloud API client
├── unusual_whales/client.py         # UW API client
├── nlp/                             # FinBERT sentiment classifier
├── llm/                             # Anthropic + OpenAI clients
└── notifications/                   # Notification dispatcher (delegates to apps/api)

services/
├── orchestrator/
│   └── src/
│       ├── morning_routine.py       # Pre-market orchestration
│       └── state_machine.py         # Agent lifecycle
├── execution/
│   └── src/
│       ├── executor.py
│       ├── risk_chain.py
│       └── live_pipeline.py
├── agent-comm/
│   └── src/
│       ├── protocol.py              # Message envelope + KnowledgeIntent
│       └── redis_transport.py       # Redis pub/sub transport
├── position-monitor/                # (Legacy daemon, replaced by sub-agents)
├── backtest-runner/                 # (Legacy, replaced by Claude Code)
└── ...

agents/
├── backtesting/
│   ├── CLAUDE.md                    # Backtester instructions
│   └── tools/                       # 12-step pipeline scripts
└── templates/
    ├── live-trader-v1/              # Discord analyst agent
    ├── position-monitor-agent/      # Position exit sub-agent
    ├── unusual-whales-agent/        # Options flow agent
    ├── social-sentiment-agent/      # Reddit/Twitter agent
    ├── strategy-agent/              # Rule-based strategy
    └── supervisor-agent/            # AutoResearch nightly

scripts/
├── init_db.py                       # Bootstrap DB schema
└── coolify-deploy-via-ssh.sh
```

---

## Summary

Phoenix is **agents calling tools**, not "code that runs trades":

1. **Control plane** (FastAPI + Postgres) provides infrastructure
2. **Execution plane** (Claude Code sessions) provides intelligence
3. **Data plane** (external APIs + ML models) provides reality

The novelty is that the agents are NOT special — they are vanilla Claude Code processes reading vanilla `CLAUDE.md` files. All Phoenix-specific logic lives in:
- The agent prompts (`CLAUDE.md` in each template)
- The Python tools the agents invoke
- The orchestration in `agent_gateway.py`

Anyone can add a new agent type by creating a new template directory with a `CLAUDE.md` and tool scripts.
