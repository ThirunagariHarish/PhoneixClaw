# Phoenix Trade Bot

An **agent-first AI trading platform** where every agent is a Claude Code session. Agents read instructions from `CLAUDE.md` files, execute Python tools, share knowledge, and self-improve.

## How It Works

1. **Backtest** a Discord analyst channel to train ML models and discover trading patterns
2. **Approve** the agent to go live with learned rules and trained models
3. **Claude Code agents** monitor Discord in real-time, process signals through the ML pipeline, and execute trades on Robinhood
4. **Position monitor sub-agents** spawn per trade to find optimal exit points
5. **Supervisor agents** analyze performance nightly and propose improvements

See [docs/architecture/01_how_project_works.md](docs/architecture/01_how_project_works.md) for the full walkthrough.

## Quick Start

```bash
make setup          # First-time: install deps + create .env
make dev-run        # Start infra + API (:8011) + Dashboard (:3000)
```

Open `http://localhost:3000` in your browser.

### Prerequisites

| Tool | Version |
|------|---------|
| Python | >= 3.11 |
| Node.js | >= 18 |
| Docker + Compose | >= 24.x |

### Setup

```bash
git clone <repo-url>
cd ProjectPhoneix

make dev-install        # Python deps (editable)
make dashboard-install  # npm deps
make env-file           # Create .env from template

# Edit .env with your secrets:
#   DATABASE_URL, REDIS_URL, JWT_SECRET_KEY,
#   ANTHROPIC_API_KEY, CREDENTIAL_ENCRYPTION_KEY
```

## Architecture

```
User ─── Dashboard (React) ─── FastAPI API ─── PostgreSQL + Redis
                                    │
                            AgentGateway
                                    │
                ┌───────────────────┼───────────────────┐
                ▼                   ▼                   ▼
         Backtester          Live Analyst         Sub-Agents
        (one-shot)          (continuous)        (per position)
                │                   │                   │
                └───── Python Tools (enrich, infer, ────┘
                       risk, TA, execute, MCP)
```

Every agent is a Claude Code subprocess with its own working directory, tools, and config. The Python services provide infrastructure; the intelligence lives in the agents.

### Key Directories

```
agents/              Agent templates + backtesting pipeline
  backtesting/       12-step ML pipeline (transform → train → evaluate → create agent)
  templates/         10 agent types (live-trader, position-monitor, supervisor, etc.)
apps/
  api/               FastAPI backend (30+ route modules)
  dashboard/         React 18 + Vite + Tailwind
shared/              DB models (28+ tables), broker adapters, LLM client, NLP
services/            Microservices (execution, orchestrator, connector-manager, etc.)
docs/                Architecture, operations, development, specs
tests/               unit/ + integration/ + e2e/ + regression/ + benchmark/
```

## Testing

```bash
make test                # Unit tests
make test-integration    # Integration tests
make test-dashboard      # Dashboard tests
make go-live-regression  # Full regression suite
```

## Deployment

Deployed via Coolify on VPS. See [docs/operations/deployment-guide.md](docs/operations/deployment-guide.md).

```bash
make up     # Docker full stack
make down   # Stop
make logs   # Watch logs
```

## Documentation

- [How Phoenix Works](docs/architecture/01_how_project_works.md) — end-to-end walkthrough
- [Architecture](docs/architecture/02_architecture.md) — system design and diagrams
- [Agent Development](docs/development/agent-development.md) — creating new agent types
- [Deployment Guide](docs/operations/deployment-guide.md) — VPS setup with Coolify
- [Go-Live Checklist](docs/dev/go-live-regression-checklist.md) — regression and sign-off

## License

Private — All rights reserved.
