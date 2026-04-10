# System Architecture — Phoenix V3 Cloud-First

## Overview

Phoenix is a multi-agent trading platform. **Claude Code Cloud Tasks** (on Anthropic's infrastructure) handle intelligence work — backtesting, analysis, and strategy reviews. **Python workers** on the Phoenix server handle real-time execution — signal processing, risk checks, and trade execution.

**PostgreSQL is the single source of truth** — all agent state, trades, metrics, logs, and backtest results live in the database. Agents communicate via HTTP callbacks to the Phoenix API. The dashboard reads from the same DB via REST polling.

## Architecture Tiers

### Tier 1 — Claude Code Cloud (Anthropic Infrastructure)

| Component | Schedule | Purpose |
|-----------|----------|---------|
| Backtesting Task | On-demand (Remote Task) | Full pipeline: ingest → transform → train → evaluate → patterns |
| Pre-Market Analysis | Daily 7am (Scheduled Task) | Scan market conditions, write briefing to DB |
| Strategy Review | Weekly (Scheduled Task) | Review agent performance, suggest parameter adjustments |
| Agent Teams (future) | On-demand | Coordinate multiple agents for research tasks |

Claude Code Cloud Tasks clone the repo, run Python tools, and POST results to the Phoenix API via HTTP callbacks. They self-heal on errors and require no VPS management.

### Tier 2 — Phoenix Server (Coolify VPS)

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Phoenix API | FastAPI | Agent CRUD, authentication, callbacks, dashboards |
| PostgreSQL | Docker | ALL state: agents, trades, signals, logs, backtest results |
| Task Runner | Python asyncio | Run backtesting pipeline as local subprocess (alternative to Cloud Tasks) |
| Trading Workers | Docker containers | Real-time signal processing, risk checks, trade execution |
| Dashboard | React + Vite | Agent management, metrics, chat, monitoring |

### Tier 3 — Communication

| Channel | Direction | Protocol |
|---------|-----------|----------|
| Cloud Task → API | Inbound | HTTP POST callbacks to `/backtest-progress`, `/live-trades`, `/metrics` |
| Dashboard → API | Outbound | REST API polling via React Query |
| Worker → DB | Direct | SQLAlchemy (same server) |
| API → Worker | Local | Docker SDK / subprocess |

## Agent Lifecycle

```
Dashboard Wizard (Channel → Risk → Review → Create)
  → Agent row created (status: BACKTESTING)
  → Task Runner spawns backtesting subprocess
  → Each step updates progress in DB
  → Pipeline completes → status: BACKTEST_COMPLETE
  → User reviews backtest results
  → User approves → status: APPROVED/PAPER
  → User promotes → status: RUNNING (Docker worker starts)
```

## Directory Layout

```
ProjectPhoneix/
├── apps/
│   ├── api/                     # FastAPI backend
│   │   └── src/
│   │       ├── routes/          # Agent, connector, trades, backtests endpoints
│   │       └── services/        # task_runner.py, agent_builder.py
│   └── dashboard/               # React frontend
│       └── src/pages/           # Agents, Connectors, AgentDashboard, etc.
├── agents/
│   ├── backtesting/tools/       # Python backtesting pipeline scripts
│   ├── templates/live-trader-v1/ # Live agent template (tools, skills, CLAUDE.md)
│   └── schema/                  # Manifest validation, characters.json
├── services/                    # Docker Compose microservices
│   ├── backtest-runner/         # Backtest orchestration
│   ├── execution/               # Live trading pipeline
│   └── ...                      # Other services
├── shared/
│   └── db/
│       ├── models/              # SQLAlchemy ORM models
│       └── migrations/          # Alembic migration scripts
└── specs/                       # Architecture and feature specifications
```

## Why Python Workers for Live Trading (Not Claude Code)

Claude Code Cloud Tasks have a **1-hour minimum interval** and **clone fresh each run** (no persistent state). Live trading needs:

- Sub-second Discord signal processing
- Persistent websocket connections  
- Continuous position monitoring (60-second ticks)

All live trading tools (`discord_listener.py`, `inference.py`, `risk_check.py`, `robinhood_mcp.py`) are **pure Python** — no LLM calls needed at runtime. Docker containers are faster, cheaper, and more reliable for this use case.

Claude Code adds value for **intelligence** (backtesting, analysis, strategy) — not for **execution** (listening, computing, trading).

## Key Design Decisions

1. **No VPS management** — eliminated SSH/SCP layer (~1,300 lines removed in V3)
2. **DB as communication hub** — no file polling, no remote reads, no SSH tunnels
3. **Local backtesting** — task_runner.py spawns subprocess on API server
4. **Cloud backtesting** — Claude Code Remote Tasks POST progress to `/backtest-progress`
5. **Manifest-driven agents** — agent_builder.py creates structured configs from templates
6. **Worker isolation** — each live trading agent runs in its own Docker container

## Future: Agent Teams

With this architecture, agent teams are straightforward:

- An "Agent Team" is a DB record grouping multiple Agents
- Each agent has its own trading worker container
- A Claude Code Cloud Scheduled Task coordinates the team (daily strategy meeting)
- Team members share signals via the PostgreSQL `agent_signals` table
- The dashboard shows team performance alongside individual agent performance
