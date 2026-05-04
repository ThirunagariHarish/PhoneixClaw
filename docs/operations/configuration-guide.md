# Phoenix v2 Configuration Guide

This guide covers environment variables, Docker Compose setup, and k3s deployment for the Phoenix v2 trading bot.

---

## Environment Variables Reference

### API (`apps/api`)

| Variable | Description | Default |
|----------|-------------|---------|
| `API_DEBUG` | Enable debug mode | `false` |
| `API_HOST` | Bind host | `0.0.0.0` |
| `API_PORT` | HTTP port | `8011` |
| `DATABASE_URL` | PostgreSQL connection string | — |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379` |

### Database (PostgreSQL)

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_USER` | Database user | `phoenixtrader` |
| `POSTGRES_PASSWORD` | Database password | — |
| `POSTGRES_DB` | Database name | `phoenixtrader` |
| `DATABASE_URL` | Full async URL | `postgresql+asyncpg://user:pass@host:5432/db` |

### Redis

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` |

### MinIO (Object Storage)

| Variable | Description | Default |
|----------|-------------|---------|
| `MINIO_ENDPOINT` | MinIO API endpoint | `http://minio:9000` |
| `MINIO_ROOT_USER` | MinIO admin user | `minioadmin` |
| `MINIO_ROOT_PASSWORD` | MinIO admin password | `minioadmin` |

### Auth (JWT)

| Variable | Description | Default |
|----------|-------------|---------|
| `JWT_SECRET_KEY` | Secret for signing tokens | — (required in prod) |
| `JWT_ALGORITHM` | Signing algorithm | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access token TTL | `30` |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL | `7` |
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key for credentials | — (required) |

### Brokers (Alpaca)

| Variable | Description | Default |
|----------|-------------|---------|
| `ALPACA_API_KEY` | Alpaca API key | — |
| `ALPACA_SECRET_KEY` | Alpaca secret | — |
| `ALPACA_BASE_URL` | API base URL | `https://paper-api.alpaca.markets` |
| `ALPACA_PAPER` | Use paper trading | `true` |

---

## Docker Compose Setup

### Development

```bash
# Start core services (PostgreSQL, Redis)
docker compose -f docker-compose.dev.yml up -d

# Run API and dashboard locally
cd apps/api && uvicorn apps.api.src.main:app --reload
cd apps/dashboard && npm run dev
```

### Production (Phoenix v2 stack)

```bash
cd infra
cp .env.example .env
# Edit .env with production values (JWT_SECRET_KEY, CREDENTIAL_ENCRYPTION_KEY, etc.)
docker compose -f docker-compose.production.yml up -d
```

Services: `phoenix-api`, `phoenix-dashboard`, `phoenix-ws-gateway`, `phoenix-execution`, `phoenix-automation`, `phoenix-connector-manager`, `phoenix-backtest-runner`, `phoenix-agent-comm`, `phoenix-global-monitor`, plus PostgreSQL, Redis, MinIO, Nginx, Prometheus, Grafana, Loki, Promtail.

---

## k3s Deployment

1. **Provision k3s** on a fresh VPS:
   ```bash
   LETSENCRYPT_EMAIL=admin@yourdomain.com ./infra/scripts/provision-k3s.sh
   ```

2. **Seal secrets** using kubeseal and apply the SealedSecret YAML. See `helm/phoenix/README.md` for the complete workflow.

3. **Deploy via Helm**:
   ```bash
   helm install phoenix helm/phoenix -f helm/phoenix/values.prod.yaml -n phoenix --create-namespace --wait
   ```

4. **Deploy** using the Helm chart. The chart includes the IngressRoute and TLS certificate.
