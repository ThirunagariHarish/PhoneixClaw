# PhoenixTrade Platform — Deployment Guide

## Architecture Overview

The platform consists of 14+ Docker services orchestrated via Docker Compose, deployed to a VPS
using Coolify (self-hosted PaaS).

### Services

| Service | Port | Description |
|---------|------|-------------|
| `postgres` | 5432 | PostgreSQL 16 database |
| `redis` | 6379 | Redis cache/dedup |
| `kafka` | 9092 | Apache Kafka message broker |
| `init` | — | DB schema migration (run-once) |
| `auth-service` | 8001 | JWT authentication |
| `api-gateway` | 8011 | REST API + WebSocket |
| `trade-parser` | 8006 | Regex + NLP trade parsing |
| `trade-gateway` | 8007 | Trade approval/routing |
| `trade-executor` | 8008 | Broker order execution |
| `position-monitor` | 8009 | P/L monitoring, stop-loss |
| `notification-service` | 8010 | Discord/email notifications |
| `source-orchestrator` | 8002 | Discord ingestor management |
| `audit-writer` | 8012 | Trade event + raw message persistence |
| `nlp-parser` | 8020 | FinBERT + spaCy NLP (1.5GB image) |
| `dashboard-ui` | 3080 | React frontend (nginx) |

### Message Flow

```
Discord → source-orchestrator → discord-ingestor
  → Kafka [raw-messages]
    → audit-writer (RawMessageWriterService → DB)
    → trade-parser (regex/NLP → Kafka [parsed-trades])
      → trade-gateway (approval → Kafka [approved-trades])
        → trade-executor (broker API → Kafka [execution-results])
          → notification-service (Discord/email alerts)
```

---

## Deployment Methods

### Method 1: Coolify (Production)

Coolify auto-deploys on push to `main`. To trigger manually:

```bash
# Normal deploy (uses Docker cache)
curl -sk -X GET \
  -H "Authorization: Bearer $COOLIFY_API_TOKEN" \
  "http://$VPS_IP:8000/api/v1/deploy?uuid=$APP_UUID"

# Force rebuild (no cache — use sparingly, causes long build times)
curl -sk -X GET \
  -H "Authorization: Bearer $COOLIFY_API_TOKEN" \
  "http://$VPS_IP:8000/api/v1/deploy?uuid=$APP_UUID&force=true"
```

**Check deployment status:**

```bash
curl -sk -X GET \
  -H "Authorization: Bearer $COOLIFY_API_TOKEN" \
  "http://$VPS_IP:8000/api/v1/deployments/$DEPLOYMENT_UUID"
```

### Method 2: Manual Docker Compose

```bash
# Build and start all services
DOCKER_BUILDKIT=1 docker compose -f docker-compose.coolify.yml up -d --build

# Build only specific services
DOCKER_BUILDKIT=1 docker compose -f docker-compose.coolify.yml build api-gateway dashboard-ui
docker compose -f docker-compose.coolify.yml up -d api-gateway dashboard-ui
```

---

## Selective Build Script

To avoid rebuilding all 14 images on every deploy, use the selective build script:

```bash
# Detect changes and build only modified services
./scripts/selective-build.sh

# Just list what would be built (dry run)
./scripts/selective-build.sh --list

# Force build all services
./scripts/selective-build.sh --all

# Compare against a specific commit
./scripts/selective-build.sh --since abc1234
```

**How it works:**
1. Runs `git diff` to find changed files since last commit.
2. Maps changed files to Docker Compose service names.
3. If `shared/` changed, rebuilds all Python services (they all depend on it).
4. If `docker-compose*.yml` changed, rebuilds everything.
5. Builds only the affected services with `docker compose build <service1> <service2>`.

---

## Docker Optimization

### BuildKit Cache Mounts

All Dockerfiles use BuildKit cache mounts for dependency installation:

- **Python services:** `--mount=type=cache,target=/root/.cache/pip` — pip packages cached across builds
- **dashboard-ui:** `--mount=type=cache,target=/root/.npm` — npm packages cached
- **nlp-parser:** `--mount=type=cache,target=/root/.cache/huggingface` — ML model weights cached

Requires `DOCKER_BUILDKIT=1` (Coolify enables this by default).

### NLP Parser Multi-Stage Build

The `nlp-parser` Dockerfile uses 3 stages:
1. **deps** — apt + pip install (cached unless requirements.txt changes)
2. **models** — spaCy, FinBERT, FLAN-T5 downloads (cached unless deps change)
3. **runtime** — slim image with only runtime files

This means adding a new Python source file does NOT re-download 1.5GB of ML models.

---

## Troubleshooting

### Deployment fails with disk space error

```bash
# SSH into VPS and clean Docker
ssh root@$VPS_IP "docker system prune -af --volumes && docker builder prune -af"

# Then redeploy WITHOUT force flag
curl -sk -X GET \
  -H "Authorization: Bearer $COOLIFY_API_TOKEN" \
  "http://$VPS_IP:8000/api/v1/deploy?uuid=$APP_UUID"
```

### Service not starting (check logs)

```bash
# On VPS
docker compose -f docker-compose.coolify.yml logs -f <service-name>
```

### Admin user loses admin status

This was fixed — the `/auth/refresh` endpoint now preserves the `is_admin` claim in the JWT.
If it happens again, the user should log out and log back in.

### Channels not showing in Backtesting

The `list_channels` endpoint now auto-syncs channels from credentials. If still empty:
1. Go to Data Sources page
2. Click the ⋮ menu on the source
3. Click "Sync Channels"
4. Return to Backtesting — channels should appear

### Raw messages not appearing

Check the pipeline in order:
1. **source-orchestrator logs:** Is the ingestor starting? Look for "Discord ingestor ready"
2. **Kafka:** Are messages being published to `raw-messages` topic?
3. **audit-writer logs:** Look for "Flushed N raw messages" or flush errors
4. **API:** `GET /api/v1/messages` — does it return data?

---

## Environment Variables

Required variables (set in Coolify Environment panel):

| Variable | Description |
|----------|-------------|
| `POSTGRES_PASSWORD` | Database password |
| `JWT_SECRET_KEY` | JWT signing key |
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key for credential encryption |
| `DISCORD_BOT_TOKEN` | (Optional) Bot token for notifications |
| `ENABLE_TRADING` | `true`/`false` — enable live trading |
| `DRY_RUN_MODE` | `true`/`false` — simulate trades without executing |

---

## Running Tests

```bash
# All tests
python3 -m pytest tests/ -v

# Integration tests only
python3 -m pytest tests/integration/ -v

# Unit tests only
python3 -m pytest tests/unit/ -v

# Linting
ruff check shared/ services/ tests/
```
