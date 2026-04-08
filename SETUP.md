# How to Run and Test -- Step-by-Step Guide

This guide walks you through setting up, running, and testing the Phoenix Trade Bot from a fresh clone. Follow every step in order.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone and Install](#2-clone-and-install)
3. [Environment Configuration](#3-environment-configuration)
4. [Start Infrastructure](#4-start-infrastructure)
5. [Initialize the Database](#5-initialize-the-database)
6. [Run Tests](#6-run-tests)
7. [Run Services Locally](#7-run-services-locally)
8. [Run the Dashboard](#8-run-the-dashboard)
9. [Test the API Manually](#9-test-the-api-manually)
10. [Run with Docker (Full Stack)](#10-run-with-docker-full-stack)
11. [Load Testing](#11-load-testing)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

Install these tools before starting:

| Tool | Minimum Version | Check Command | Install |
|------|-----------------|---------------|---------|
| Python | 3.11+ | `python3 --version` | [python.org/downloads](https://www.python.org/downloads/) |
| pip | 23+ | `pip3 --version` | Comes with Python |
| Docker Desktop | 24+ | `docker --version` | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) |
| Docker Compose | 2.20+ | `docker compose version` | Included with Docker Desktop |
| Node.js | 18+ | `node --version` | [nodejs.org](https://nodejs.org/) (for dashboard only) |
| npm | 9+ | `npm --version` | Comes with Node.js |
| Git | 2.x | `git --version` | [git-scm.com](https://git-scm.com/) |

**Verify all are installed:**

```bash
python3 --version        # Python 3.11+
docker --version         # Docker 24+
docker compose version   # Docker Compose 2.20+
node --version           # v18+
npm --version            # 9+
```

---

## 2. Clone and Install

```bash
# Clone the repository
git clone <your-repo-url>
cd discordmessages2trade

# Install Python dependencies (editable mode)
make dev-install
```

This installs all production and development Python packages including pytest, ruff, mypy, and the `shared` library.

**Verify installation:**

```bash
python3 -c "import shared; print('shared library OK')"
python3 -m pytest --version
```

---

## 3. Environment Configuration

### Step 3a: Create .env file

```bash
make env-file
```

This copies `.env.example` to `.env` and auto-generates a Fernet encryption key.

### Step 3b: Generate a JWT secret

```bash
# Generate a secure JWT secret key
openssl rand -hex 32
```

Copy the output.

### Step 3c: Edit .env

Open `.env` in your editor and update these values:

```bash
# REQUIRED -- paste the JWT secret you generated above
JWT_SECRET_KEY=<paste-your-openssl-output-here>

# OPTIONAL -- only needed for live Discord ingestion
DISCORD_BOT_TOKEN=<your-discord-bot-token>
DISCORD_TARGET_CHANNELS=<comma-separated-channel-IDs>

# OPTIONAL -- only needed for live Alpaca trading
ALPACA_API_KEY=<your-alpaca-api-key>
ALPACA_SECRET_KEY=<your-alpaca-secret-key>
ALPACA_PAPER=true
```

The remaining defaults in `.env` work for local development as-is.

### Step 3d: Verify .env is not tracked by git

```bash
git status .env
# Should show nothing (it's in .gitignore)
```

---

## 4. Start Infrastructure

The platform needs three infrastructure services: **Kafka**, **PostgreSQL**, and **Redis**.

```bash
# Start all infrastructure containers
make infra-up
```

**Wait ~10 seconds**, then verify they are running:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Expected output:

```
NAMES      STATUS                   PORTS
kafka      Up 10s (healthy)         0.0.0.0:9092->9092/tcp
postgres   Up 10s (healthy)         0.0.0.0:5432->5432/tcp
redis      Up 10s (healthy)         0.0.0.0:6379->6379/tcp
```

**Verify connectivity:**

```bash
# Test PostgreSQL
docker exec postgres pg_isready -U phoenixtrader
# /var/run/postgresql:5432 - accepting connections

# Test Redis
docker exec redis redis-cli ping
# PONG

# Test Kafka
docker exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
# (empty list or topic names)
```

To **stop** infrastructure later:

```bash
make infra-down
```

---

## 5. Initialize the Database

With PostgreSQL running, create all database tables:

```bash
make db-init
```

**Verify tables were created:**

```bash
docker exec postgres psql -U phoenixtrader -c "\dt"
```

You should see tables like: `users`, `trading_accounts`, `data_sources`, `channels`, `account_source_mappings`, `trades`, `positions`, `trade_events`, `daily_metrics`, `configurations`, `notification_log`, etc.

---

## 6. Run Tests

### 6a: Run all unit tests (no infrastructure needed)

Unit tests use SQLite in-memory and mocked Kafka/Redis -- they do NOT require Docker.

```bash
make test
```

Expected output:

```
169 passed in ~3s
```

### 6b: Run tests with coverage report

```bash
make test-cov
```

This generates a terminal summary and an HTML report at `htmlcov/index.html`.

### 6c: Run a specific test file

```bash
# Trade parser tests
python3 -m pytest tests/unit/test_trade_parser.py -v

# Auth tests
python3 -m pytest tests/unit/test_auth.py -v

# Buffer pricing tests
python3 -m pytest tests/unit/test_buffer_pricing.py -v
```

### 6d: Run a specific test by name

```bash
python3 -m pytest tests/unit/test_trade_parser.py::TestParseTradeMessage::test_buy_with_expiration -v
```

### 6e: Run the latency benchmark

```bash
make benchmark
```

This runs the trade parser and buffer pricing functions 1000 times each and reports p50/p95/p99 latencies.

### Test file reference

| Test File | What It Tests | Count |
|-----------|---------------|-------|
| `test_config.py` | Config loading, defaults | 7 |
| `test_models.py` | ORM model structure, FK relationships | 17 |
| `test_crypto.py` | Fernet encrypt/decrypt round-trip | 5 |
| `test_kafka_producer.py` | Kafka producer (mocked) | 7 |
| `test_kafka_consumer.py` | Kafka consumer (mocked) | 4 |
| `test_error_codes.py` | Error code enum | 2 |
| `test_trade_parser.py` | Trade message regex parsing | 12 |
| `test_buffer_pricing.py` | Buffer price calculation | 9 |
| `test_validator.py` | Trade validation rules | 10 |
| `test_gateway.py` | Auto/manual approval | 3 |
| `test_auth.py` | Password hashing, JWT tokens | 8 |
| `test_jwt_middleware.py` | JWT middleware (FastAPI) | 5 |
| `test_tenant.py` | Scoped query tenant isolation | 4 |
| `test_msgpack_serialization.py` | Msgpack round-trip | 5 |
| `test_async_broker.py` | Alpaca adapter (mocked HTTP) | 5 |
| `test_circuit_breaker.py` | Circuit breaker state machine | 7 |
| `test_dlq.py` | Dead letter queue | 2 |
| `test_retry.py` | Retry with exponential backoff | 4 |
| `test_dedup.py` | Redis deduplication (mocked) | 3 |
| `test_graceful_shutdown.py` | SIGTERM handling | 3 |
| `test_broker_factory.py` | Broker adapter factory | 2 |
| `test_source_orchestrator.py` | Source orchestrator | 2 |
| `test_profit_target.py` | Profit target exit engine | 4 |
| `test_stop_loss.py` | Stop loss exit engine | 3 |
| `test_trailing_stop.py` | Trailing stop + HWM | 6 |
| `test_daily_aggregator.py` | Daily metrics aggregator | 1 |
| `test_manual_approval.py` | Manual approval flow | 7 |
| `test_discord_commands.py` | Discord bot commands | 2 |
| `test_rate_limiter.py` | Sliding window rate limiter | 3 |
| `test_feature_flags.py` | Feature flags + overrides | 5 |
| `test_agent_protocol.py` | Agent plugin protocol | 3 |
| `test_agent_registry.py` | Agent registry CRUD | 4 |
| `test_signal_scorer.py` | Signal scoring agent | 5 |
| **Total** | | **169** |

---

## 7. Run Services Locally

With infrastructure running (Step 4), start services individually in separate terminals.

### Minimum viable setup (API + Auth):

```bash
# Terminal 1 -- API Gateway (serves all REST endpoints + auth)
make run-gateway
# Starts on http://localhost:8011
```

### Full pipeline (signal ingestion through execution):

```bash
# Terminal 1 -- API Gateway
make run-gateway           # :8011

# Terminal 2 -- Trade Parser (Kafka consumer)
make run-parser            # :8006

# Terminal 3 -- Trade Executor (Kafka consumer)
make run-executor          # :8008

# Terminal 4 -- Position Monitor
make run-monitor           # :8009
```

### Verify services are running:

```bash
curl http://localhost:8011/health    # API Gateway
curl http://localhost:8006/health    # Trade Parser
curl http://localhost:8008/health    # Trade Executor
curl http://localhost:8009/health    # Position Monitor
```

Each returns: `{"status":"ready","service":"<service-name>"}`

---

## 8. Run the Dashboard

### First time setup:

```bash
make dashboard-install
```

### Start the dev server:

```bash
make run-dashboard
```

Open **http://localhost:3000** in your browser.

The dashboard proxies API requests to `http://localhost:8011`, so the API Gateway must be running.

### What you can do in the dashboard:

1. **Register** -- Create a new account
2. **Login** -- Sign in with your credentials
3. **Dashboard tab** -- View trade stats, daily P&L chart, recent trades table
4. **Data Sources tab** -- Add Discord/Twitter/Reddit data sources
5. **Trading Accounts tab** -- Connect Alpaca or other broker accounts
6. **Analytics tab** -- Cumulative P&L, win rate trend charts
7. **System tab** -- Service health monitor, notifications

---

## 9. Test the API Manually

With the API Gateway running (`make run-gateway`):

### Register a user:

```bash
curl -s -X POST http://localhost:8011/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"SecurePass123!","name":"Test User"}' | python3 -m json.tool
```

Save the `access_token` from the response.

### Login:

```bash
curl -s -X POST http://localhost:8011/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"SecurePass123!"}' | python3 -m json.tool
```

### Use the token for authenticated requests:

```bash
# Set your token (paste from login response)
TOKEN="<your-access-token>"

# List trading accounts
curl -s http://localhost:8011/api/v1/accounts \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# List trades
curl -s http://localhost:8011/api/v1/trades?limit=10 \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Get daily metrics
curl -s "http://localhost:8011/api/v1/metrics/daily?days=7" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Check system health (no auth needed)
curl -s http://localhost:8011/api/v1/system/health | python3 -m json.tool

# Check unread notification count
curl -s http://localhost:8011/api/v1/notifications/unread-count \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### Create a trading account:

```bash
curl -s -X POST http://localhost:8011/api/v1/accounts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "broker_type": "alpaca",
    "display_name": "My Paper Account",
    "credentials": {"api_key": "your-key", "secret_key": "your-secret"},
    "paper_mode": true
  }' | python3 -m json.tool
```

### Create a data source:

```bash
curl -s -X POST http://localhost:8011/api/v1/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "discord",
    "display_name": "My Discord Server",
    "credentials": {"bot_token": "your-bot-token"}
  }' | python3 -m json.tool
```

---

## 10. Run with Docker (Full Stack)

To run everything in containers with one command:

```bash
# Build all images (first time or after code changes)
make docker-build

# Start the entire platform
make docker-up

# Watch logs
make docker-logs
```

This starts 15 containers:
- `kafka`, `postgres`, `redis` -- infrastructure
- `init` -- creates DB tables (runs once and exits)
- `auth-service`, `api-gateway`, `trade-parser`, `trade-gateway`, `trade-executor`, `position-monitor`, `notification-service`, `source-orchestrator`, `audit-writer` -- microservices
- `dashboard-ui` -- React frontend (nginx)

**Access points:**
- Dashboard: http://localhost:3000
- API: http://localhost:8011
- API docs: http://localhost:8011/docs

**Stop everything:**

```bash
make docker-down
```

---

## 11. Prediction Markets Agent

The **TopBetsAgent** is a 24/7 autonomous scanner that surfaces high-confidence prediction-market bets from Robinhood Predictions (primary venue). All trades in Phase 15 are **paper mode only** — no real money is ever committed.

### Start the agent (standalone)

```bash
# From repo root (infrastructure must already be running)
PYTHONPATH=. python -m agents.polymarket.top_bets.runner
```

### Start via Docker (agents profile)

The agent is included in the `agents` Docker Compose profile so it does **not** start with the default `docker compose up`. To include it:

```bash
docker compose --profile agents up -d
```

Or run it alone:

```bash
docker compose --profile agents up pm-top-bets-agent
```

### Key environment variables

| Variable | Default | Description |
|---|---|---|
| `PM_TOP_BETS_ENABLED` | `true` | Enable/disable the agent entirely |
| `PM_TOP_BETS_VENUE` | `robinhood_predictions` | Venue registry key |
| `PM_TOP_BETS_CYCLE_INTERVAL_S` | `60` | Seconds between scan cycles |
| `PM_RESEARCH_ENABLED` | `true` | Enable nightly auto-research runner |

These are all optional — sensible defaults allow the agent to run without any additional configuration.

### Paper mode note

> **All trades in Phase 15 are paper-only.** The "Place Bet" action in the dashboard creates a paper order record and does **not** submit any order to Robinhood or any other broker. Live execution is planned for Phase 16.

---

## 12. Load Testing

### Install Locust:

```bash
pip3 install locust
```

### Run load tests:

```bash
# Start the API Gateway first
make run-gateway

# In another terminal, start Locust
locust -f tests/load/locustfile.py --host http://localhost:8011
```

Open http://localhost:8089 in your browser. Set:
- Number of users: 10
- Spawn rate: 2
- Click "Start swarming"

Locust automatically registers test users and runs requests against all API endpoints.

---

## 13. Troubleshooting

### "Connection refused" on port 5432/9092/6379

Infrastructure is not running. Start it:

```bash
make infra-up
docker ps   # verify containers are healthy
```

### "ModuleNotFoundError: No module named 'shared'"

Dependencies not installed. Run:

```bash
make dev-install
```

### "CREDENTIAL_ENCRYPTION_KEY not set"

Your `.env` file is missing or the key is blank. Run:

```bash
make env-file
# Then check .env has a real key on the CREDENTIAL_ENCRYPTION_KEY line
```

### "TypeError: pool_size sent to create_engine(), using SQLite"

You're running a service that imports `shared.models.database` but `DATABASE_URL` points to SQLite. This is fine for tests (they use in-memory SQLite). For running services, make sure PostgreSQL is running and `.env` has the PostgreSQL URL.

### Tests fail with "aiosqlite" error

Install the dev dependencies:

```bash
pip3 install aiosqlite
# or
make dev-install
```

### Dashboard shows "Network Error" on API calls

The API Gateway is not running. Start it:

```bash
make run-gateway
```

### Docker build fails on arm64 / Apple Silicon

The Kafka image may not have an arm64 build. Add `platform: linux/amd64` under the kafka service in `docker-compose.dev.yml`:

```yaml
kafka:
  image: apache/kafka-native:3.8
  platform: linux/amd64
```

### Port already in use

Kill the process using the port:

```bash
lsof -ti:8011 | xargs kill -9   # API Gateway
lsof -ti:3000 | xargs kill -9   # Dashboard
```

### Reset everything

```bash
make docker-down
make infra-down
make clean
docker volume rm discordmessages2trade_pgdata 2>/dev/null
make infra-up
make db-init
```

---

## Quick Reference Card

```
make dev-install          Install everything
make env-file             Create .env
make infra-up             Start Kafka + Postgres + Redis
make db-init              Create database tables
make test                 Run 169 unit tests
make run-gateway          Start API on :8011
make run-dashboard        Start UI on :3000
make docker-up            Run full stack in Docker
make docker-down          Stop everything
make clean                Remove caches/artifacts
make help                 Show all commands
```
