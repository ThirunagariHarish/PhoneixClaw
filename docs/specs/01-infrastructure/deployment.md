# Spec: Deployment Strategy

## Purpose

End-to-end deployment process for Phoenix Claw, covering local development, Docker Compose, k3s production, and Claude Code VPS agent deployment.

## Environments

### Local Development

- `make dev-run` starts Postgres, Redis, API, and dashboard
- Uses Homebrew Postgres/Redis or Docker Compose (auto-detect)
- `.env` file for local configuration
- Dashboard at http://localhost:5173, API at http://localhost:8011

### Docker Compose (Full Stack)

- `docker-compose.yml` for complete local stack
- `docker-compose.dev.yml` for development with hot-reload
- All services, infra, and monitoring included

### Production (k3s)

- Host: 69.62.86.166
- Domain: cashflowus.com
- Platform: k3s with Traefik for TLS termination
- Compose file: `docker-compose.k3s.yml`
- Container registry: GHCR (ghcr.io/cashflowus/phoneixclaw/*)

## CI/CD Pipeline

### CI (.github/workflows/ci.yml)

Triggers: push to main/develop, PRs

Steps:

1. Lint Python (ruff) and TypeScript (eslint)
2. Run unit tests (pytest, vitest)
3. Docker build (no push) — validates all Dockerfiles compile
4. Security scan (trivy on built images)

### CD (.github/workflows/cd.yml)

Triggers: push of version tag (v*)

Steps:

1. Build all service images
2. Push to GHCR with tag
3. SSH to k3s VPS
4. Pull new images and restart services
5. Run database migrations (Alembic)
6. Health check all endpoints
7. Notify on failure (Discord webhook)

```yaml
# Deployment step (to replace commented webhook)
- name: Deploy to k3s VPS
  env:
    SSH_KEY: ${{ secrets.K3S_SSH_KEY }}
    VPS_HOST: ${{ secrets.K3S_HOST }}
  run: |
    mkdir -p ~/.ssh
    echo "$SSH_KEY" > ~/.ssh/deploy_key
    chmod 600 ~/.ssh/deploy_key
    ssh -o StrictHostKeyChecking=no -i ~/.ssh/deploy_key root@$VPS_HOST \
      "cd /data/k3s/applications/tsogksw8kg0kgkgoow048cgk && \
       kubectl pull && \
       kubectl up -d --remove-orphans && \
       kubectl exec phoenix-api alembic upgrade head"
```

## Database Migration Strategy

### Alembic Setup

- Config: `alembic.ini` in project root
- Migration directory: `alembic/versions/`
- Async engine: uses `shared.db.engine` with asyncpg

### Migration Flow

1. Developer creates migration: `make db-migrate msg="add notification table"`
2. Review generated migration in `alembic/versions/`
3. Apply locally: `make db-upgrade`
4. On deploy: init container runs `alembic upgrade head` before API starts

### Rollback

- `alembic downgrade -1` to revert last migration
- `make db-downgrade` Makefile target

## Service Startup Order

Services must start in this order (enforced by Docker Compose `depends_on` with `condition: service_healthy`):

1. postgres (healthcheck: pg_isready)
2. redis (healthcheck: redis-cli ping)
3. minio (healthcheck: curl)
4. phoenix-api (healthcheck: /health)
5. All other services (depend on api, postgres, and/or redis)

## Health Check Endpoints

| Service | Endpoint | Expected |
|---------|----------|----------|
| phoenix-api | GET /health | {"status": "ok"} |
| phoenix-ws-gateway | WS /ws/health | connection established |
| phoenix-execution | GET /health | {"status": "ok"} |
| phoenix-position-monitor | GET /health | {"status": "ok"} |
| All others | GET /health | {"status": "ok"} |

## Environment Variable Management

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| DATABASE_URL | Postgres connection | postgresql+asyncpg://user:pass@host:5432/db |
| REDIS_URL | Redis connection | redis://host:6379/0 |
| JWT_SECRET_KEY | JWT signing key | random 64-char string |
| DISCORD_TOKEN | Discord bot token | ... |
| RH_USERNAME | Robinhood username | ... |
| RH_PASSWORD | Robinhood password | ... |
| RH_TOTP_SECRET | Robinhood TOTP | ... |
| FERNET_KEY | Encryption key | ... |

### Secret Storage

- Local: `.env` file (gitignored)
- Production: k3s Environment Variables panel (encrypted at rest)
- Agent VPS: injected via SSH during ship-agent, stored in agent's `.env`

## Rollback Procedure

1. Identify failing version from k3s logs
2. `git tag` the last known working version
3. SSH to VPS: `kubectl pull [service]:previous-tag && kubectl up -d [service]`
4. If DB migration caused issue: `alembic downgrade -1`
5. Verify health endpoints

## Files to Create/Update

| File | Action |
|------|--------|
| `.github/workflows/cd.yml` | Update — wire SSH deploy |
| `docker-compose.k3s.yml` | Update — add missing services |
| `.env.production.example` | New — production env template |
| `alembic.ini` | New — migration config |
| `alembic/env.py` | New — async migration env |
