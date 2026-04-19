.PHONY: help install dev-install lint test test-cov infra-up infra-down infra-logs \
       test-integration test-e2e test-e2e-remote regression-yaml-parallel test-api-all go-live-regression go-live-regression-quality db-alembic-heads \
       db-init db-migrate dev \
       docker-build docker-up docker-down docker-logs clean benchmark \
       up down status logs setup local-up local-down \
       prod-build prod-up prod-down prod-logs prod-status \
       run-api run-dashboard \
       run-orchestrator run-execution run-ws-gateway run-automation \
       run-connector-manager run-backtest-runner run-skill-sync \
       run-agent-comm run-comms run-code-executor run-global-monitor \
       run-llm-gateway run-position-monitor \
       run-core run-all check-infra seed-db dev-run

PYTHON := python3
PIP := pip3
PG_BIN := $(shell brew --prefix postgresql@16 2>/dev/null)/bin

# Use the local .venv if it exists
VENV := $(wildcard .venv/bin/activate)
ifdef VENV
  RUN := . .venv/bin/activate &&
else
  RUN :=
endif

# Local dev env vars (used when running services outside Docker)
# Brew Postgres runs as the current OS user with no password by default.
# Docker Postgres uses phoenixtrader:localdev.  Detect which is available.
HAS_DOCKER := $(shell command -v docker 2>/dev/null)
LOCAL_DB_URL ?= postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader
LOCAL_REDIS    ?= redis://localhost:6379
LOCAL_MINIO    ?= http://localhost:9002
LOCAL_JWT      ?= dev-jwt-secret-change-me

# Common env block for local service targets
define LOCAL_ENV
PYTHONPATH=. \
DATABASE_URL=$(LOCAL_DB_URL) \
REDIS_URL=$(LOCAL_REDIS) \
JWT_SECRET_KEY=$(LOCAL_JWT) \
MINIO_ENDPOINT=$(LOCAL_MINIO) \
MINIO_ACCESS_KEY=minioadmin \
MINIO_SECRET_KEY=minioadmin \
API_URL=http://localhost:8011 \
OLLAMA_BASE_URL=http://localhost:11434 \
OLLAMA_EXPAND_MODEL=llama3.2:1b \
API_DEBUG=true
endef

# ─────────────────────────────────────────────
# Help
# ─────────────────────────────────────────────
help: ## Show this help
	@echo ""
	@echo "  \033[1m── Quick Start ──────────────────────────\033[0m"
	@echo "  \033[36mmake setup\033[0m          First-time setup (install deps + create .env)"
	@echo "  \033[36mmake dev-run\033[0m        \033[1mOne command: infra + API + Dashboard\033[0m"
	@echo "  \033[36mmake up\033[0m             Build & start ENTIRE platform (Docker)"
	@echo "  \033[36mmake down\033[0m           Stop everything"
	@echo "  \033[36mmake logs\033[0m           Tail all logs"
	@echo "  \033[36mmake status\033[0m         Show running containers"
	@echo "  \033[36mmake local-up\033[0m       Start infra + init DB (run services yourself)"
	@echo ""
	@echo "  \033[1m── Local Dev (run services natively) ────\033[0m"
	@echo "  \033[36mmake run-core\033[0m       Run API + Dashboard (needs infra running)"
	@echo "  \033[36mmake run-api\033[0m        Run Phoenix API on :8011"
	@echo "  \033[36mmake run-dashboard\033[0m  Run Dashboard dev server on :3000"
	@echo ""
	@echo "  \033[1m── All Commands ─────────────────────────\033[0m"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ─────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────
install: ## Install production dependencies
	$(PIP) install -e .

dev-install: ## Install all dependencies (prod + dev + ml)
	$(PIP) install -e ".[dev,ml]"

env-file: ## Create .env from .env.example
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		KEY=$$($(PYTHON) -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"); \
		sed -i '' "s|^CREDENTIAL_ENCRYPTION_KEY=.*|CREDENTIAL_ENCRYPTION_KEY=$$KEY|" .env; \
		echo ".env created -- edit it with your keys"; \
	else \
		echo ".env already exists"; \
	fi

dashboard-install: ## Install dashboard (npm) dependencies
	cd apps/dashboard && npm install

# ─────────────────────────────────────────────
# Code Quality
# ─────────────────────────────────────────────
lint: ## Run ruff linter (shared, services, apps, tests)
	$(PYTHON) -m ruff check shared/ services/ apps/ tests/

lint-fix: ## Auto-fix lint issues
	$(PYTHON) -m ruff check --fix shared/ services/ tests/

typecheck: ## Run mypy type checker
	$(PYTHON) -m mypy shared/ --ignore-missing-imports

# ─────────────────────────────────────────────
# Testing
# ─────────────────────────────────────────────
test: ## Run unit tests: tests/unit + apps/api/tests/unit (split avoids conftest clash; no API integration)
	PYTHONPATH=. $(PYTHON) -m pytest tests/unit/ -v --tb=short
	PYTHONPATH=. $(PYTHON) -m pytest apps/api/tests/unit/ -v --tb=short

test-api: ## Run Phoenix v2 API unit tests (apps/api/tests/unit only)
	PYTHONPATH=. $(PYTHON) -m pytest apps/api/tests/unit/ -v --tb=short

test-api-all: ## All API tests including integration (may fail on route/DB drift)
	PYTHONPATH=. $(PYTHON) -m pytest apps/api/tests/ -v --tb=short

test-dashboard: ## Run Phoenix v2 dashboard unit tests
	cd apps/dashboard && npm run test

test-integration: ## Run pytest integration tests (live pipeline mocks, etc.)
	PYTHONPATH=. $(PYTHON) -m pytest tests/integration/ -v --tb=short

test-e2e: ## Playwright E2E — requires dashboard :3000 + API :8011 running
	PYTHONPATH=. $(PYTHON) -m pytest tests/e2e/ -v --tb=short

test-e2e-remote: ## Playwright E2E against deployed URL — set PHOENIX_E2E_BASE_URL (and optional PHOENIX_E2E_EMAIL/PASSWORD)
	@if [ -z "$$PHOENIX_E2E_BASE_URL" ]; then echo "Set PHOENIX_E2E_BASE_URL to the live dashboard origin."; exit 1; fi
	PYTHONPATH=. $(PYTHON) -m pytest tests/e2e/ -v --tb=short

regression-yaml-parallel: ## Run tests/regression/user_journeys.yaml via 10 parallel browsers — set PHOENIX_E2E_BASE_URL, PHOENIX_API_BASE_URL
	@if [ -z "$$PHOENIX_E2E_BASE_URL" ]; then echo "Set PHOENIX_E2E_BASE_URL"; exit 1; fi
	$(PYTHON) scripts/regression/run_yaml_parallel.py

go-live-regression: ## Automated go-live: test (unit + api unit), integration, dashboard
	$(MAKE) test
	$(MAKE) test-integration
	$(MAKE) test-dashboard

go-live-regression-quality: ## Optional quality gate: ruff + mypy (may fail until repo-wide cleanup)
	$(MAKE) lint
	$(MAKE) typecheck

db-alembic-heads: ## Print Alembic head revision(s); expect 038_decision_trail for audit trail column
	$(RUN) PYTHONPATH=. alembic -c $(ALEMBIC_INI) heads

test-cov: ## Run tests with coverage report
	PYTHONPATH=. $(PYTHON) -m pytest tests/unit/ apps/api/tests/ --cov=shared --cov=apps --cov-report=term-missing --cov-report=html

benchmark: ## Run latency benchmark
	$(PYTHON) -m tests.benchmark.run_benchmark --count 1000

# ─────────────────────────────────────────────
# Local Infrastructure (Docker Compose)
# ─────────────────────────────────────────────
infra-up: ## Start Kafka, Postgres, Redis (dev mode)
ifdef HAS_DOCKER
	docker compose -f docker-compose.dev.yml up -d
	@echo "Waiting for services to be healthy..."
	@sleep 5
	@echo "Infrastructure ready"
else
	@echo "Docker not found — using Homebrew services"
	brew services start postgresql@16
	brew services start redis
	@for i in 1 2 3 4 5; do $(PG_BIN)/pg_isready -q 2>/dev/null && break; sleep 2; done
	@$(PG_BIN)/createdb phoenixtrader 2>/dev/null || true
	@echo "Infrastructure ready (Postgres :5432, Redis :6379)"
endif

infra-down: ## Stop local infrastructure
ifdef HAS_DOCKER
	docker compose -f docker-compose.dev.yml down
else
	brew services stop postgresql@16 2>/dev/null || true
	brew services stop redis 2>/dev/null || true
	@echo "Homebrew services stopped"
endif

infra-logs: ## Tail infrastructure logs
	docker compose -f docker-compose.dev.yml logs -f

# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────
db-init: ## Create all database tables (no Alembic, for bootstrapping)
	$(RUN) PYTHONPATH=. DATABASE_URL=$(LOCAL_DB_URL) $(PYTHON) scripts/init_db.py

ALEMBIC_INI := shared/db/migrations/alembic.ini

db-migrate: ## Generate Alembic migration (usage: make db-migrate msg="add xyz")
	$(RUN) PYTHONPATH=. DATABASE_URL=$(LOCAL_DB_URL) alembic -c $(ALEMBIC_INI) revision --autogenerate -m "$(msg)"

db-upgrade: ## Apply all pending Alembic migrations
	$(RUN) PYTHONPATH=. DATABASE_URL=$(LOCAL_DB_URL) alembic -c $(ALEMBIC_INI) upgrade head

db-downgrade: ## Revert last Alembic migration
	$(RUN) PYTHONPATH=. DATABASE_URL=$(LOCAL_DB_URL) alembic -c $(ALEMBIC_INI) downgrade -1

db-history: ## Show Alembic migration history
	$(RUN) PYTHONPATH=. DATABASE_URL=$(LOCAL_DB_URL) alembic -c $(ALEMBIC_INI) history --verbose

db-current: ## Show current Alembic revision
	$(RUN) PYTHONPATH=. DATABASE_URL=$(LOCAL_DB_URL) alembic -c $(ALEMBIC_INI) current

# ─────────────────────────────────────────────
# Run v2 Stack via Docker Compose
# ─────────────────────────────────────────────
dev: ## Start the v2 stack via Docker Compose
	docker compose -f infra/docker-compose.production.yml up -d
	@echo ""
	@echo "  v2 stack starting..."
	@echo "      Dashboard:   http://localhost:3000"
	@echo "      API:         http://localhost:8011"
	@echo ""

dev-run: ## One command: start infra + DB + API + Dashboard (Ctrl+C stops all)
	@echo ""
	@echo "  \033[1mStarting infrastructure...\033[0m"
ifdef HAS_DOCKER
	@docker compose -f docker-compose.dev.yml up -d
	@echo "  Waiting for Postgres & Redis to be healthy..."
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		docker compose -f docker-compose.dev.yml ps --format '{{.Status}}' 2>/dev/null | grep -q "healthy" && break; \
		sleep 2; \
	done
else
	@echo "  Docker not found — using Homebrew services (postgresql@16, redis)"
	@brew services start postgresql@16 2>/dev/null || true
	@brew services start redis 2>/dev/null || true
	@echo "  Waiting for Postgres & Redis..."
	@for i in 1 2 3 4 5; do \
		$(PG_BIN)/pg_isready -q 2>/dev/null && break; \
		sleep 2; \
	done
	@$(PG_BIN)/psql postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='phoenixtrader'" | grep -q 1 \
		|| $(PG_BIN)/psql postgres -c "CREATE ROLE phoenixtrader WITH LOGIN PASSWORD 'localdev' CREATEDB;" 2>/dev/null
	@$(PG_BIN)/createdb -O phoenixtrader phoenixtrader 2>/dev/null || true
endif
	@echo "  Initializing database..."
	@$(RUN) PYTHONPATH=. DATABASE_URL=$(LOCAL_DB_URL) $(PYTHON) scripts/init_db.py 2>/dev/null || true
	@echo ""
	@echo "  \033[1m\033[32mReady! Starting services...\033[0m"
	@echo "      API:        http://localhost:8011"
	@echo "      Dashboard:  http://localhost:3000"
	@echo ""
	@echo "  Press Ctrl+C to stop everything."
	@echo ""
	@trap 'echo ""; echo "  Shutting down..."; kill 0; wait; echo "  Done."; exit 0' INT TERM; \
		$(RUN) $(LOCAL_ENV) $(PYTHON) -m uvicorn apps.api.src.main:app --host 0.0.0.0 --port 8011 --reload & \
		(cd apps/dashboard && npm run dev) & \
		wait

# ─────────────────────────────────────────────
# Run Services Locally (no Docker, hot-reload)
# ─────────────────────────────────────────────
# Core apps
run-api: ## Run Phoenix API on :8011 (hot-reload)
	$(LOCAL_ENV) $(PYTHON) -m uvicorn apps.api.src.main:app --host 0.0.0.0 --port 8011 --reload

run-api-v2: run-api ## Alias for run-api

run-dashboard: ## Run Dashboard dev server on :3000
	cd apps/dashboard && npm run dev

run-dashboard-v2: run-dashboard ## Alias for run-dashboard

# Microservices
run-orchestrator: ## Run Orchestrator on :8040
	$(LOCAL_ENV) $(PYTHON) -m uvicorn services.orchestrator.src.main:app --host 0.0.0.0 --port 8040 --reload

run-execution: ## Run Execution Service on :8020
	$(LOCAL_ENV) $(PYTHON) -m uvicorn services.execution.src.main:app --host 0.0.0.0 --port 8020 --reload

run-ws-gateway: ## Run WebSocket Gateway on :8031
	$(LOCAL_ENV) $(PYTHON) -c "import asyncio; from services.ws_gateway.src.gateway import create_gateway; asyncio.run(create_gateway(host='0.0.0.0', port=8031))"

run-automation: ## Run Automation Scheduler
	$(LOCAL_ENV) $(PYTHON) -m services.automation.src.main

run-connector-manager: ## Run Connector Manager on :8060
	$(LOCAL_ENV) $(PYTHON) -m uvicorn services.connector_manager.src.main:app --host 0.0.0.0 --port 8060 --reload

run-backtest-runner: ## Run Backtest Runner on :8022
	$(LOCAL_ENV) $(PYTHON) -m uvicorn services.backtest_runner.src.main:app --host 0.0.0.0 --port 8022 --reload

run-skill-sync: ## Run Skill Sync on :8023
	$(LOCAL_ENV) $(PYTHON) -m uvicorn services.skill_sync.src.main:app --host 0.0.0.0 --port 8023 --reload

run-agent-comm: ## Run Agent Comm on :8024
	$(LOCAL_ENV) $(PYTHON) -m uvicorn services.agent_comm.src.main:app --host 0.0.0.0 --port 8024 --reload

run-comms: ## Run Comms Service on :8025
	$(LOCAL_ENV) $(PYTHON) -m uvicorn services.comms.src.main:app --host 0.0.0.0 --port 8025 --reload

run-code-executor: ## Run Code Executor on :8026
	$(LOCAL_ENV) $(PYTHON) -m uvicorn services.code_executor.src.main:app --host 0.0.0.0 --port 8026 --reload

run-global-monitor: ## Run Global Monitor on :8050
	$(LOCAL_ENV) $(PYTHON) -m uvicorn services.global_monitor.src.main:app --host 0.0.0.0 --port 8050 --reload

run-llm-gateway: ## Run LLM Gateway on :8051
	$(LOCAL_ENV) $(PYTHON) -m uvicorn services.llm_gateway.main:app --host 0.0.0.0 --port 8051 --reload

run-position-monitor: ## Run Position Monitor on :8009
	$(LOCAL_ENV) $(PYTHON) -m uvicorn services.position_monitor.main:app --host 0.0.0.0 --port 8009 --reload

# Convenience combos
run-core: ## Run API + Dashboard in parallel (needs infra running)
	@echo "  Starting API + Dashboard..."
	@echo "  Press Ctrl+C to stop both."
	@trap 'kill 0' INT; \
		$(MAKE) run-api & \
		$(MAKE) run-dashboard & \
		wait

# ─────────────────────────────────────────────
# Quick Start (one-command workflows)
# ─────────────────────────────────────────────
setup: dev-install env-file dashboard-install ## First-time: install everything + create .env
	@echo ""
	@echo "  ✅  Setup complete. Edit .env with your API keys, then run:"
	@echo "      make up          (full Docker stack)"
	@echo "      make local-up    (infra only, run services manually)"

up: ## Build & run ENTIRE platform in Docker
	docker compose up -d --build
	@echo ""
	@echo "  Platform starting..."
	@echo "      Dashboard:   http://localhost:3000"
	@echo "      API:         http://localhost:8011"
	@echo ""
	@echo "  Run 'make logs' to watch output"
	@echo "  Run 'make status' to check health"

down: ## Stop everything (infra + services)
	docker compose down 2>/dev/null || true
	docker compose -f docker-compose.dev.yml down 2>/dev/null || true
	@echo "  All stopped."

logs: ## Tail all logs (Docker)
	docker compose logs -f

status: ## Show running containers & health
	@docker compose ps 2>/dev/null; docker compose -f docker-compose.dev.yml ps 2>/dev/null || true

local-up: infra-up db-init ## Start infra (Kafka/PG/Redis) + init DB for local dev
	@echo ""
	@echo "  Infrastructure running & DB initialized."
	@echo ""
	@echo "  \033[1mStart services in separate terminals:\033[0m"
	@echo "      make run-api              API            http://localhost:8011"
	@echo "      make run-dashboard        Dashboard      http://localhost:3000"
	@echo "      make run-orchestrator     Orchestrator   http://localhost:8040"
	@echo "      make run-execution        Execution      http://localhost:8020"
	@echo "      make run-ws-gateway       WS Gateway     ws://localhost:8031"
	@echo ""
	@echo "  \033[1mOr run API + Dashboard together:\033[0m"
	@echo "      make run-core"
	@echo ""

local-down: infra-down ## Stop local infra (Kafka/PG/Redis)

check-infra: ## Check if local infra containers are healthy
	@echo "  Checking infrastructure..."
	@docker compose -f docker-compose.dev.yml ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "  Infra not running. Run: make infra-up"

seed-db: ## Seed the database with a test user
	$(LOCAL_ENV) $(PYTHON) scripts/seed_user.py

# ─────────────────────────────────────────────
# Full Docker Stack (granular)
# ─────────────────────────────────────────────
docker-build: ## Build all Docker images
	docker compose build

docker-up: ## Start entire platform in Docker
	docker compose up -d

docker-down: ## Stop entire platform
	docker compose down

docker-logs: ## Tail all service logs
	docker compose logs -f

# ─────────────────────────────────────────────
# Production (infra/docker-compose.production.yml)
# ─────────────────────────────────────────────
prod-build: ## Build production images
	docker compose -f infra/docker-compose.production.yml build

prod-up: ## Start production stack locally (test before deploying)
	docker compose -f infra/docker-compose.production.yml up -d --build
	@echo ""
	@echo "  Production stack starting on http://localhost"
	@echo "  Run 'make prod-logs' to watch output"

prod-down: ## Stop production stack
	docker compose -f infra/docker-compose.production.yml down

prod-logs: ## Tail production logs
	docker compose -f infra/docker-compose.production.yml logs -f

prod-status: ## Show production container health
	docker compose -f infra/docker-compose.production.yml ps

# ─────────────────────────────────────────────
# Housekeeping
# ─────────────────────────────────────────────
clean: ## Remove build artifacts and caches
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov
	rm -rf *.egg-info build dist
	rm -f test.db coverage.xml .coverage
