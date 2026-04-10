# Phoenix v2 Configuration Guide

This guide covers environment variables, Docker Compose setup, WireGuard VPN, OpenClaw instances, and Coolify deployment for the Phoenix v2 trading bot.

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

### OpenClaw / Bridge

| Variable | Description | Default |
|----------|-------------|---------|
| `BRIDGE_TOKEN` | Token for bridge API auth | — |
| `MINIO_ENDPOINT` | MinIO for skill sync | — |
| `BRIDGE_URL` | Bridge service URL | `http://phoenix-bridge:18800` |

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

Services: `phoenix-api`, `phoenix-dashboard`, `phoenix-bridge`, `phoenix-ws-gateway`, `phoenix-execution`, `phoenix-automation`, `phoenix-connector-manager`, `phoenix-backtest-runner`, `phoenix-skill-sync`, `phoenix-agent-comm`, `phoenix-global-monitor`, plus PostgreSQL, Redis, MinIO, Nginx, Prometheus, Grafana, Loki, Promtail.

---

## WireGuard VPN Configuration

Phoenix uses WireGuard for secure communication between the control plane and remote OpenClaw nodes.

1. **Install WireGuard** on control plane and node VPS:
   - Ubuntu: `apt install wireguard`
   - macOS: App Store or `brew install wireguard-tools`

2. **Generate keys** on each peer:
   ```bash
   wg genkey | tee privatekey | wg pubkey > publickey
   ```

3. **Create `/etc/wireguard/wg0.conf`** on each host with `[Interface]` and `[Peer]` sections. Use a private subnet (e.g. `10.0.0.0/24`).

4. **Start WireGuard**:
   ```bash
   sudo wg-quick up wg0
   ```

5. **Test connectivity**:
   ```bash
   ./infra/scripts/test_wireguard.sh
   # Or: PEER_IPS=10.0.0.2,10.0.0.3 ./infra/scripts/test_wireguard.sh
   ```

---

## OpenClaw Instance Setup

1. **Provision a node** (VPS or laptop):
   ```bash
   ./infra/scripts/provision-local-node.sh https://api.phoenix.example.com
   ```

2. **Configure instance** in `openclaw/configs/` (e.g. `openclaw-instance-d.json`):
   - `instance_name`, `role`, `node_type`, `host`, `port`
   - `bridge_token` (must match control plane)
   - `agents` array with `id`, `path`, `type`, `auto_start`
   - `capabilities` and `resource_limits`

3. **Deploy Bridge** on the node to expose REST API on port 18800. The control plane registers instances and manages agents via the bridge.

4. **Register node** with the control plane (done by `provision-local-node.sh` or manually via `POST /api/v1/nodes/register`).

---

## Coolify Deployment

1. **Provision Coolify** on a fresh VPS:
   ```bash
   ./infra/scripts/provision-coolify.sh
   # Or: ./infra/scripts/provision-coolify.sh --skip-firewall
   ```

2. **Create a new project** in Coolify and add the Phoenix repo.

3. **Set environment variables** from `.env.coolify.example` in Coolify's Environment Variables panel. Required: `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`.

4. **Deploy** using `docker-compose.coolify.yml` or the production compose file. Coolify will build and run the stack.

5. **Configure domains** for API and dashboard in Coolify (e.g. `api.phoenix.example.com`, `app.phoenix.example.com`).
