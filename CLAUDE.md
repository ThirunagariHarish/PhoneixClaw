# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Phoenix Trade Bot — an enterprise multi-tenant AI trading platform. Monorepo with a React/Vite dashboard, FastAPI backend, PostgreSQL, Redis, Kafka, and OpenClaw AI agents for automated trading. Python 3.11+, Node.js 18+.

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
make test                     # All unit tests (tests/unit/ + apps/api/tests/)
make test-api                 # API tests only
make test-dashboard           # Dashboard tests (npm)
make test-bridge              # OpenClaw Bridge tests
make test-cov                 # Tests with coverage (HTML + terminal)
make benchmark                # Latency benchmark (p50/p95/p99)
```

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

### Three-Plane Design

**Control Plane** — Single server running the dashboard, API, PostgreSQL, Redis, and the BullMQ orchestrator for agent lifecycle.

**Execution Plane** — Remote VPS nodes each running an OpenClaw instance with AI agents, workspaces, and a Bridge Service sidecar (REST API for Control Plane communication).

**Shared Services** — MinIO (artifact storage), TimescaleDB (market data), Execution Service (broker adapters for Alpaca/IBKR), Prometheus + Grafana.

### Key Directories
- `apps/api/src/` — FastAPI backend (30+ route modules, pydantic-settings config, JWT auth middleware)
- `apps/dashboard/src/` — React 18 + Vite + Radix UI + Tailwind + TanStack Query
- `shared/` — Importable libraries: DB models (28+ tables via SQLAlchemy), Kafka utils, broker adapters, LLM client, backtest engine, NLP, crypto (Fernet)
- `services/` — Microservices: orchestrator, execution, backtest-runner, llm-gateway, ws-gateway, position-monitor, etc.
- `openclaw/bridge/` — Bridge Service for remote OpenClaw agent management
- `agents/backtesting/` — Backtesting agent pipeline (9-step: transform → enrich → embed → preprocess → train 8 models → evaluate → explain → patterns → create live agent)
- `tests/` — unit/, integration/, e2e/ (Playwright), benchmark/

### Design Patterns
- **Repository pattern** for all DB access (no raw SQL in services)
- **State machine** for agent lifecycle (created → approved → executing → idle → disabled)
- **Circuit breaker** (three-state) for broker calls
- **3-layer risk chain**: agent → execution → global
- **Event bus**: Redis Streams with pub-sub consumers
- **Centralized config**: env vars via `shared/config/base_config.py` (dataclass) and `apps/api/src/config.py` (pydantic-settings)

### ML Pipeline
Training runs 8 models sequentially (memory-constrained): XGBoost, LightGBM, CatBoost, LSTM, Transformer, TFT, TCN → then Hybrid ensemble + Meta-learner. Features span ~200 attributes across price action, technicals, volume, market context, time, sentiment, and options data.

## Code Style & Tooling

- **Python**: Ruff (E, F, I, N, W rules), line-length 120, target py311. MyPy strict (`disallow_untyped_defs`).
- **Testing**: pytest with `asyncio_mode = "auto"`. Tests in `tests/` and `apps/api/tests/`. Fixtures in `conftest.py` use SQLite in-memory for DB.
- **Frontend**: React 18, Vite, TypeScript, Tailwind CSS, Radix UI primitives.
- **PYTHONPATH**: Must be set to repo root (`.`) when running services or tests outside Make.
- **Pre-commit hooks**: Ruff auto-fix, trailing whitespace, YAML/JSON check, large file detection, private key detection.

## Environment Variables

All services read from `.env` (git-ignored). Key vars: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ANTHROPIC_API_KEY`, `BRIDGE_TOKEN`, `KAFKA_BOOTSTRAP_SERVERS`, `OLLAMA_BASE_URL`. Run `make env-file` to generate from `.env.example`.

The Makefile provides sensible local defaults (`LOCAL_DB_URL`, `LOCAL_REDIS`, etc.) so services can run without a `.env` when launched via `make run-*`.
