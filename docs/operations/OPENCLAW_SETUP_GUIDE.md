# OpenClaw Instance Setup Guide

Complete step-by-step guide for setting up OpenClaw instances, connecting them to Phoenix Claw, running multiple instances in Docker on a single machine, configuring agents, and optimizing token usage with safeguard prompts.

---

## Table of Contents

1. [Overview and Architecture](#1-overview-and-architecture)
2. [Prerequisites](#2-prerequisites)
3. [Single Instance Setup (Docker)](#3-single-instance-setup-docker)
4. [Multiple Instances on a Single Machine](#4-multiple-instances-on-a-single-machine)
5. [Agent Configuration](#5-agent-configuration)
6. [System Prompts for Token Safeguarding and Optimization](#6-system-prompts-for-token-safeguarding-and-optimization)
7. [Configuring the Bridge Connection](#7-configuring-the-bridge-connection)
8. [WireGuard Setup for Remote Nodes](#8-wireguard-setup-for-remote-nodes)
9. [Security Best Practices](#9-security-best-practices)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Overview and Architecture

### What is OpenClaw?

OpenClaw is the AI agent execution runtime. Each OpenClaw instance runs one or more autonomous agents (trading agents, research analysts, risk monitors, etc.). Phoenix Claw is the control plane that orchestrates, monitors, and manages these instances through a **Bridge Service** sidecar.

### How it connects

```
┌─────────────────────┐
│   Phoenix Claw      │
│   Dashboard (:3000) │
└────────┬────────────┘
         │ HTTP
         ▼
┌─────────────────────┐
│   Phoenix API       │
│   (:8011)           │
│   - /api/v2/instances│
│   - /api/v2/agents  │
└────────┬────────────┘
         │ HTTP (WireGuard or Docker network)
         ▼
┌─────────────────────┐     ┌──────────────────┐
│   Bridge Service    │────▶│  OpenClaw Instance│
│   (:18800)          │     │  (Agent Runtime)  │
│   - X-Bridge-Token  │     │                   │
│   - Agent CRUD      │     │  Agent A          │
│   - Heartbeat       │     │  Agent B          │
│   - Skill Sync      │     │  Agent C          │
└─────────────────────┘     └──────────────────┘
```

### Bridge Sidecar Pattern

Every OpenClaw instance has a **Bridge Service** sidecar:
- REST API on port **18800** (configurable)
- Authenticated via **`X-Bridge-Token`** header
- Handles: agent CRUD, heartbeat reporting, skill sync from MinIO, agent messaging
- Auto-registers with the Phoenix API control plane on startup

### Key Endpoints (Bridge)

| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /health` | None | Health check |
| `GET /heartbeat` | `X-Bridge-Token` | Agent statuses, positions, PnL |
| `GET /agents` | `X-Bridge-Token` | List all agents |
| `POST /agents` | `X-Bridge-Token` | Create agent |
| `PUT /agents/{id}` | `X-Bridge-Token` | Update agent |
| `DELETE /agents/{id}` | `X-Bridge-Token` | Delete agent |
| `POST /agents/{id}/pause` | `X-Bridge-Token` | Pause agent |
| `POST /agents/{id}/resume` | `X-Bridge-Token` | Resume agent |
| `POST /agents/{id}/message` | `X-Bridge-Token` | Send message to agent |
| `GET /agents/{id}/logs` | `X-Bridge-Token` | Get agent logs |
| `POST /skills/sync` | `X-Bridge-Token` | Pull skills from MinIO |
| `GET /metrics` | None | Prometheus metrics |

---

## 2. Prerequisites

Before setting up OpenClaw instances, ensure:

### Required

- **Docker** >= 24.0 and **Docker Compose** >= 2.20
- **Phoenix Claw stack running**:
  - API on port `8011` (or your configured port)
  - Dashboard on port `3000`
  - PostgreSQL, Redis, MinIO all healthy
- A **strong unique `BRIDGE_TOKEN`**: 4cf6e005da14b87fbfcb2a2ca6d793521a9885716e63b5a4bedeedb4f74307e3
  ```bash
  # Generate a secure token
  openssl rand -hex 32
  # Example output: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2
  ```

### For remote/VPS nodes

- **WireGuard** installed on both the control plane and remote node
- Network connectivity between control plane and node (see [Section 8](#8-wireguard-setup-for-remote-nodes))

### For local (same machine) instances

- Instances share the Docker network with the Phoenix stack
- No WireGuard needed; services communicate via Docker service names

---

## 3. Single Instance Setup (Docker)

This section walks through setting up **one** OpenClaw Bridge on the same machine as the Phoenix stack. For multiple instances, complete this section first, then proceed to [Section 4](#4-multiple-instances-on-a-single-machine).

### Step 1: Create an instance configuration file

Create a JSON config file describing your instance. Use `openclaw/configs/openclaw-instance-d.json` as a template:

```json
{
  "instance_name": "My-Trading-Instance",
  "role": "general",
  "description": "General-purpose trading and research instance",
  "node_type": "local",
  "host": "phoenix-bridge",
  "port": 18800,
  "bridge_token": "YOUR_GENERATED_TOKEN_HERE",
  "agents": [],
  "capabilities": {
    "live_trading": false,
    "paper_trading": true,
    "backtesting": true,
    "strategy_lab": true,
    "max_agents": 10
  },
  "resource_limits": {
    "max_memory_mb": 4096,
    "max_cpu_percent": 80
  }
}
```

Save this as `openclaw/configs/my-instance.json`.

### Step 2: Add Bridge environment variables to `.env`

The project's `.env.example` does **not** include Bridge variables. Append the following block to your `.env` file at the project root:

```bash
# ======================
# OpenClaw Bridge Config
# ======================

# Auth token shared between the Bridge and the Phoenix API.
# Generate with: openssl rand -hex 32
BRIDGE_TOKEN=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2

# MinIO connection for skill sync (Docker service name when on the same compose network)
MINIO_ENDPOINT=http://minio:9000
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin

# Phoenix API address as reachable FROM the Bridge container.
# For local (same machine): use the Docker service name.
# For remote (VPS): use the WireGuard IP of the control plane, e.g. http://10.0.1.1:8011
CONTROL_PLANE_URL=http://phoenix-api:8011

# Unique display name for this instance (appears in the dashboard Network page)
INSTANCE_NAME=My-Trading-Instance

# "local" = same machine as Phoenix stack, "vps" = remote node
NODE_TYPE=local

# Port the Bridge listens on inside the container (rarely needs changing)
BRIDGE_PORT=18800
```

> **What each variable does:**
>
> | Variable | Purpose | Where it's used |
> |----------|---------|-----------------|
> | `BRIDGE_TOKEN` | Authenticates every request between Phoenix API and the Bridge via the `X-Bridge-Token` header. Must be identical on both sides. | Bridge `config.py`, API instance routes |
> | `MINIO_ENDPOINT` | Address of the MinIO object store for pulling skill files. Inside Docker use the service name (`minio`), not `localhost`. | Bridge `skill_sync.py` |
> | `CONTROL_PLANE_URL` | The URL the Bridge calls to auto-register itself with the Phoenix API on startup. | Bridge `auto_register.py` |
> | `INSTANCE_NAME` | Human-readable name. Shows up in the dashboard Network graph and the Agents instance dropdown. | Bridge `auto_register.py` |
> | `NODE_TYPE` | Tells the control plane whether this is a co-located Docker instance (`local`) or a remote machine (`vps`). | Bridge `auto_register.py` |
> | `BRIDGE_PORT` | The TCP port uvicorn binds to inside the container. The docker-compose port mapping controls the host-side port. | Bridge `main.py` / Dockerfile |

### Step 3: Update `docker-compose.yml` for the Bridge service

The existing `phoenix-bridge` service in `docker-compose.yml` is missing several environment variables that the Bridge code requires. Update it to match:

```yaml
phoenix-bridge:
  build:
    context: .
    dockerfile: openclaw/bridge/Dockerfile
  ports:
    - "18800:18800"
  environment:
    - BRIDGE_TOKEN=${BRIDGE_TOKEN}
    - MINIO_ENDPOINT=${MINIO_ENDPOINT:-http://minio:9000}
    - MINIO_ACCESS_KEY=${MINIO_ROOT_USER:-minioadmin}
    - MINIO_SECRET_KEY=${MINIO_ROOT_PASSWORD:-minioadmin}
    - CONTROL_PLANE_URL=${CONTROL_PLANE_URL:-http://phoenix-api:8011}
    - INSTANCE_NAME=${INSTANCE_NAME:-openclaw-default}
    - NODE_TYPE=${NODE_TYPE:-local}
    - AGENTS_ROOT=/data/agents
  volumes:
    - bridge_agents:/data/agents
  depends_on:
    - phoenix-api
    - minio
  deploy:
    resources:
      limits:
        memory: 256M
  restart: unless-stopped
```

> **Current code gap:** The `docker-compose.yml` shipped in the repo only passes `BRIDGE_TOKEN` and `MINIO_ENDPOINT` to the Bridge. The variables `CONTROL_PLANE_URL`, `INSTANCE_NAME`, `NODE_TYPE`, `MINIO_ACCESS_KEY`, and `MINIO_SECRET_KEY` are all used by the Bridge code (`auto_register.py`, `config.py`, `skill_sync.py`) but are not in the compose file. You **must** add them as shown above or auto-registration and skill sync will silently use defaults / fail.

Don't forget to add the `bridge_agents` volume to the `volumes:` section at the bottom of `docker-compose.yml`:

```yaml
volumes:
  pgdata:
  miniodata:
  # ... existing volumes ...
  bridge_agents:
```

### Step 4: Start the Bridge

```bash
docker compose up -d phoenix-bridge
```

Confirm the container is running:

```bash
docker compose ps phoenix-bridge
# STATUS should show "Up" or "running"
```

### Step 5: Verify the Bridge is healthy

```bash
# Health check (no auth required)
curl http://localhost:18800/health
# Expected: {"status":"ready","service":"phoenix-bridge"}

# Heartbeat (requires token)
curl -H "X-Bridge-Token: $BRIDGE_TOKEN" http://localhost:18800/heartbeat
# Expected: {"agents":[],"count":0}

# List agents
curl -H "X-Bridge-Token: $BRIDGE_TOKEN" http://localhost:18800/agents
# Expected: {"agents":[]}
```

If you get "connection refused", check `docker compose logs phoenix-bridge --tail 50`.

### Step 6: Register the instance with Phoenix API

**Option A: Auto-registration (recommended)**

If `CONTROL_PLANE_URL` is set and the Phoenix API is reachable, the Bridge auto-registers on startup. Check the logs:

```bash
docker compose logs phoenix-bridge | grep -i register
# Look for: "Registered with control plane: 201"
```

> **Current code gap:** The `auto_register()` function exists in `openclaw/bridge/src/auto_register.py` but is not wired into the FastAPI lifespan in `main.py` yet. Until this is connected, use **Option B** (manual registration) below.

**Option B: Manual registration**

```bash
# 1. Get a JWT token by logging in to the Phoenix API
TOKEN=$(curl -s -X POST http://localhost:8011/api/v2/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@phoenix.local","password":"admin"}' \
  | jq -r '.access_token')

# 2. Register the instance
curl -X POST http://localhost:8011/api/v2/instances \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "My-Trading-Instance",
    "host": "phoenix-bridge",
    "port": 18800,
    "role": "general",
    "node_type": "local",
    "capabilities": {
      "paper_trading": true,
      "backtesting": true,
      "max_agents": 10
    }
  }'
# Expected: 201 Created with instance JSON including an "id" field
```

> **Important:** The `host` field must be the address the **Phoenix API** uses to reach the Bridge. For local Docker containers on the same network, this is the Docker service name (e.g., `phoenix-bridge`). For remote VPS, this is the WireGuard IP (e.g., `10.0.1.10`).

### Step 7: Verify in the dashboard

1. Open `http://localhost:3000` and log in
2. Go to **Agents** > **Network** in the sidebar
3. Your instance should appear as a node in the network graph
4. Status should show **ONLINE** (green) if heartbeats are flowing

---

## 4. Multiple Instances on a Single Machine

This section covers running **multiple OpenClaw Bridge instances** as separate Docker containers on the **same physical/virtual machine**. Each instance is isolated with its own port, data volume, and name, but they all share the same Docker network as the Phoenix stack.

### 4.1 Planning Your Instances

Before creating containers, decide how many instances you need and what each one does. Here is a recommended 4-instance layout:

| Instance Name | Host Port | Container Port | Role | Memory Limit | Purpose |
|---------------|-----------|----------------|------|-------------|---------|
| `OpenClaw-Paper-Trading` | 18800 | 18800 | `general` | 256 MB | Paper trading agents |
| `OpenClaw-Research` | 18801 | 18800 | `research` | 256 MB | Technical/fundamental analysis agents |
| `OpenClaw-Backtest` | 18802 | 18800 | `backtest` | 512 MB | Backtesting (higher memory for data) |
| `OpenClaw-Live-Trading` | 18803 | 18800 | `live-trading` | 512 MB | Live trading (restricted, approval-gated) |

**Key decisions:**

- **Shared vs unique `BRIDGE_TOKEN`**: A single token simplifies management. Unique tokens per instance give stronger isolation (a compromised token only affects one instance). For development, shared is fine.
- **Port allocation**: Each instance maps a unique host port (18800, 18801, ...) to the same container port (18800). The container port never changes.
- **Data isolation**: Each instance gets its own Docker volume so agent workspaces are completely separate.

### 4.2 Step 1 -- Create instance config files

Create a JSON config for each instance in `openclaw/configs/`:

**`openclaw/configs/instance-paper-trading.json`**

```json
{
  "instance_name": "OpenClaw-Paper-Trading",
  "role": "general",
  "description": "Paper trading and strategy testing",
  "node_type": "local",
  "host": "phoenix-bridge-a",
  "port": 18800,
  "bridge_token": "YOUR_BRIDGE_TOKEN",
  "agents": [],
  "capabilities": {
    "live_trading": false,
    "paper_trading": true,
    "backtesting": false,
    "max_agents": 10
  },
  "resource_limits": { "max_memory_mb": 256, "max_cpu_percent": 80 }
}
```

**`openclaw/configs/instance-research.json`**

```json
{
  "instance_name": "OpenClaw-Research",
  "role": "research",
  "description": "Technical analysis, sentiment, macro research agents",
  "node_type": "local",
  "host": "phoenix-bridge-b",
  "port": 18800,
  "bridge_token": "YOUR_BRIDGE_TOKEN",
  "agents": [],
  "capabilities": {
    "live_trading": false,
    "paper_trading": false,
    "backtesting": false,
    "max_agents": 10
  },
  "resource_limits": { "max_memory_mb": 256, "max_cpu_percent": 60 }
}
```

**`openclaw/configs/instance-backtest.json`**

```json
{
  "instance_name": "OpenClaw-Backtest",
  "role": "backtest",
  "description": "Historical data backtesting and strategy validation",
  "node_type": "local",
  "host": "phoenix-bridge-c",
  "port": 18800,
  "bridge_token": "YOUR_BRIDGE_TOKEN",
  "agents": [],
  "capabilities": {
    "live_trading": false,
    "paper_trading": false,
    "backtesting": true,
    "strategy_lab": true,
    "max_agents": 5
  },
  "resource_limits": { "max_memory_mb": 512, "max_cpu_percent": 90 }
}
```

**`openclaw/configs/instance-live-trading.json`**

```json
{
  "instance_name": "OpenClaw-Live-Trading",
  "role": "live-trading",
  "description": "Live trading with human approval gates",
  "node_type": "local",
  "host": "phoenix-bridge-d",
  "port": 18800,
  "bridge_token": "YOUR_BRIDGE_TOKEN",
  "agents": [],
  "capabilities": {
    "live_trading": true,
    "paper_trading": true,
    "backtesting": false,
    "max_agents": 5
  },
  "resource_limits": { "max_memory_mb": 512, "max_cpu_percent": 80 }
}
```

### 4.3 Step 2 -- Set environment variables in `.env`

Make sure your `.env` has all Bridge variables (see [Section 3, Step 2](#step-2-add-bridge-environment-variables-to-env)). The `BRIDGE_TOKEN`, `MINIO_*`, and `CONTROL_PLANE_URL` values are shared by all instances via the compose file. The `INSTANCE_NAME` is overridden per-service in the compose file, so the `.env` value is only a fallback.

### 4.4 Step 3 -- Create `docker-compose.multi-openclaw.yml`

Create this file **alongside** your main `docker-compose.yml` in the project root:

```yaml
version: "3.9"

services:
  # ─────────────────────────────────────────────
  # Instance A: Paper Trading (host port 18800)
  # ─────────────────────────────────────────────
  phoenix-bridge-a:
    build:
      context: .
      dockerfile: openclaw/bridge/Dockerfile
    container_name: phoenix-bridge-a
    ports:
      - "18800:18800"
    environment:
      - BRIDGE_TOKEN=${BRIDGE_TOKEN}
      - MINIO_ENDPOINT=${MINIO_ENDPOINT:-http://minio:9000}
      - MINIO_ACCESS_KEY=${MINIO_ROOT_USER:-minioadmin}
      - MINIO_SECRET_KEY=${MINIO_ROOT_PASSWORD:-minioadmin}
      - CONTROL_PLANE_URL=${CONTROL_PLANE_URL:-http://phoenix-api:8011}
      - INSTANCE_NAME=OpenClaw-Paper-Trading
      - NODE_TYPE=local
      - AGENTS_ROOT=/data/agents
    volumes:
      - bridge_a_agents:/data/agents
    networks:
      - phoenix-net
    deploy:
      resources:
        limits:
          memory: 256M
    restart: unless-stopped

  # ─────────────────────────────────────────────
  # Instance B: Research & Analysis (host port 18801)
  # ─────────────────────────────────────────────
  phoenix-bridge-b:
    build:
      context: .
      dockerfile: openclaw/bridge/Dockerfile
    container_name: phoenix-bridge-b
    ports:
      - "18801:18800"
    environment:
      - BRIDGE_TOKEN=${BRIDGE_TOKEN}
      - MINIO_ENDPOINT=${MINIO_ENDPOINT:-http://minio:9000}
      - MINIO_ACCESS_KEY=${MINIO_ROOT_USER:-minioadmin}
      - MINIO_SECRET_KEY=${MINIO_ROOT_PASSWORD:-minioadmin}
      - CONTROL_PLANE_URL=${CONTROL_PLANE_URL:-http://phoenix-api:8011}
      - INSTANCE_NAME=OpenClaw-Research
      - NODE_TYPE=local
      - AGENTS_ROOT=/data/agents
    volumes:
      - bridge_b_agents:/data/agents
    networks:
      - phoenix-net
    deploy:
      resources:
        limits:
          memory: 256M
    restart: unless-stopped

  # ─────────────────────────────────────────────
  # Instance C: Backtesting (host port 18802)
  # ─────────────────────────────────────────────
  phoenix-bridge-c:
    build:
      context: .
      dockerfile: openclaw/bridge/Dockerfile
    container_name: phoenix-bridge-c
    ports:
      - "18802:18800"
    environment:
      - BRIDGE_TOKEN=${BRIDGE_TOKEN}
      - MINIO_ENDPOINT=${MINIO_ENDPOINT:-http://minio:9000}
      - MINIO_ACCESS_KEY=${MINIO_ROOT_USER:-minioadmin}
      - MINIO_SECRET_KEY=${MINIO_ROOT_PASSWORD:-minioadmin}
      - CONTROL_PLANE_URL=${CONTROL_PLANE_URL:-http://phoenix-api:8011}
      - INSTANCE_NAME=OpenClaw-Backtest
      - NODE_TYPE=local
      - AGENTS_ROOT=/data/agents
    volumes:
      - bridge_c_agents:/data/agents
    networks:
      - phoenix-net
    deploy:
      resources:
        limits:
          memory: 512M
    restart: unless-stopped

  # ─────────────────────────────────────────────
  # Instance D: Live Trading (host port 18803)
  # ─────────────────────────────────────────────
  phoenix-bridge-d:
    build:
      context: .
      dockerfile: openclaw/bridge/Dockerfile
    container_name: phoenix-bridge-d
    ports:
      - "18803:18800"
    environment:
      - BRIDGE_TOKEN=${BRIDGE_TOKEN}
      - MINIO_ENDPOINT=${MINIO_ENDPOINT:-http://minio:9000}
      - MINIO_ACCESS_KEY=${MINIO_ROOT_USER:-minioadmin}
      - MINIO_SECRET_KEY=${MINIO_ROOT_PASSWORD:-minioadmin}
      - CONTROL_PLANE_URL=${CONTROL_PLANE_URL:-http://phoenix-api:8011}
      - INSTANCE_NAME=OpenClaw-Live-Trading
      - NODE_TYPE=local
      - AGENTS_ROOT=/data/agents
    volumes:
      - bridge_d_agents:/data/agents
    networks:
      - phoenix-net
    deploy:
      resources:
        limits:
          memory: 512M
    restart: unless-stopped

volumes:
  bridge_a_agents:
  bridge_b_agents:
  bridge_c_agents:
  bridge_d_agents:

networks:
  phoenix-net:
    external: true
    name: projectphoneix_default
```

**Understanding the network:**

- `projectphoneix_default` is the Docker network automatically created by `docker compose up` from the main `docker-compose.yml`. The name follows the pattern `<project-directory>_default`.
- By joining this external network, all Bridge containers can reach `phoenix-api`, `minio`, `redis`, and `postgres` by their Docker service names.
- If your project directory has a different name, check with `docker network ls` and update the `name:` field accordingly.

### 4.5 Step 4 -- Start the Phoenix stack first

The Bridge instances depend on `phoenix-api` and `minio`. Start the main stack and wait for it to be healthy:

```bash
# Start the core Phoenix stack
docker compose up -d

# Verify critical services are healthy
docker compose ps
# Confirm phoenix-api, postgres, redis, minio all show "Up" / "healthy"
```

### 4.6 Step 5 -- Build and start all Bridge instances

```bash
# Build the Bridge image (shared by all instances)
docker compose -f docker-compose.multi-openclaw.yml build

# Start all 4 instances
docker compose -f docker-compose.multi-openclaw.yml up -d
```

Verify all containers are running:

```bash
docker compose -f docker-compose.multi-openclaw.yml ps
# All 4 should show "Up" or "running"
```

### 4.7 Step 6 -- Verify each Bridge is healthy

Run a health check loop across all ports:

```bash
for port in 18800 18801 18802 18803; do
  echo "--- Bridge on :$port ---"
  curl -s http://localhost:$port/health
  echo ""
done
```

Expected output for each:

```json
{"status":"ready","service":"phoenix-bridge"}
```

If any returns "connection refused", check that specific container's logs:

```bash
docker logs phoenix-bridge-a --tail 30
docker logs phoenix-bridge-b --tail 30
docker logs phoenix-bridge-c --tail 30
docker logs phoenix-bridge-d --tail 30
```

### 4.8 Step 7 -- Register instances with the Phoenix API

Since auto-registration is not yet wired into the Bridge lifespan (see [Section 3, Step 6 note](#step-6-register-the-instance-with-phoenix-api)), register each instance manually:

```bash
# 1. Get a JWT token
TOKEN=$(curl -s -X POST http://localhost:8011/api/v2/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@phoenix.local","password":"admin"}' \
  | jq -r '.access_token')

# 2. Register Instance A (Paper Trading)
curl -s -X POST http://localhost:8011/api/v2/instances \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "OpenClaw-Paper-Trading",
    "host": "phoenix-bridge-a",
    "port": 18800,
    "role": "general",
    "node_type": "local",
    "capabilities": {"paper_trading": true, "max_agents": 10}
  }'

# 3. Register Instance B (Research)
curl -s -X POST http://localhost:8011/api/v2/instances \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "OpenClaw-Research",
    "host": "phoenix-bridge-b",
    "port": 18800,
    "role": "research",
    "node_type": "local",
    "capabilities": {"paper_trading": false, "max_agents": 10}
  }'

# 4. Register Instance C (Backtest)
curl -s -X POST http://localhost:8011/api/v2/instances \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "OpenClaw-Backtest",
    "host": "phoenix-bridge-c",
    "port": 18800,
    "role": "backtest",
    "node_type": "local",
    "capabilities": {"backtesting": true, "strategy_lab": true, "max_agents": 5}
  }'

# 5. Register Instance D (Live Trading)
curl -s -X POST http://localhost:8011/api/v2/instances \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "OpenClaw-Live-Trading",
    "host": "phoenix-bridge-d",
    "port": 18800,
    "role": "live-trading",
    "node_type": "local",
    "capabilities": {"live_trading": true, "paper_trading": true, "max_agents": 5}
  }'
```

> **Important:** The `host` value for local instances is the **Docker service name** (e.g., `phoenix-bridge-a`), NOT `localhost`. The Phoenix API runs inside Docker and resolves service names via Docker DNS. The `port` is always `18800` (the container port), regardless of the host port mapping.

Confirm all 4 instances are registered:

```bash
curl -s http://localhost:8011/api/v2/instances \
  -H "Authorization: Bearer $TOKEN" | jq '.[].name'
# Expected:
# "OpenClaw-Paper-Trading"
# "OpenClaw-Research"
# "OpenClaw-Backtest"
# "OpenClaw-Live-Trading"
```

### 4.9 Step 8 -- Verify in the dashboard

1. Open `http://localhost:3000` and log in
2. Navigate to **Agents** > **Network** in the sidebar
3. All 4 instances should appear as nodes in the network graph
4. Each should show **ONLINE** (green) if heartbeats are flowing
5. Go to **Agents** > click **+ New Agent** and confirm the instance dropdown lists all 4

### 4.10 Common Mistakes Checklist

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Wrong Docker network name | Bridge containers can't reach `phoenix-api` | Run `docker network ls`, update `name:` in the compose file to match the actual network |
| Host port collision | `docker compose up` fails with "port already in use" | Ensure each instance has a unique host port (18800, 18801, 18802, 18803) |
| Missing volumes section | Agent data lost on container restart | Add named volumes to the `volumes:` section at the bottom of the compose file |
| `host` set to `localhost` in registration | Phoenix API can't reach the Bridge | Use the Docker service name (`phoenix-bridge-a`) for local instances |
| `port` set to host port (18801) in registration | Phoenix API tries wrong port inside Docker | Always use the container port `18800` in registration, not the host port |
| Forgot to start main stack first | Bridge can't reach `phoenix-api` or `minio` | Run `docker compose up -d` before starting multi-openclaw compose |
| `BRIDGE_TOKEN` mismatch | 401 Unauthorized on all Bridge API calls | Verify the token in `.env` matches what's passed to each Bridge container |

### 4.11 Managing the Multi-Instance Stack

```bash
# Stop all OpenClaw instances (Phoenix stack keeps running)
docker compose -f docker-compose.multi-openclaw.yml down

# Restart a single instance
docker compose -f docker-compose.multi-openclaw.yml restart phoenix-bridge-b

# View logs for a specific instance
docker compose -f docker-compose.multi-openclaw.yml logs phoenix-bridge-c --tail 50 -f

# Scale: add a 5th instance by duplicating a service block with a new name/port,
# then run: docker compose -f docker-compose.multi-openclaw.yml up -d
```

---

## 5. Agent Configuration

### Agent config JSON format

Each agent is defined by a JSON config file in `openclaw/configs/`. Example for a trading agent:

```json
{
  "name": "0DTE SPX Agent",
  "type": "trading",
  "role": "0DTE Options Specialist",
  "model": "gpt-4o",
  "skills": [
    "gex-gamma-flip",
    "moc-imbalance-analyzer",
    "vanna-charm-tracker",
    "0dte-spx-scalp",
    "dynamic-stop-atr"
  ],
  "schedule": { "cron": "0 14 * * 1-5" },
  "config": {
    "instruments": ["SPX", "SPY", "ES"],
    "max_risk_per_trade_pct": 1.0,
    "auto_execute": false,
    "trading_window_start": "14:00",
    "trading_window_end": "16:00"
  }
}
```

Example for a research agent:

```json
{
  "name": "Technical Analyst",
  "type": "technical",
  "role": "Technical Analysis Specialist",
  "model": "gpt-4o",
  "subscribe_to": ["stream:research-signals"],
  "skills": [
    "fibonacci-retracement",
    "vwap-reversion",
    "multi-timeframe-confluence",
    "trend-follower"
  ],
  "schedule": { "cron": "15 7 * * 1-5" },
  "config": {
    "timeframes": ["1m", "5m", "15m", "1h", "4h", "1d"],
    "output_format": "structured_signal",
    "publish_to": "stream:technical-signals"
  }
}
```

### Agent types

| Type | Purpose | Typical Model |
|------|---------|---------------|
| `trading` | Execute trades, manage positions | `gpt-4o` |
| `technical` | Technical analysis, chart patterns | `gpt-4o` or `gpt-4o-mini` |
| `monitoring` | Monitor positions, risk alerts | `gpt-4o-mini` |
| `research` | News, sentiment, fundamental analysis | `gpt-4o` |

### Workspace files (auto-created by Bridge)

When the Bridge creates an agent, it auto-generates these files in the agent's workspace directory (`AGENTS_ROOT/<agent-id>/`):

| File | Purpose |
|------|---------|
| **AGENTS.md** | Agent name and identity |
| **TOOLS.md** | Available tools (read_file, write_file, etc.) |
| **SOUL.md** | Agent's role, personality, and behavioral constraints |
| **HEARTBEAT.md** | Heartbeat interval and scheduled actions |

You can customize these files after creation. The most important one for token optimization is **SOUL.md** — see [Section 6](#6-system-prompts-for-token-safeguarding-and-optimization).

### Deploying an agent via the Bridge API

```bash
curl -X POST http://localhost:18800/agents \
  -H "X-Bridge-Token: $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "SPY Scalper",
    "type": "trading",
    "role": "SPY Day Trading Specialist",
    "config": {
      "instruments": ["SPY"],
      "max_risk_per_trade_pct": 0.5,
      "auto_execute": false
    }
  }'
```

### Skill assignment

Skills are centrally managed in MinIO (`phoenix-skills` bucket) and synced to instances:

```bash
# Trigger skill sync for a specific instance
curl -X POST http://localhost:18800/skills/sync \
  -H "X-Bridge-Token: $BRIDGE_TOKEN"
```

Or from the dashboard: **Agents** > **Skills** > select instance > **Sync Skills**.

---

## 6. System Prompts for Token Safeguarding and Optimization

The **SOUL.md** file in each agent's workspace defines behavior, constraints, and output format. Well-crafted SOUL.md files are critical for:

- Preventing unauthorized actions
- Minimizing token usage (cost optimization)
- Enforcing risk management rules
- Ensuring structured, parseable output

### Token optimization principles

1. **Instruct concise output**: Tell the agent to respond with structured JSON, not prose
2. **Set max token caps**: Specify maximum response length
3. **Use structured formats**: JSON responses are shorter and more parseable than natural language
4. **Batch information**: Ask for all analysis in one call instead of multiple round-trips
5. **Use smaller models for simple tasks**: `gpt-4o-mini` for monitoring, `gpt-4o` for complex analysis

### SOUL.md Template: Trading Agent

```markdown
# Trading Agent — SOUL

## Identity
You are a disciplined day trading agent specializing in {INSTRUMENTS}.
You operate under strict risk management rules. You never deviate from your parameters.

## Output Format
ALWAYS respond in JSON. Never use prose or markdown. Structure:
```json
{
  "action": "BUY|SELL|HOLD|SKIP",
  "instrument": "TICKER",
  "reasoning": "1-2 sentences max",
  "confidence": 0.0-1.0,
  "risk_reward": 0.0,
  "stop_loss": 0.0,
  "take_profit": 0.0,
  "position_size_pct": 0.0
}
```

## Constraints
- NEVER exceed {MAX_RISK_PER_TRADE_PCT}% risk per trade
- NEVER trade outside market hours ({TRADING_WINDOW_START} to {TRADING_WINDOW_END} ET)
- NEVER trade more than {MAX_DAILY_TRADES} times per day
- NEVER hold positions overnight unless explicitly configured
- If confidence < 0.6, action MUST be "SKIP"
- If daily loss exceeds {MAX_DAILY_LOSS_PCT}%, action MUST be "SKIP" for remainder of day

## Token Optimization
- Keep reasoning to 1-2 sentences maximum
- Do not repeat the question or context in your response
- Do not include disclaimers or caveats
- Respond with JSON only, no surrounding text
- Maximum response: 200 tokens

## Human Approval Gate
- All BUY/SELL actions require human approval when auto_execute is false
- Include "requires_approval": true in your response for any trade action

## Circuit Breakers
- If you detect data anomalies (price gaps > 5%, missing data), respond: {"action":"SKIP","reasoning":"Data anomaly detected","circuit_breaker":true}
- If you encounter errors, respond: {"action":"SKIP","reasoning":"Error encountered","error":true}
```

### SOUL.md Template: Research Agent

```markdown
# Research Agent — SOUL

## Identity
You are a financial research analyst. You analyze market data, news, and sentiment
to produce structured research signals. You do not execute trades.

## Output Format
ALWAYS respond in JSON:
```json
{
  "signal_type": "BULLISH|BEARISH|NEUTRAL",
  "ticker": "SYMBOL",
  "summary": "2-3 sentences max",
  "key_factors": ["factor1", "factor2", "factor3"],
  "confidence": 0.0-1.0,
  "timeframe": "intraday|swing|position",
  "data_sources": ["source1", "source2"]
}
```

## Constraints
- Analyze only the instruments in your assigned watchlist
- Do not make trade recommendations; only produce signals
- Cite specific data points, not vague assertions
- If data is insufficient, set confidence below 0.3 and note in summary

## Token Optimization
- Maximum 3 key factors per signal
- Summary must be 2-3 sentences, not paragraphs
- Do not repeat raw data in the response
- Maximum response: 250 tokens
- Batch multiple tickers in a single response as a JSON array
```

### SOUL.md Template: Monitoring Agent

```markdown
# Monitoring Agent — SOUL

## Identity
You are a position monitoring agent. You watch open positions and alert on risk events.
You never initiate trades. You only monitor and report.

## Output Format
ALWAYS respond in JSON:
```json
{
  "alert_type": "NONE|WARNING|CRITICAL",
  "positions_checked": 0,
  "alerts": [
    {
      "ticker": "SYMBOL",
      "alert": "description",
      "severity": "low|medium|high|critical",
      "recommended_action": "hold|reduce|close"
    }
  ],
  "portfolio_risk_pct": 0.0
}
```

## Constraints
- Check all open positions every heartbeat cycle
- CRITICAL alert if any single position exceeds {MAX_POSITION_PCT}% of portfolio
- CRITICAL alert if total portfolio drawdown exceeds {MAX_DRAWDOWN_PCT}%
- WARNING if any position is down more than {STOP_LOSS_PCT}%
- Do not recommend actions beyond hold/reduce/close

## Token Optimization
- If no alerts, respond: {"alert_type":"NONE","positions_checked":N,"alerts":[],"portfolio_risk_pct":X}
- Keep alert descriptions to 10 words or fewer
- Maximum response: 150 tokens
```

### Applying SOUL.md to an agent

After creating an agent via the Bridge, write the SOUL.md:

```bash
# The Bridge auto-creates a basic SOUL.md. Override it:
docker exec phoenix-bridge sh -c 'cat > /data/agents/MY_AGENT_ID/SOUL.md << "EOF"
# (paste your SOUL.md content here)
EOF'
```

Or update via the Bridge API:

```bash
curl -X PUT http://localhost:18800/agents/MY_AGENT_ID \
  -H "X-Bridge-Token: $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "soul": "# Trading Agent — SOUL\n\n## Identity\nYou are a disciplined day trading agent...",
    "tools": "read_file\nwrite_file\napi_call"
  }'
```

---

## 7. Configuring the Bridge Connection

This section explains **how the Bridge works**, **what configuration values go where**, and provides separate step-by-step flows for local (same-machine Docker) and remote (VPS over WireGuard) deployments.

### 7.1 Part A -- How the Bridge Works

The Bridge Service is a lightweight FastAPI sidecar that sits alongside each OpenClaw instance. It is the **only point of contact** between the Phoenix control plane and the agent runtime.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          YOUR MACHINE / VPS                              │
│                                                                          │
│  ┌─────────────┐    HTTP     ┌─────────────┐    HTTP     ┌────────────┐ │
│  │  Phoenix    │ ──────────▶ │  Phoenix    │ ──────────▶ │  Bridge    │ │
│  │  Dashboard  │             │  API        │             │  Service   │ │
│  │  (:3000)    │             │  (:8011)    │             │  (:18800)  │ │
│  └─────────────┘             └─────────────┘             └─────┬──────┘ │
│                                                                │        │
│                                                          Agent CRUD     │
│                                                          Heartbeat      │
│                                                          Skill Sync     │
│                                                                │        │
│                                                          ┌─────▼──────┐ │
│                                                          │  OpenClaw  │ │
│                                                          │  Runtime   │ │
│                                                          │  (Agents)  │ │
│                                                          └────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

**Data flow:**

1. **Dashboard** sends user actions (create agent, pause, deploy pipeline) to the **Phoenix API** via REST.
2. **Phoenix API** looks up the target instance's `host` and `port` from the database and forwards the request to the **Bridge Service** at `http://{host}:{port}/agents/...`, authenticated with the `X-Bridge-Token` header.
3. **Bridge Service** executes the operation on the local OpenClaw runtime (creates agent workspace, updates config, collects heartbeat data).
4. **Bridge Service** periodically sends heartbeat data back to the Phoenix API at `POST /api/v2/instances/{id}/heartbeat`.

**Authentication:** Every request between the Phoenix API and the Bridge carries the `X-Bridge-Token` header. This token must be identical on both sides. If they don't match, the Bridge returns 401 Unauthorized.

### 7.2 Part B -- Configuration Values: What Comes From Where

This is the most critical part. Each variable has a specific source and destination:

| Variable | Who Sets It | Where It Goes | Value for Local Docker | Value for Remote VPS |
|----------|-------------|---------------|----------------------|---------------------|
| `BRIDGE_TOKEN` | You generate it (`openssl rand -hex 32`) | Bridge container env AND Phoenix API `.env` | Same value on both sides | Same value on both sides |
| `CONTROL_PLANE_URL` | You set it in the Bridge's environment | Bridge container env | `http://phoenix-api:8011` (Docker DNS) | `http://10.0.1.1:8011` (WireGuard IP of hub) |
| `INSTANCE_NAME` | You choose a descriptive name | Bridge container env | e.g., `OpenClaw-Paper-Trading` | e.g., `OpenClaw-VPS-Node-A` |
| `NODE_TYPE` | You set it | Bridge container env | `local` | `vps` |
| `MINIO_ENDPOINT` | You set it in the Bridge's environment | Bridge container env | `http://minio:9000` (Docker DNS) | `http://10.0.1.1:9000` (WireGuard IP of hub) |
| `MINIO_ACCESS_KEY` | From your MinIO config | Bridge container env | `minioadmin` (default) | Same as control plane |
| `MINIO_SECRET_KEY` | From your MinIO config | Bridge container env | `minioadmin` (default) | Same as control plane |
| `host` (in registration) | Set during instance registration (auto or manual) | Phoenix API database | Docker service name: `phoenix-bridge-a` | WireGuard IP: `10.0.1.10` |
| `port` (in registration) | Set during instance registration | Phoenix API database | `18800` (always the container port) | `18800` (always the container port) |

> **The most common confusion:** The `host` in the registration payload is how the **Phoenix API reaches the Bridge**, not how you reach it from your terminal. Inside Docker, services find each other by name. From a remote VPS, services find each other by WireGuard IP.

### 7.3 Part C -- Local Bridge Configuration (Same Machine)

When the Bridge runs on the same machine as the Phoenix stack (the setup from Sections 3 and 4), connectivity works via Docker networking:

```
┌───────────────────────────────────────────────────────┐
│              Docker Network: projectphoneix_default     │
│                                                        │
│  phoenix-api ◄──── phoenix-bridge-a (OpenClaw-Paper)   │
│  (8011)      ◄──── phoenix-bridge-b (OpenClaw-Research)│
│              ◄──── phoenix-bridge-c (OpenClaw-Backtest)│
│  minio       ◄──── phoenix-bridge-d (OpenClaw-Live)   │
│  (9000)                                                │
│                                                        │
│  All services resolve each other by name via Docker DNS│
└───────────────────────────────────────────────────────┘
```

**What makes it work:**

1. **Same Docker network**: Both the main compose and the multi-openclaw compose reference the same network (`projectphoneix_default`).
2. **Docker DNS**: Inside the network, `phoenix-api` resolves to the API container's IP. `phoenix-bridge-a` resolves to that Bridge container's IP. No explicit IPs needed.
3. **No WireGuard**: Everything is on one machine, so no tunnel is needed.
4. **`CONTROL_PLANE_URL`** = `http://phoenix-api:8011` (the Docker service name).
5. **`MINIO_ENDPOINT`** = `http://minio:9000` (the Docker service name).
6. **`host` in registration** = the Docker service name of the Bridge container (e.g., `phoenix-bridge-a`).

**Verification:**

```bash
# From inside the Bridge container, verify it can reach the API
docker exec phoenix-bridge-a curl -s http://phoenix-api:8011/health
# Expected: {"status":"ok","service":"phoenix-api","version":"..."}

# From inside the Bridge container, verify it can reach MinIO
docker exec phoenix-bridge-a curl -s http://minio:9000/minio/health/live
# Expected: HTTP 200
```

### 7.4 Part D -- Remote Bridge Configuration (VPS over WireGuard)

When the Bridge runs on a **different machine** (a VPS, a laptop, a separate datacenter), it cannot use Docker DNS to reach the Phoenix API. Instead, both machines must be connected via a WireGuard VPN tunnel (see [Section 8](#8-wireguard-setup-for-remote-nodes) for the WireGuard setup).

```
Machine A (Control Plane)              Machine B (Remote Node)
WireGuard IP: 10.0.1.1                WireGuard IP: 10.0.1.10
┌──────────────────────┐              ┌──────────────────────┐
│ Phoenix API (:8011)  │◄────────────▶│ Bridge (:18800)      │
│ MinIO (:9000)        │  WireGuard   │ OpenClaw Runtime     │
│ Dashboard (:3000)    │  tunnel      │ Agent workspaces     │
│ PostgreSQL (:5432)   │              │                      │
│ Redis (:6379)        │              │                      │
└──────────────────────┘              └──────────────────────┘
```

**Step-by-step:**

**Step 1: Complete WireGuard setup** (see [Section 8](#8-wireguard-setup-for-remote-nodes)) so that:
- Control plane (hub) is at `10.0.1.1`
- Remote node is at `10.0.1.10` (or your chosen IP)
- Both machines can `ping` each other over the WireGuard interface

**Step 2: Expose Phoenix API and MinIO on the WireGuard interface**

On the control plane machine, ensure the Phoenix API and MinIO are listening on the WireGuard IP (or `0.0.0.0`). By default, Docker binds to `0.0.0.0`, so they should be reachable at `10.0.1.1:8011` and `10.0.1.1:9000` through the tunnel.

Verify from the remote node:

```bash
# From the remote VPS, test connectivity
curl http://10.0.1.1:8011/health
# Expected: {"status":"ok","service":"phoenix-api","version":"..."}

curl http://10.0.1.1:9000/minio/health/live
# Expected: HTTP 200
```

**Step 3: Set Bridge environment variables on the remote node**

Create a `.env` file on the remote VPS:

```bash
BRIDGE_TOKEN=<SAME_TOKEN_AS_CONTROL_PLANE>
MINIO_ENDPOINT=http://10.0.1.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
CONTROL_PLANE_URL=http://10.0.1.1:8011
INSTANCE_NAME=OpenClaw-VPS-Node-A
NODE_TYPE=vps
BRIDGE_PORT=18800
```

**Step 4: Run the Bridge on the remote node**

You can run the Bridge directly with Docker:

```bash
docker run -d \
  --name phoenix-bridge-remote \
  -p 18800:18800 \
  -e BRIDGE_TOKEN=$BRIDGE_TOKEN \
  -e MINIO_ENDPOINT=$MINIO_ENDPOINT \
  -e MINIO_ACCESS_KEY=$MINIO_ACCESS_KEY \
  -e MINIO_SECRET_KEY=$MINIO_SECRET_KEY \
  -e CONTROL_PLANE_URL=$CONTROL_PLANE_URL \
  -e INSTANCE_NAME=$INSTANCE_NAME \
  -e NODE_TYPE=$NODE_TYPE \
  -e AGENTS_ROOT=/data/agents \
  -v bridge_remote_agents:/data/agents \
  --restart unless-stopped \
  <your-bridge-image>
```

Or create a minimal `docker-compose.yml` on the remote node:

```yaml
version: "3.9"
services:
  phoenix-bridge:
    build:
      context: .
      dockerfile: openclaw/bridge/Dockerfile
    ports:
      - "18800:18800"
    env_file:
      - .env
    environment:
      - AGENTS_ROOT=/data/agents
    volumes:
      - bridge_agents:/data/agents
    restart: unless-stopped

volumes:
  bridge_agents:
```

**Step 5: Register the remote instance with the control plane**

From the control plane machine (or anywhere that can reach port 8011):

```bash
TOKEN=$(curl -s -X POST http://localhost:8011/api/v2/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@phoenix.local","password":"admin"}' \
  | jq -r '.access_token')

curl -X POST http://localhost:8011/api/v2/instances \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "OpenClaw-VPS-Node-A",
    "host": "10.0.1.10",
    "port": 18800,
    "role": "general",
    "node_type": "vps",
    "capabilities": {
      "paper_trading": true,
      "max_agents": 10
    }
  }'
```

> **Critical:** The `host` is the **WireGuard IP** of the remote node (`10.0.1.10`), NOT the public IP or `localhost`. The Phoenix API will use this address to reach the Bridge through the WireGuard tunnel.

**Step 6: Firewall the Bridge port**

On the remote node, only allow Bridge traffic from the WireGuard subnet:

```bash
sudo ufw allow from 10.0.1.0/24 to any port 18800
sudo ufw deny 18800
```

### 7.5 Part E -- Verifying the Bridge Connection

Whether local or remote, verify the full chain:

**1. Bridge health (from the host machine or via WireGuard):**

```bash
# Local
curl http://localhost:18800/health

# Remote (from control plane, via WireGuard)
curl http://10.0.1.10:18800/health
```

**2. Authenticated heartbeat:**

```bash
curl -H "X-Bridge-Token: $BRIDGE_TOKEN" http://localhost:18800/heartbeat
# Expected: {"agents":[...],"count":N}
```

**3. Agent list:**

```bash
curl -H "X-Bridge-Token: $BRIDGE_TOKEN" http://localhost:18800/agents
# Expected: {"agents":[...]}
```

**4. Check Bridge container logs for registration:**

```bash
# Local
docker compose logs phoenix-bridge-a --tail 20

# Remote
docker logs phoenix-bridge-remote --tail 20
# Look for: "Registered with control plane: 201"
# Or: "Registration returned 409" (already registered -- this is OK)
```

**5. Confirm in the dashboard:**

1. Open `http://localhost:3000`
2. Navigate to **Agents** > **Network**
3. All registered instances should appear as nodes
4. Status colors: Green = ONLINE, Yellow = DEGRADED, Red = OFFLINE
5. Click any instance node to see its details (host, port, agent count)

**6. End-to-end test -- create a test agent via the Bridge:**

```bash
curl -X POST http://localhost:18800/agents \
  -H "X-Bridge-Token: $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "test-agent", "type": "monitoring"}'
# Expected: 201 with {"id":"test-agent","name":"test-agent","status":"CREATED"}

# Verify it appears in the agent list
curl -H "X-Bridge-Token: $BRIDGE_TOKEN" http://localhost:18800/agents
# Expected: {"agents":[{"id":"test-agent",...}]}

# Clean up
curl -X DELETE http://localhost:18800/agents/test-agent \
  -H "X-Bridge-Token: $BRIDGE_TOKEN"
# Expected: 204 No Content
```

### 7.6 Summary: Local vs Remote Configuration At a Glance

| Setting | Local (same machine) | Remote (VPS via WireGuard) |
|---------|---------------------|---------------------------|
| Docker network | Shared `projectphoneix_default` | Standalone (no shared network) |
| `CONTROL_PLANE_URL` | `http://phoenix-api:8011` | `http://10.0.1.1:8011` |
| `MINIO_ENDPOINT` | `http://minio:9000` | `http://10.0.1.1:9000` |
| `NODE_TYPE` | `local` | `vps` |
| `host` in registration | Docker service name (`phoenix-bridge-a`) | WireGuard IP (`10.0.1.10`) |
| `port` in registration | `18800` (container port) | `18800` (container port) |
| WireGuard required | No | Yes |
| Firewall | Docker handles isolation | `ufw allow from 10.0.1.0/24 to any port 18800` |

---

## 8. WireGuard Setup for Remote Nodes

This section covers setting up a WireGuard VPN tunnel between the Phoenix control plane and one or more remote machines running OpenClaw Bridge instances. **Skip this section if all your instances run on the same machine as the Phoenix stack** (covered in Sections 3-4).

### 8.1 When You Need WireGuard

You need WireGuard when the Bridge runs on a **different physical/virtual machine** than the Phoenix API:

| Scenario | WireGuard Needed? |
|----------|-------------------|
| All instances on one machine (Docker multi-instance) | No |
| OpenClaw on a remote VPS (Hetzner, DigitalOcean, AWS, etc.) | **Yes** |
| OpenClaw on a laptop at home, Phoenix API on a VPS | **Yes** |
| OpenClaw in a different datacenter | **Yes** |
| Phoenix API and OpenClaw on the same LAN | Optional (can use LAN IPs directly) |

### 8.2 What You Need Before Starting

**From the control plane machine (hub):**

| Item | How to get it | Example |
|------|---------------|---------|
| Public IP address | `curl ifconfig.me` | `203.0.113.50` |
| SSH access | You should already have this | `ssh root@203.0.113.50` |
| Open UDP port 51820 | Cloud provider firewall / `ufw allow 51820/udp` | -- |
| WireGuard installed | See Step 1 below | -- |
| WireGuard private/public key pair | See Step 2 below | -- |

**From each remote node:**

| Item | How to get it | Example |
|------|---------------|---------|
| SSH access to the node | You should already have this | `ssh root@198.51.100.10` |
| WireGuard installed | See Step 1 below | -- |
| WireGuard private/public key pair | See Step 2 below | -- |
| Docker installed | For running the Bridge | `docker --version` |

**IP allocation plan** (decide before starting):

| Machine | Role | WireGuard IP |
|---------|------|-------------|
| Control Plane (hub) | Phoenix API, Dashboard, MinIO | `10.0.1.1` |
| Node A | Remote VPS running Bridge | `10.0.1.10` |
| Node B | Laptop behind NAT | `10.0.1.11` |
| Node C | Another laptop | `10.0.1.12` |

### 8.3 Network Topology

```
Hub-and-spoke model — all nodes connect to the hub, not to each other:

                   ┌──────────────────────────┐
                   │  Control Plane (Hub)      │
                   │  Public IP: 203.0.113.50  │
                   │  WireGuard: 10.0.1.1/24   │
                   │  UDP port: 51820          │
                   │                           │
                   │  Services:                │
                   │    Phoenix API (:8011)     │
                   │    MinIO (:9000)           │
                   │    Dashboard (:3000)       │
                   └──────┬────────────────────┘
                          │  WireGuard tunnel (UDP 51820)
           ┌──────────────┼──────────────┐
           │              │              │
           ▼              ▼              ▼
    ┌────────────┐  ┌───────────┐  ┌───────────┐
    │ Node A     │  │ Node B    │  │ Node C    │
    │ 10.0.1.10  │  │ 10.0.1.11 │  │ 10.0.1.12 │
    │ VPS        │  │ Laptop    │  │ Laptop    │
    │ Bridge     │  │ Bridge    │  │ Bridge    │
    │ :18800     │  │ :18800    │  │ :18800    │
    └────────────┘  └───────────┘  └───────────┘
```

### 8.4 Step 1 -- Install WireGuard

**On every machine** (hub and all nodes):

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y wireguard

# macOS
brew install wireguard-tools

# CentOS / RHEL
sudo yum install -y epel-release
sudo yum install -y wireguard-tools
```

### 8.5 Step 2 -- Generate Key Pairs

Run this on **every machine** (hub and each node):

```bash
# Generate a private key and derive the public key
wg genkey | tee /etc/wireguard/privatekey | wg pubkey > /etc/wireguard/publickey

# Set secure permissions
chmod 600 /etc/wireguard/privatekey

# View the keys (you'll need to copy these into configs)
cat /etc/wireguard/privatekey   # Keep this SECRET
cat /etc/wireguard/publickey    # Share this with the other side
```

After running this on all machines, you should have:

| Machine | Private Key (secret) | Public Key (share) |
|---------|---------------------|--------------------|
| Hub | `<HUB_PRIVATE_KEY>` | `<HUB_PUBLIC_KEY>` |
| Node A | `<NODE_A_PRIVATE_KEY>` | `<NODE_A_PUBLIC_KEY>` |
| Node B | `<NODE_B_PRIVATE_KEY>` | `<NODE_B_PUBLIC_KEY>` |

### 8.6 Step 3 -- Configure the Hub (Control Plane)

On the control plane machine, create `/etc/wireguard/wg0.conf`:

```ini
[Interface]
PrivateKey = <HUB_PRIVATE_KEY>
Address = 10.0.1.1/24
ListenPort = 51820

# Forward traffic between peers (enable if nodes need to talk to each other)
# PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
# PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# Node A — Remote VPS
[Peer]
PublicKey = <NODE_A_PUBLIC_KEY>
AllowedIPs = 10.0.1.10/32

# Node B — Laptop behind NAT
[Peer]
PublicKey = <NODE_B_PUBLIC_KEY>
AllowedIPs = 10.0.1.11/32

# Node C — Another laptop
[Peer]
PublicKey = <NODE_C_PUBLIC_KEY>
AllowedIPs = 10.0.1.12/32
```

Open the WireGuard port in the firewall:

```bash
sudo ufw allow 51820/udp
```

### 8.7 Step 4 -- Configure Each Remote Node

On **Node A** (remote VPS), create `/etc/wireguard/wg0.conf`:

```ini
[Interface]
PrivateKey = <NODE_A_PRIVATE_KEY>
Address = 10.0.1.10/24

[Peer]
PublicKey = <HUB_PUBLIC_KEY>
Endpoint = 203.0.113.50:51820
AllowedIPs = 10.0.1.0/24
PersistentKeepalive = 25
```

On **Node B** (laptop behind NAT), create `/etc/wireguard/wg0.conf`:

```ini
[Interface]
PrivateKey = <NODE_B_PRIVATE_KEY>
Address = 10.0.1.11/24

[Peer]
PublicKey = <HUB_PUBLIC_KEY>
Endpoint = 203.0.113.50:51820
AllowedIPs = 10.0.1.0/24
PersistentKeepalive = 25
```

> **`PersistentKeepalive = 25`**: Essential for machines behind NAT (laptops, home networks). Sends a keepalive packet every 25 seconds to keep the tunnel open through the NAT. Without it, the tunnel will drop after a few minutes of inactivity.
>
> **`Endpoint`**: The public IP of the **hub** machine plus port 51820. Nodes behind NAT don't need a static public IP -- the hub discovers their address from incoming packets.

### 8.8 Step 5 -- Start WireGuard and Verify

On **every machine** (hub first, then nodes):

```bash
# Start the tunnel
sudo wg-quick up wg0

# Verify the interface is up
sudo wg show
# Should show: interface wg0, listening port, peer info, latest handshake
```

**Test connectivity from each node to the hub:**

```bash
# From Node A
ping -c 3 10.0.1.1
# Expected: 3 packets received

# From Node A, verify Phoenix API is reachable through the tunnel
curl http://10.0.1.1:8011/health
# Expected: {"status":"ok","service":"phoenix-api",...}
```

**Test connectivity from the hub to each node:**

```bash
# From the hub
ping -c 3 10.0.1.10
# Expected: 3 packets received (only works after the node has connected)
```

### 8.9 Step 6 -- Map WireGuard IPs to Bridge Configuration

Now that the tunnel is active, configure the Bridge on each remote node. Here is the complete IP-to-config mapping:

| Config Variable | Where It's Set | What IP to Use | Example |
|----------------|----------------|----------------|---------|
| `CONTROL_PLANE_URL` | Bridge `.env` on the remote node | Hub's WireGuard IP | `http://10.0.1.1:8011` |
| `MINIO_ENDPOINT` | Bridge `.env` on the remote node | Hub's WireGuard IP | `http://10.0.1.1:9000` |
| `host` in registration | `POST /api/v2/instances` on the hub | Node's WireGuard IP | `10.0.1.10` |
| `port` in registration | `POST /api/v2/instances` on the hub | Container port (always 18800) | `18800` |

**Complete `.env` for a remote Bridge (Node A):**

```bash
BRIDGE_TOKEN=<SAME_TOKEN_AS_CONTROL_PLANE>
CONTROL_PLANE_URL=http://10.0.1.1:8011
MINIO_ENDPOINT=http://10.0.1.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
INSTANCE_NAME=OpenClaw-VPS-Node-A
NODE_TYPE=vps
BRIDGE_PORT=18800
```

**Register the remote instance (run from the hub or any machine):**

```bash
TOKEN=$(curl -s -X POST http://localhost:8011/api/v2/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@phoenix.local","password":"admin"}' \
  | jq -r '.access_token')

curl -X POST http://localhost:8011/api/v2/instances \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "OpenClaw-VPS-Node-A",
    "host": "10.0.1.10",
    "port": 18800,
    "role": "general",
    "node_type": "vps",
    "capabilities": {"paper_trading": true, "max_agents": 10}
  }'
```

### 8.10 Step 7 -- Firewall the Bridge Port

On each remote node, restrict Bridge traffic to only the WireGuard subnet:

```bash
# Allow Bridge traffic only from WireGuard peers
sudo ufw allow from 10.0.1.0/24 to any port 18800

# Block Bridge traffic from all other sources
sudo ufw deny 18800

# Verify
sudo ufw status | grep 18800
```

### 8.11 Step 8 -- Enable WireGuard Auto-Start

Ensure the tunnel comes back up after a reboot:

```bash
# On every machine (hub and nodes)
sudo systemctl enable wg-quick@wg0

# Verify
sudo systemctl status wg-quick@wg0
```

### 8.12 Step 9 -- Verify the Full Chain

From the control plane machine, verify the remote Bridge is reachable through the tunnel:

```bash
# Health check (via WireGuard IP)
curl http://10.0.1.10:18800/health
# Expected: {"status":"ready","service":"phoenix-bridge"}

# Heartbeat (via WireGuard IP)
curl -H "X-Bridge-Token: $BRIDGE_TOKEN" http://10.0.1.10:18800/heartbeat
# Expected: {"agents":[],"count":0}
```

Open the dashboard at `http://localhost:3000` > **Agents** > **Network** and confirm the remote instance appears as an ONLINE node.

### 8.13 Troubleshooting WireGuard

| Problem | Diagnostic | Fix |
|---------|------------|-----|
| `ping 10.0.1.1` times out from node | `sudo wg show` -- check if latest handshake is recent | Verify `Endpoint` IP and port are correct; check hub firewall allows UDP 51820 |
| Handshake never completes | `sudo wg show` -- check if peer shows | Verify public keys are correct on both sides (most common mistake) |
| Tunnel works but `curl 10.0.1.1:8011` fails | Hub firewall may block internal traffic | `sudo ufw allow from 10.0.1.0/24` on the hub |
| Tunnel drops after inactivity | Missing `PersistentKeepalive` | Add `PersistentKeepalive = 25` to the node config |
| Bridge registers but shows OFFLINE in dashboard | Hub can't reach the Bridge back | Verify `host` in registration is the node's WireGuard IP, and port 18800 is open on the node |

---

## 9. Security Best Practices

### Token management

| Practice | How |
|----------|-----|
| **Strong tokens** | `openssl rand -hex 32` — minimum 64 hex characters |
| **Unique per environment** | Different `BRIDGE_TOKEN` for dev, staging, production |
| **Never commit tokens** | Use `.env` files (gitignored) or secret managers |
| **Rotate periodically** | Change tokens quarterly; update all Bridge instances and the `.env` simultaneously |

### Network security

| Practice | How |
|----------|-----|
| **WireGuard-only** | Never expose Bridge ports (18800) to the public internet |
| **Firewall rules** | `ufw allow from 10.0.1.0/24 to any port 18800` |
| **Docker network isolation** | Use internal Docker networks; only expose via nginx reverse proxy |
| **TLS in production** | Use nginx with TLS termination for the dashboard and API |

### Token rotation procedure

1. Generate a new token: `openssl rand -hex 32`
2. Update `.env` on the control plane with the new `BRIDGE_TOKEN`
3. Update `.env` on every Bridge node
4. Restart all Bridge instances: `docker compose restart phoenix-bridge`
5. Restart the control plane API: `docker compose restart phoenix-api`
6. Verify all instances show ONLINE in the dashboard

### Agent security

- Always set `auto_execute: false` for new agents (require human approval)
- Use `max_risk_per_trade_pct` and `max_daily_loss_pct` in agent configs
- Monitor the Dev Sprint Board for agent errors
- Review agent logs before promoting from paper to live trading

---

## 10. Troubleshooting

### Bridge health check fails

```bash
curl http://localhost:18800/health
# If connection refused:
docker compose logs phoenix-bridge --tail 50
```

**Common causes:**
- Container not running: `docker compose ps` — check if bridge is up
- Port conflict: Another service using 18800. Change the host port mapping.
- Build failure: `docker compose build phoenix-bridge` to rebuild

### Registration fails (409 Conflict)

```
Registration returned 409
```

This means the instance name is already registered. Either:
- Use a different `INSTANCE_NAME`
- Delete the existing instance via the API: `DELETE /api/v2/instances/{id}`

### Registration fails (network unreachable)

```
Registration attempt failed: Connection refused
```

**Causes:**
- `CONTROL_PLANE_URL` is wrong. For Docker: `http://phoenix-api:8011`. For WireGuard: `http://10.0.1.1:8011`.
- Phoenix API is not running: `docker compose ps phoenix-api`
- Docker network mismatch: Bridge must be on the same network as `phoenix-api`

### Heartbeat timeouts (instance shows OFFLINE)

The control plane marks an instance OFFLINE after 3 missed heartbeats (3 minutes).

**Causes:**
- Bridge container crashed: `docker compose logs phoenix-bridge`
- WireGuard tunnel dropped: `sudo wg show` — check handshake timestamps
- Bridge token mismatch: Verify `BRIDGE_TOKEN` matches on both sides
- High CPU/memory: Bridge starved of resources. Increase limits.

### Agent creation fails

```bash
curl -X POST http://localhost:18800/agents \
  -H "X-Bridge-Token: $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"test","type":"trading"}'
```

If 401: Token mismatch. Check `BRIDGE_TOKEN` value.
If 500: Check Bridge logs — likely disk or permission issue with `AGENTS_ROOT`.

### Skills not syncing

```bash
curl -X POST http://localhost:18800/skills/sync \
  -H "X-Bridge-Token: $BRIDGE_TOKEN"
```

If it fails:
- Check `MINIO_ENDPOINT` is reachable from the Bridge container
- Verify `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY`
- Ensure the `phoenix-skills` bucket exists in MinIO

### Common environment variable mistakes

| Mistake | Fix |
|---------|-----|
| `BRIDGE_TOKEN=change-me` | Generate a real token with `openssl rand -hex 32` |
| `MINIO_ENDPOINT=localhost:9000` | Use `http://minio:9000` in Docker |
| `CONTROL_PLANE_URL=localhost:8011` | Use `http://phoenix-api:8011` in Docker |
| Missing `AGENTS_ROOT` | Set to `/data/agents` and mount a volume |
| `NODE_TYPE` not set | Defaults to `vps`; set to `local` for laptops |

---

## Quick Reference: Environment Variables

> **Note:** The project's `.env.example` does not include any Bridge/OpenClaw variables. You must manually add the Bridge block below to your `.env` file. See [Section 3, Step 2](#step-2-add-bridge-environment-variables-to-env) for the full `.env` block to append.

| Variable | Service | Default | Required | Description |
|----------|---------|---------|----------|-------------|
| `BRIDGE_TOKEN` | Bridge, API | `change-me` | **Yes** | Shared auth token for `X-Bridge-Token` header. Generate with `openssl rand -hex 32`. |
| `AGENTS_ROOT` | Bridge | `/tmp/phoenix-bridge-agents` | No | Agent workspace directory inside the container. Set to `/data/agents` and mount a volume. |
| `MINIO_ENDPOINT` | Bridge | `localhost:9000` | **Yes** | MinIO address for skill sync. Local: `http://minio:9000`. Remote: `http://<wireguard-ip>:9000`. |
| `MINIO_ACCESS_KEY` | Bridge | (empty) | **Yes** | MinIO username. Passed as `MINIO_ROOT_USER` in the main compose. |
| `MINIO_SECRET_KEY` | Bridge | (empty) | **Yes** | MinIO password. Passed as `MINIO_ROOT_PASSWORD` in the main compose. |
| `MINIO_BUCKET_SKILLS` | Bridge | `phoenix-skills` | No | MinIO bucket name for agent skills. |
| `MINIO_USE_SSL` | Bridge | `false` | No | Enable TLS for MinIO connections. |
| `CONTROL_PLANE_URL` | Bridge | `http://phoenix-api:8011` | **Yes** | Phoenix API URL for auto-registration. Local: Docker service name. Remote: WireGuard IP. |
| `INSTANCE_NAME` | Bridge | hostname | **Yes** | Display name in the dashboard. Must be unique across all instances. |
| `BRIDGE_PORT` | Bridge | `18800` | No | TCP port uvicorn binds to inside the container. |
| `NODE_TYPE` | Bridge | `vps` | **Yes** | `local` for same-machine Docker, `vps` for remote nodes. |
