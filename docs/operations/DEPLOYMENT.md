# PhoenixTrade Platform — Deployment Guide

## Architecture Overview

The platform consists of 15+ microservices deployed on k3s via Helm. Production runs on a single-node VPS with Traefik ingress and cert-manager for TLS.

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

### Method 1: k3s + Helm (Production)

Production deploys automatically on tagged releases via GitHub Actions CD workflow. The workflow builds all service images, pushes to GHCR, and runs `helm upgrade` on the k3s cluster.

**Manual deployment:**

```bash
# Tag a release
git tag v1.2.3
git push origin v1.2.3

# Or manually deploy from the VPS
ssh root@<VPS_IP>
cd /opt/phoenix
helm upgrade --install phoenix helm/phoenix \
  -f helm/phoenix/values.prod.yaml \
  -n phoenix --create-namespace \
  --set image.tag=v1.2.3 \
  --wait --timeout=15m
```

**Check deployment status:**

```bash
kubectl get pods -n phoenix
kubectl logs -n phoenix -l app.kubernetes.io/part-of=phoenix --tail=50
```

### Method 2: Local Docker Compose

```bash
# Build and start all services
make up

# Stop all services
make down
```

---

## CI/CD Pipeline

The `.github/workflows/cd.yml` workflow handles production deployments:

1. Trigger: Push a `v*` tag
2. Build all 14 service images with Docker Buildx
3. Tag each image as `ghcr.io/thirunagariharish/phoneixclaw/phoenix-<svc>:$TAG` and `:latest`
4. Push to GitHub Container Registry
5. SSH to k3s host, copy Helm chart, run `helm upgrade --install`
6. Helm pre-install hook runs database migrations
7. Traefik routes public traffic to the new pods

**Required secrets:**
- `K3S_HOST` — VPS IP or hostname
- `K3S_SSH_KEY` — Private SSH key for root@VPS

---

## Docker Optimization

### BuildKit Cache Mounts

All Dockerfiles use BuildKit cache mounts for dependency installation:

- **Python services:** `--mount=type=cache,target=/root/.cache/pip` — pip packages cached across builds
- **dashboard-ui:** `--mount=type=cache,target=/root/.npm` — npm packages cached
- **nlp-parser:** `--mount=type=cache,target=/root/.cache/huggingface` — ML model weights cached

Requires `DOCKER_BUILDKIT=1` (GitHub Actions `docker/setup-buildx-action@v3` enables this by default).

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
# SSH into VPS and clean k3s containerd image cache
ssh root@$VPS_IP "k3s crictl rmi --prune"

# Then re-tag the release to retrigger CD, or run helm upgrade manually:
ssh root@$VPS_IP "helm upgrade --install phoenix /opt/phoenix/helm/phoenix \
  -f /opt/phoenix/helm/phoenix/values.prod.yaml -n phoenix \
  --set image.tag=$TAG --wait --timeout=15m"
```

### Service not starting (check logs)

```bash
# On k3s
kubectl logs -n phoenix deployment/phoenix-<service> --tail=100 -f

# Or view all Phoenix logs
kubectl logs -n phoenix -l app.kubernetes.io/part-of=phoenix --tail=50 --prefix
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

Required variables (sealed via SealedSecret in k3s, or set in `.env` for local dev):

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
