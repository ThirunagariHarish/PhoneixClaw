# Deploying PhoenixTrade to Hostinger VPS with Coolify

Step-by-step guide to deploy the full PhoenixTrade platform on a Hostinger VPS using Coolify.

---

## Prerequisites

| Requirement | Details |
|---|---|
| Hostinger VPS | KVM 2+ recommended (2 vCPU, 8 GB RAM, 100 GB NVMe) |
| Domain name | Point an A record to your VPS IP (e.g. `trade.yourdomain.com`) |
| GitHub repo | This project pushed to a GitHub repository (public or private) |
| Coolify installed | Pre-installed on Hostinger "Ubuntu 24.04 with Coolify" template |

### Minimum VPS specs

The full stack runs 13 containers. Recommended: **8 GB RAM** (4 GB is tight).

| Component | Memory |
|---|---|
| Kafka | ~1 GB |
| PostgreSQL | ~512 MB |
| Redis | ~192 MB |
| 10 Python services | ~2.5 GB total |
| Dashboard (Nginx) | ~128 MB |
| OS + Coolify overhead | ~2 GB |
| **Total** | **~6.3 GB** |

---

## Step 1: Set Up Your Hostinger VPS

1. Log in to [Hostinger hPanel](https://hpanel.hostinger.com)
2. Go to **VPS** → Select your server
3. If Coolify is not installed:
   - Go to **OS & Panel** → **Operating System**
   - Select **Ubuntu 24.04 with Coolify**
   - Click **Change OS** (this wipes the VPS)
4. Note your **VPS IP address**

---

## Step 2: Point Your Domain

In your domain DNS settings, create:

```
A  trade.yourdomain.com  →  YOUR_VPS_IP
```

Wait for DNS propagation (~5 minutes for Hostinger DNS, up to 24 hours elsewhere).

---

## Step 3: Access Coolify Dashboard

1. Open your browser: `http://YOUR_VPS_IP:8000`
2. Create your admin account on first visit
3. Complete the onboarding wizard:
   - Select **Localhost** as the server (deploys on this VPS)
   - Skip cloud provider setup

---

## Step 4: Connect Your GitHub Repository

### Option A: Public Repository
No setup needed — you'll paste the URL directly when creating the resource.

### Option B: Private Repository
1. In Coolify, go to **Sources** → **Add GitHub App**
2. Follow the OAuth flow to authorize Coolify
3. Select which repositories to grant access to

---

## Step 5: Create the Project in Coolify

1. Go to **Projects** → **Add Project**
2. Name it `PhoenixTrade`
3. Click into the **Production** environment
4. Click **Add New Resource**

---

## Step 6: Deploy via Docker Compose

1. Select **Public Repository** (or GitHub App if private)
2. Paste your repository URL:
   ```
   https://github.com/YOUR_USERNAME/discordmessages2trade
   ```
3. **Build Pack**: Select **Docker Compose** (not Nixpacks)
4. **Docker Compose Location**: Set to:
   ```
   /docker-compose.coolify.yml
   ```
5. **Base Directory**: Leave as `/`
6. **Branch**: `main`
7. Click **Continue**

---

## Step 7: Configure Environment Variables

Before deploying, Coolify will detect all `${VAR}` references from the compose file and show them in the **Environment Variables** tab.

### Required Variables (must set before first deploy)

| Variable | How to generate |
|---|---|
| `POSTGRES_PASSWORD` | Any strong password (e.g. `openssl rand -base64 24`) |
| `JWT_SECRET_KEY` | `openssl rand -hex 32` |
| `CREDENTIAL_ENCRYPTION_KEY` | `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

### Optional Variables (have defaults)

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` | `phoenixtrader` | DB username |
| `POSTGRES_DB` | `phoenixtrader` | DB name |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Token TTL |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token TTL |
| `APPROVAL_MODE` | `auto` | `auto` or `manual` |
| `ENABLE_TRADING` | `true` | Master kill switch |
| `DRY_RUN_MODE` | `false` | Simulate trades |
| `BUFFER_PERCENTAGE` | `0.15` | Price buffer |
| `MAX_POSITION_SIZE` | `10` | Max contracts per trade |
| `MAX_DAILY_LOSS` | `1000.0` | Daily loss limit ($) |
| `DEFAULT_PROFIT_TARGET` | `0.30` | Take profit at 30% |
| `DEFAULT_STOP_LOSS` | `0.20` | Stop loss at 20% |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` |

### Discord (set when ready to connect)

| Variable | Description |
|---|---|
| `DISCORD_BOT_TOKEN` | From Discord Developer Portal |
| `DISCORD_TARGET_CHANNELS` | Comma-separated channel IDs |

> You can also configure Discord sources and broker credentials through the dashboard UI after deployment.

A reference file is available at `.env.coolify.example`.

---

## Step 8: Assign a Domain to the Dashboard

1. In Coolify, go to your resource's **Settings**
2. Under the `dashboard-ui` service, set the domain:
   ```
   https://trade.yourdomain.com
   ```
3. Coolify will automatically:
   - Provision a Let's Encrypt SSL certificate
   - Configure Traefik to route traffic to the dashboard on port 80

> All other services (Kafka, Postgres, Redis, Python microservices) remain **private** — they communicate only on the internal Docker network.

---

## Step 9: Deploy

1. Click **Deploy** in Coolify
2. Watch the build logs — first deploy takes 5–10 minutes (Docker image builds)
3. Subsequent deploys are faster (layer caching)

### What happens during deployment

1. Docker builds all 13 service images
2. Infrastructure starts first (Kafka, PostgreSQL, Redis)
3. `init` container waits for PostgreSQL, creates database tables, then exits
4. All application services start after `init` succeeds
5. Dashboard becomes available at your domain

---

## Step 10: Verify

1. Open `https://trade.yourdomain.com` — you should see the login page
2. Register a new account
3. Go to **Trading Accounts** → Add your Alpaca account
4. Go to **Data Sources** → Add your Discord bot
5. Check **System** tab — all services should show healthy

### Quick health check via terminal

SSH into your VPS and run:

```bash
# Check all containers
docker ps --format "table {{.Names}}\t{{.Status}}"

# Test API health
curl -s http://localhost:8011/health | jq .

# Check logs for a specific service
docker logs <container_name> --tail 50
```

---

## Ongoing Operations

### Redeploying (after code changes)

Push to `main` → In Coolify, click **Deploy** (or enable auto-deploy via webhook).

To enable auto-deploy:
1. Go to resource **Settings** → **Webhooks**
2. Copy the webhook URL
3. Add it to your GitHub repo: **Settings** → **Webhooks** → **Add webhook**
4. Set the payload URL, content type `application/json`, and trigger on `push`

### Viewing Logs

In Coolify dashboard → select your resource → **Logs** tab. You can filter by service.

Or SSH into VPS:
```bash
docker compose -f docker-compose.coolify.yml logs -f api-gateway
docker compose -f docker-compose.coolify.yml logs -f trade-executor
```

### Scaling (if your VPS has more resources)

Edit `docker-compose.coolify.yml` → adjust `deploy.resources.limits` and push. Redeploy.

### Updating Environment Variables

Change values in Coolify's **Environment Variables** panel → click **Redeploy**.

### Backups

Coolify backs up PostgreSQL data automatically if you enable it in **Settings** → **Backups**.

For manual backup via SSH:
```bash
docker exec postgres pg_dump -U phoenixtrader phoenixtrader > backup_$(date +%Y%m%d).sql
```

### Monitoring

SSH into VPS:
```bash
# Resource usage by container
docker stats --no-stream

# Disk usage
df -h
docker system df
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| **Backtesting tab missing** | Dashboard is serving a cached build. **Fix:** 1) In Coolify, go to your resource → **Deploy** → click the **⋮** menu → **Force Deploy** (rebuilds without cache). 2) Or: **Configuration → Advanced** → enable **Disabled Build Cache** → **Deploy**. 3) Hard-refresh browser (Ctrl+Shift+R or Cmd+Shift+R). |
| **Build fails** | Check build logs in Coolify. Usually a missing env var or Docker context issue. |
| **"502 Bad Gateway"** | Services still starting. Wait 1–2 min. Check `docker ps` for unhealthy containers. |
| **Dashboard loads but API calls fail** | Verify `api-gateway` container is running. Check `docker logs api-gateway`. |
| **"Database connection refused"** | PostgreSQL may not be ready. Check `docker logs postgres`. Ensure `POSTGRES_PASSWORD` is set. |
| **Kafka keeps restarting** | Usually OOM. Increase Kafka memory limit in compose or upgrade VPS. |
| **SSL not working** | Ensure your domain A record points to the VPS IP. Coolify handles Let's Encrypt automatically. |
| **Out of disk space** | Run `docker system prune -a` to clean old images. |
| **Out of memory** | Check `docker stats`. Reduce Kafka memory limit or disable unused services. |

---

## Architecture on VPS

```
Internet
   │
   ▼
Traefik (Coolify built-in) ─── HTTPS ───▶ dashboard-ui (nginx :80)
                                              │
                                    ┌─────────┤ /api/* /auth/*
                                    ▼
                              api-gateway (:8011)
                                    │
                   ┌────────────────┼────────────────┐
                   ▼                ▼                 ▼
             auth-service     trade-parser    source-orchestrator
                              trade-gateway   notification-service
                              trade-executor  audit-writer
                              position-monitor
                                    │
                   ┌────────────────┼──────────┐
                   ▼                ▼           ▼
                 Kafka          PostgreSQL    Redis
            (internal)         (internal)   (internal)
```

All infrastructure and microservices are on a **private Docker network**. Only the dashboard is exposed to the internet through Coolify's Traefik proxy with automatic HTTPS.
