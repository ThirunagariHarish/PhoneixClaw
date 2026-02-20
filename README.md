# Phoenix Trade Bot

Enterprise-grade, multi-tenant phoenix trade bot. Parses trading signals from Discord (and other sources), routes them through a Kafka pipeline, and executes trades on broker APIs with configurable buffer pricing, risk management, and real-time position monitoring.

## Architecture Overview

```
Discord/Twitter/Reddit  -->  Source Orchestrator  -->  Kafka (raw-messages)
                                                            |
                                                     Trade Parser
                                                            |
                                                   Kafka (parsed-trades)
                                                            |
                                                     Trade Gateway (auto/manual approve)
                                                            |
                                                   Kafka (approved-trades)
                                                            |
                                                     Trade Executor (buffer pricing + broker)
                                                            |
                                                   Kafka (execution-results)
                                                            |
                                          Position Monitor  +  Notification Service
```

**Tech stack:** Python 3.13, FastAPI, SQLAlchemy (async), Kafka (KRaft), PostgreSQL 16, Redis 7, React 18, TypeScript, Tailwind CSS, Docker, Kubernetes.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | >= 3.11 | [python.org](https://python.org) |
| Docker + Docker Compose | >= 24.x | [docker.com](https://docker.com) |
| Node.js | >= 18 | [nodejs.org](https://nodejs.org) (dashboard only) |
| Git | >= 2.x | [git-scm.com](https://git-scm.com) |

---

## Quick Start (5 minutes)

### Step 1: Clone and install

```bash
git clone <your-repo-url>
cd discordmessages2trade

# Install Python dependencies (creates editable install)
make dev-install
```

### Step 2: Create your `.env` file

```bash
make env-file
```

This copies `.env.example` to `.env` and generates a Fernet encryption key. Open `.env` and fill in your secrets:

```bash
# Required -- change these:
JWT_SECRET_KEY=<run: openssl rand -hex 32>

# Optional -- for live trading:
ALPACA_API_KEY=<your alpaca key>
ALPACA_SECRET_KEY=<your alpaca secret>
DISCORD_BOT_TOKEN=<your discord bot token>
DISCORD_TARGET_CHANNELS=<comma-separated channel IDs>
```

### Step 3: Start infrastructure

```bash
make infra-up
```

This starts Kafka, PostgreSQL, and Redis in Docker containers. Wait ~10 seconds for health checks to pass.

### Step 4: Initialize the database

```bash
make db-init
```

### Step 5: Run the API Gateway

```bash
make run-gateway
```

The gateway starts on `http://localhost:8011`. Test it:

```bash
curl http://localhost:8011/health
# {"status":"ready","service":"api-gateway"}
```

### Step 6: Run the Dashboard (optional)

In a new terminal:

```bash
make dashboard-install   # first time only
make run-dashboard
```

Open `http://localhost:3000` in your browser. Register an account and explore the UI.

---

## Running the Full Pipeline

To run the entire trade pipeline locally (each in its own terminal):

```bash
# Terminal 1 -- Infrastructure
make infra-up

# Terminal 2 -- API Gateway (includes auth routes)
make run-gateway

# Terminal 3 -- Trade Parser
make run-parser

# Terminal 4 -- Trade Executor
make run-executor

# Terminal 5 -- Position Monitor
make run-monitor

# Terminal 6 -- Dashboard
make run-dashboard
```

---

## Running with Docker (Full Stack)

To run everything in Docker with a single command:

```bash
# Build all images
make docker-build

# Start the entire platform
make docker-up

# Watch logs
make docker-logs

# Stop everything
make docker-down
```

This starts:
- 3 infrastructure containers (Kafka, PostgreSQL, Redis)
- 1 init container (creates DB tables + Kafka topics)
- 10 microservice containers
- 1 dashboard container (nginx on port 3000)

The API is available at `http://localhost:8011` and the dashboard at `http://localhost:3000`.

---

## Available Make Commands

```bash
make help              # Show all commands with descriptions
```

| Command | Description |
|---------|-------------|
| `make dev-install` | Install all dependencies (prod + dev) |
| `make env-file` | Create .env from .env.example |
| `make lint` | Run ruff linter |
| `make test` | Run all 169 unit tests |
| `make test-cov` | Run tests with coverage report |
| `make benchmark` | Run latency benchmark |
| `make infra-up` | Start Kafka, Postgres, Redis |
| `make infra-down` | Stop infrastructure |
| `make db-init` | Create database tables |
| `make run-gateway` | Run API Gateway (:8011) |
| `make run-auth` | Run Auth Service (:8001) |
| `make run-parser` | Run Trade Parser (:8006) |
| `make run-executor` | Run Trade Executor (:8008) |
| `make run-monitor` | Run Position Monitor (:8009) |
| `make run-dashboard` | Run React dashboard (:3000) |
| `make docker-build` | Build all Docker images |
| `make docker-up` | Start entire platform in Docker |
| `make docker-down` | Stop entire platform |
| `make clean` | Remove build artifacts and caches |

---

## Project Structure

```
.
├── shared/                         # Shared Python libraries
│   ├── config/base_config.py       # Centralized config (env vars)
│   ├── models/                     # SQLAlchemy ORM models + DB engine
│   ├── kafka_utils/                # Kafka producer/consumer/DLQ
│   ├── broker/                     # BrokerAdapter protocol + Alpaca impl
│   ├── crypto/                     # Fernet credential encryption
│   ├── agents/                     # Agent plugin protocol + registry
│   ├── observability/              # Logging, metrics, tracing
│   ├── graceful_shutdown.py
│   ├── error_codes.py
│   ├── retry.py
│   ├── dedup.py
│   ├── rate_limiter.py
│   └── feature_flags.py
├── services/
│   ├── auth-service/               # JWT auth (register/login)
│   ├── api-gateway/                # REST API + JWT middleware
│   ├── discord-ingestor/           # Discord message ingestion
│   ├── trade-parser/               # Regex trade parser
│   ├── trade-gateway/              # Auto/manual approval
│   ├── trade-executor/             # Buffer pricing + broker execution
│   ├── position-monitor/           # Exit engine + daily aggregator
│   ├── notification-service/       # Discord bot commands
│   ├── source-orchestrator/        # Per-user ingestor management
│   ├── audit-writer/               # Off-path audit persistence
│   ├── signal-scorer/              # ML signal scoring agent
│   └── dashboard-ui/               # React + TypeScript + Tailwind
├── tests/
│   ├── unit/                       # 169 unit tests
│   ├── integration/
│   ├── e2e/
│   ├── benchmark/                  # Latency benchmark harness
│   └── load/                       # Locust load tests
├── k8s/                            # Kubernetes manifests
├── infra/                          # Grafana dashboards, Prometheus config
├── scripts/                        # Utility scripts
├── alembic/                        # Database migrations
├── docker-compose.yml              # Full stack
├── docker-compose.dev.yml          # Infrastructure only (dev)
├── Makefile                        # All commands
├── pyproject.toml                  # Python project config
└── .env.example                    # Environment variable template
```

---

## API Endpoints

Once the gateway is running, full docs are at `http://localhost:8011/docs`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Register a new user |
| POST | `/auth/login` | Login, get JWT tokens |
| POST | `/auth/refresh` | Refresh access token |
| GET | `/auth/me?token=` | Get current user profile |
| GET | `/api/v1/accounts` | List trading accounts |
| POST | `/api/v1/accounts` | Create trading account |
| PUT | `/api/v1/accounts/{id}` | Update account |
| DELETE | `/api/v1/accounts/{id}` | Delete account |
| POST | `/api/v1/accounts/{id}/toggle-mode` | Toggle paper/live |
| GET | `/api/v1/sources` | List data sources |
| POST | `/api/v1/sources` | Create data source |
| GET | `/api/v1/sources/{id}/channels` | List channels |
| POST | `/api/v1/sources/{id}/channels` | Add channel |
| GET | `/api/v1/mappings` | List account-source mappings |
| POST | `/api/v1/mappings` | Create mapping |
| GET | `/api/v1/trades` | List trades (filterable) |
| GET | `/api/v1/metrics/daily` | Daily P&L metrics |
| GET | `/api/v1/notifications` | List notifications |
| GET | `/api/v1/system/health` | System health status |

All `/api/v1/*` endpoints require `Authorization: Bearer <token>` header.

---

## Configuration Reference

All configuration is via environment variables. See `.env.example` for the full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker address |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `JWT_SECRET_KEY` | (required) | Secret for JWT signing |
| `CREDENTIAL_ENCRYPTION_KEY` | (required) | Fernet key for credential encryption |
| `BUFFER_PERCENTAGE` | `0.15` | Default order buffer (15%) |
| `MAX_POSITION_SIZE` | `10` | Max contracts per trade |
| `MAX_DAILY_LOSS` | `1000.0` | Daily loss limit ($) |
| `APPROVAL_MODE` | `auto` | `auto` or `manual` |
| `DEFAULT_PROFIT_TARGET` | `0.30` | Take profit at 30% |
| `DEFAULT_STOP_LOSS` | `0.20` | Stop loss at 20% |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## Testing

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test file
python3 -m pytest tests/unit/test_trade_parser.py -v

# Run latency benchmark
make benchmark

# Load testing (requires: pip install locust)
locust -f tests/load/locustfile.py --host http://localhost:8011
```

---

## Kubernetes Deployment

```bash
# Apply all manifests
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/services/
kubectl apply -f k8s/hpa.yaml
kubectl apply -f k8s/ingress.yaml

# Check status
kubectl -n phoenixtrader get pods
```

---

## Credential Rotation

To rotate the Fernet encryption key used for stored broker/source credentials:

```bash
python3 scripts/credential_rotation.py \
  --old-key "current-fernet-key" \
  --new-key "$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

Then update `CREDENTIAL_ENCRYPTION_KEY` in your `.env` and restart services.

---

## License

Private -- All rights reserved.
