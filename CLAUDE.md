# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Phoenix Trade Bot — an agent-first AI trading platform where every agent is a Claude Code session. Monorepo with a React/Vite dashboard, FastAPI backend, PostgreSQL, Redis, and Claude SDK agents for automated trading. Python 3.11+, Node.js 18+.

**Core principle**: Claude SDK agents are the brain. Python tools are focused, single-purpose scripts the agents invoke. The intelligence lives in the agents' CLAUDE.md files and the tools they call.

## Common Commands

### Quick Start
```bash
make setup          # First-time: install deps + create .env
make dev-run        # One command: infra + API (:8011) + Dashboard (:3000)
```

### Development
```bash
make dev-install              # Install Python prod + dev deps (editable)
make dashboard-install        # Install dashboard npm deps
make infra-up                 # Start Postgres, Redis (via Docker or Homebrew)
make infra-down               # Stop infrastructure
make run-api                  # API only on :8011
make run-dashboard            # Dashboard only on :3000
make run-core                 # API + Dashboard together
```

### Testing
```bash
make test                     # tests/unit + apps/api/tests/unit (split runs)
make test-api                 # apps/api/tests/unit only
make test-api-all             # All apps/api/tests (integration may need DB)
make test-integration         # tests/integration/
make test-e2e                 # Playwright (needs API + dashboard running)
make go-live-regression       # test + test-integration + test-bridge + test-dashboard
make go-live-regression-quality  # lint + typecheck
make db-alembic-heads         # Show Alembic head (expect 038_decision_trail)
make test-dashboard           # Dashboard tests (npm)
make test-bridge              # OpenClaw Bridge tests
make test-cov                 # Tests with coverage (HTML + terminal)
make benchmark                # Latency benchmark (p50/p95/p99)
```

Go-live checklist: [docs/dev/go-live-regression-checklist.md](docs/dev/go-live-regression-checklist.md).

Single test file: `python3 -m pytest tests/unit/test_foo.py -v --tb=short`
Single test: `python3 -m pytest tests/unit/test_foo.py::test_name -v`

### Code Quality
```bash
make lint                     # Ruff linter (shared/, services/, apps/, tests/)
make lint-fix                 # Auto-fix lint issues
make typecheck                # MyPy on shared/
```

### Database
```bash
make db-init                  # Bootstrap tables (no Alembic)
make db-migrate msg="desc"    # Generate Alembic migration
make db-upgrade               # Apply pending migrations
make db-downgrade             # Revert last migration
```

### Docker (Full Stack)
```bash
make up / make down / make logs / make status
```

## Architecture

See [docs/architecture/01_how_project_works.md](docs/architecture/01_how_project_works.md) for the full walkthrough and [docs/architecture/02_architecture.md](docs/architecture/02_architecture.md) for diagrams.

### Agent-First Design

Every agent is a **Claude Code session** running in a sandboxed working directory with a `CLAUDE.md` instructions file and `tools/` of Python scripts. Agents are NOT Python daemons — they are real Claude Code processes that reason, call tools, inspect outputs, and fix errors.

**Agent Gateway** (`apps/api/src/services/agent_gateway.py`) is the single entry point for all agent lifecycle operations — no other agent-starting mechanism exists.

### Key Directories
- `apps/api/src/` — FastAPI backend (30+ route modules, pydantic-settings config, JWT auth middleware)
- `apps/dashboard/src/` — React 18 + Vite + Radix UI + Tailwind + TanStack Query
- `shared/` — Importable libraries: DB models (28+ tables via SQLAlchemy), broker adapters, LLM client, NLP, crypto (Fernet)
- `services/` — Microservices: orchestrator, execution, backtest-runner, llm-gateway, ws-gateway, etc. Hyphen-named dirs with import aliasing in `services/__init__.py`
- `openclaw/bridge/` — Bridge Service for remote OpenClaw agent management
- `agents/backtesting/` — Backtesting agent pipeline (12-step: transform → enrich → embed → preprocess → train models → evaluate → explain → patterns → LLM analysis → validate → create live agent)
- `agents/templates/` — Agent templates: live-trader-v1, position-monitor-agent, supervisor, morning-briefing, etc.
- `docs/` — All documentation (architecture, operations, development, specs, PRDs, releases)
- `tests/` — unit/, integration/, e2e/ (Playwright), regression/, benchmark/

### Live Trading Flow (Agent-Driven)
1. Discord messages → Redis stream (via message-ingestion service)
2. `signal_listener.py` watches Redis, writes signals as JSON files
3. Claude agent reads each signal file, calls tools in sequence:
   - `parse_signal.py` → extract ticker, direction, price
   - `enrich_single.py` → 200+ market features
   - `inference.py` → ML model prediction (TRADE/SKIP)
   - Agent applies its own reasoning + learned rules
   - `risk_check.py` → position/exposure limits
   - `technical_analysis.py` → TA confirmation
   - `execute_trade.py` → Robinhood MCP order + Phoenix recording
4. Position monitor sub-agent spawned per trade
5. Sell signals routed from primary agent to sub-agents

### Design Patterns
- **Repository pattern** for all DB access (no raw SQL in services)
- **State machine** for agent lifecycle (created → backtesting → approved → running → paused/stopped)
- **Circuit breaker** (three-state) for broker calls
- **3-layer risk chain**: agent → execution → global
- **Event bus**: Redis Streams with pub-sub consumers
- **Centralized config**: env vars via `shared/config/base_config.py` and `apps/api/src/config.py`

### ML Pipeline
Training runs 8+ models sequentially: XGBoost, LightGBM, CatBoost, Random Forest, LSTM, Transformer, TFT, TCN → Hybrid ensemble + Meta-learner. Features span ~200 attributes across price action, technicals, volume, market context, time, sentiment, and options data.

## Code Style & Tooling

- **Python**: Ruff (E, F, I, N, W rules), line-length 120, target py311. MyPy strict.
- **Testing**: pytest with `asyncio_mode = "auto"`. Tests in `tests/` and `apps/api/tests/`. Fixtures use SQLite in-memory for DB.
- **Frontend**: React 18, Vite, TypeScript, Tailwind CSS, Radix UI.
- **PYTHONPATH**: Must be set to repo root (`.`) when running services or tests outside Make.
- **Pre-commit hooks**: Ruff auto-fix, trailing whitespace, YAML/JSON check.

## Environment Variables

All services read from `.env` (git-ignored). Key vars: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, `ANTHROPIC_API_KEY`, `BRIDGE_TOKEN`. Run `make env-file` to generate from `.env.example`.

The Makefile provides sensible local defaults so services can run without `.env` when launched via `make run-*`.
