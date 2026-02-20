.PHONY: help install dev-install lint test test-cov infra-up infra-down infra-logs \
       db-init db-migrate run-gateway run-auth run-dashboard \
       docker-build docker-up docker-down docker-logs clean benchmark \
       up down status logs setup local-up local-down \
       prod-build prod-up prod-down prod-logs prod-status

PYTHON := python3
PIP := pip3

# ─────────────────────────────────────────────
# Help
# ─────────────────────────────────────────────
help: ## Show this help
	@echo ""
	@echo "  \033[1m── Quick Start ──────────────────────────\033[0m"
	@echo "  \033[36mmake setup\033[0m          First-time setup (install deps + create .env)"
	@echo "  \033[36mmake up\033[0m             Build & start ENTIRE platform (Docker)"
	@echo "  \033[36mmake down\033[0m           Stop everything"
	@echo "  \033[36mmake logs\033[0m           Tail all logs"
	@echo "  \033[36mmake status\033[0m         Show running containers"
	@echo "  \033[36mmake local-up\033[0m       Start infra + init DB (run services yourself)"
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

dev-install: ## Install all dependencies (prod + dev)
	$(PIP) install -e ".[dev]"

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
	cd services/dashboard-ui && npm install

# ─────────────────────────────────────────────
# Code Quality
# ─────────────────────────────────────────────
lint: ## Run ruff linter
	$(PYTHON) -m ruff check shared/ services/ tests/

lint-fix: ## Auto-fix lint issues
	$(PYTHON) -m ruff check --fix shared/ services/ tests/

typecheck: ## Run mypy type checker
	$(PYTHON) -m mypy shared/ --ignore-missing-imports

# ─────────────────────────────────────────────
# Testing
# ─────────────────────────────────────────────
test: ## Run all unit tests
	$(PYTHON) -m pytest tests/unit/ -v --tb=short

test-cov: ## Run tests with coverage report
	$(PYTHON) -m pytest tests/unit/ --cov=shared --cov-report=term-missing --cov-report=html

benchmark: ## Run latency benchmark
	$(PYTHON) -m tests.benchmark.run_benchmark --count 1000

# ─────────────────────────────────────────────
# Local Infrastructure (Docker Compose)
# ─────────────────────────────────────────────
infra-up: ## Start Kafka, Postgres, Redis (dev mode)
	docker compose -f docker-compose.dev.yml up -d
	@echo "Waiting for services to be healthy..."
	@sleep 5
	@echo "Infrastructure ready"

infra-down: ## Stop local infrastructure
	docker compose -f docker-compose.dev.yml down

infra-logs: ## Tail infrastructure logs
	docker compose -f docker-compose.dev.yml logs -f

# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────
db-init: ## Create all database tables
	$(PYTHON) -c "import asyncio; from shared.models.database import init_db; asyncio.run(init_db())"

db-migrate: ## Generate a new Alembic migration (usage: make db-migrate msg="add xyz")
	alembic revision --autogenerate -m "$(msg)"

db-upgrade: ## Apply pending migrations
	alembic upgrade head

# ─────────────────────────────────────────────
# Run Individual Services (local, no Docker)
# ─────────────────────────────────────────────
run-gateway: ## Run API Gateway on :8011
	$(PYTHON) services/api-gateway/main.py

run-auth: ## Run Auth Service on :8001
	$(PYTHON) services/auth-service/main.py

run-parser: ## Run Trade Parser on :8006
	$(PYTHON) services/trade-parser/main.py

run-executor: ## Run Trade Executor on :8008
	$(PYTHON) services/trade-executor/main.py

run-monitor: ## Run Position Monitor on :8009
	$(PYTHON) services/position-monitor/main.py

run-dashboard: ## Run React dashboard dev server on :3000
	cd services/dashboard-ui && npm run dev

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
	@echo "  ✅  Platform starting..."
	@echo "      Dashboard:   http://localhost:3000"
	@echo "      API Gateway: http://localhost:8011"
	@echo "      Auth API:    http://localhost:8001"
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
	@echo "  ✅  Infra running & DB initialized. Now start services in separate terminals:"
	@echo "      make run-auth       (port 8001)"
	@echo "      make run-gateway    (port 8011)"
	@echo "      make run-parser"
	@echo "      make run-executor"
	@echo "      make run-monitor"
	@echo "      make run-dashboard  (port 3000)"

local-down: infra-down ## Stop local infra (Kafka/PG/Redis)

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
# Production / Coolify (docker-compose.coolify.yml)
# ─────────────────────────────────────────────
prod-build: ## Build production images (Coolify compose)
	docker compose -f docker-compose.coolify.yml build

prod-up: ## Start production stack locally (test before deploying)
	docker compose -f docker-compose.coolify.yml up -d --build
	@echo ""
	@echo "  Production stack starting on http://localhost"
	@echo "  Run 'make prod-logs' to watch output"

prod-down: ## Stop production stack
	docker compose -f docker-compose.coolify.yml down

prod-logs: ## Tail production logs
	docker compose -f docker-compose.coolify.yml logs -f

prod-status: ## Show production container health
	docker compose -f docker-compose.coolify.yml ps

# ─────────────────────────────────────────────
# Housekeeping
# ─────────────────────────────────────────────
clean: ## Remove build artifacts and caches
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov
	rm -rf *.egg-info build dist
	rm -f test.db coverage.xml .coverage
