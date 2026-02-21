# PhoenixTrade Platform — Monitoring Guide

This guide walks you through monitoring every layer of the PhoenixTrade platform:
Docker containers, application metrics, Kubernetes clusters, and infrastructure
components (PostgreSQL, Redis, Kafka).

---

## Table of Contents

1. [Docker Monitoring (Coolify / VPS)](#1-docker-monitoring-coolifyvps)
2. [Application Metrics (Prometheus Endpoints)](#2-application-metrics-prometheus-endpoints)
3. [Kubernetes Monitoring](#3-kubernetes-monitoring)
4. [Infrastructure Monitoring](#4-infrastructure-monitoring)
5. [Grafana + Prometheus Stack (Optional)](#5-grafana--prometheus-stack-optional)
6. [Quick Reference Cheat Sheet](#6-quick-reference-cheat-sheet)

---

## 1. Docker Monitoring (Coolify/VPS)

### 1.1 Check Container Status

SSH into your VPS and run:

```bash
# Show all containers with health status
docker compose -f docker-compose.coolify.yml ps

# Shortcut via Makefile
make prod-status
```

Output columns to watch:

| Column  | Meaning                                                      |
|---------|--------------------------------------------------------------|
| STATE   | `running`, `exited`, `restarting` — anything but running is a problem |
| HEALTH  | `healthy`, `unhealthy`, `starting` — from the HEALTHCHECK in each Dockerfile |
| PORTS   | Mapped host:container ports                                  |

### 1.2 Real-Time Resource Usage

```bash
# Live CPU, memory, network I/O, and disk I/O for every container
docker stats

# Filter to a single service
docker stats api-gateway
```

Key columns:
- **CPU %** — sustained >80% means the service needs more resources or horizontal scaling.
- **MEM USAGE / LIMIT** — compare against the `deploy.resources.limits.memory` in `docker-compose.coolify.yml`.
- **NET I/O** — useful for spotting unusual traffic spikes.

### 1.3 Reading Logs

```bash
# Tail all service logs (Ctrl+C to stop)
docker compose -f docker-compose.coolify.yml logs -f

# Shortcut
make prod-logs

# Tail a single service
docker compose -f docker-compose.coolify.yml logs -f api-gateway

# Last 200 lines only
docker compose -f docker-compose.coolify.yml logs --tail=200 trade-executor

# Logs from the last 30 minutes
docker compose -f docker-compose.coolify.yml logs --since=30m notification-service

# Filter for errors (pipe through grep)
docker compose -f docker-compose.coolify.yml logs api-gateway 2>&1 | grep -i error
```

### 1.4 Health Check Interpretation

Every Python service has a Dockerfile `HEALTHCHECK` that hits its `/health` endpoint
every 15 seconds:

| Status      | What It Means                                   | Action                                  |
|-------------|------------------------------------------------|-----------------------------------------|
| `healthy`   | `/health` responded 200 within 5s              | All good                                |
| `starting`  | Container just started, within the grace period | Wait 30–60s                             |
| `unhealthy` | 3 consecutive health checks failed             | Check logs: `docker logs <container>`   |

Manually test a health endpoint:

```bash
# From inside the VPS (containers share the Docker network)
docker exec api-gateway python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8011/health').read())"
```

### 1.5 Restart a Single Service

```bash
# Restart without rebuilding
docker compose -f docker-compose.coolify.yml restart trade-executor

# Rebuild and restart (picks up code changes)
docker compose -f docker-compose.coolify.yml up -d --build trade-executor
```

### 1.6 Coolify UI

If you deployed via Coolify, open the Coolify dashboard at `https://<your-coolify-host>:8000`:

1. Navigate to **Projects > PhoenixTrade**.
2. Click any service to see its **Logs**, **Health**, and **Resource** graphs.
3. The **Deployments** tab shows build history and deploy status.
4. **Settings > Webhooks** shows whether GitHub auto-deploy is active.

---

## 2. Application Metrics (Prometheus Endpoints)

Every Python service exposes a `/metrics` endpoint that returns Prometheus-format
text. These are defined in `shared/metrics.py`.

### 2.1 Service Port Reference

| Service               | Port  | Metrics URL (inside Docker network) |
|-----------------------|-------|-------------------------------------|
| auth-service          | 8001  | `http://auth-service:8001/metrics`  |
| source-orchestrator   | 8002  | `http://source-orchestrator:8002/metrics` |
| api-gateway           | 8011  | `http://api-gateway:8011/metrics`   |
| trade-parser          | 8006  | `http://trade-parser:8006/metrics`  |
| trade-gateway         | 8007  | `http://trade-gateway:8007/metrics` |
| trade-executor        | 8008  | `http://trade-executor:8008/metrics`|
| position-monitor      | 8009  | `http://position-monitor:8009/metrics` |
| notification-service  | 8010  | `http://notification-service:8010/metrics` |
| audit-writer          | 8012  | `http://audit-writer:8012/metrics`  |
| nlp-parser            | 8020  | `http://nlp-parser:8020/metrics`    |
| dashboard-ui          | 80    | N/A (static nginx, no metrics)      |

### 2.2 Available Metrics

| Metric Name                        | Type      | Labels                    | Description                                |
|------------------------------------|-----------|---------------------------|--------------------------------------------|
| `phoenix_trades_total`             | Counter   | `service`, `status`       | Total trades processed (EXECUTED, REJECTED, ERROR) |
| `phoenix_trade_latency_seconds`    | Histogram | `service`                 | End-to-end trade execution latency         |
| `phoenix_kafka_messages_total`     | Counter   | `service`, `topic`        | Kafka messages consumed per topic          |
| `phoenix_open_positions`           | Gauge     | `service`                 | Current number of open positions           |
| `phoenix_http_requests_total`      | Counter   | `service`, `method`, `path`, `status` | HTTP requests served        |
| `phoenix_http_latency_seconds`     | Histogram | `service`, `method`, `path` | HTTP request latency                     |
| `phoenix_ws_connections`           | Gauge     | `channel`                 | Active WebSocket connections               |
| `phoenix_circuit_breaker_state`    | Gauge     | `service`                 | 0=closed, 1=open, 2=half-open             |
| `phoenix_errors_total`             | Counter   | `service`, `error_type`   | Application-level errors                   |

### 2.3 Query Metrics from the Terminal

```bash
# From inside the VPS, curl a service directly
curl -s http://localhost:8011/metrics | head -40

# If ports are not exposed to the host, exec into a container
docker exec api-gateway curl -s http://localhost:8011/metrics

# Filter for a specific metric
curl -s http://localhost:8011/metrics | grep phoenix_trades_total

# Check trade execution latency buckets
curl -s http://localhost:8008/metrics | grep phoenix_trade_latency

# Check open positions
curl -s http://localhost:8009/metrics | grep phoenix_open_positions

# Check circuit breaker state (0=healthy)
curl -s http://localhost:8008/metrics | grep phoenix_circuit_breaker_state
```

### 2.4 What to Watch

| Situation                         | Metric to Check                            | Threshold               |
|-----------------------------------|--------------------------------------------|-------------------------|
| Trades failing                    | `phoenix_trades_total{status="ERROR"}`     | Any sudden spike        |
| Slow execution                    | `phoenix_trade_latency_seconds`            | p99 > 5s is concerning  |
| Kafka consumer falling behind     | `phoenix_kafka_messages_total` (flat line) | Not incrementing        |
| Circuit breaker tripped           | `phoenix_circuit_breaker_state`            | Value = 1 (open)        |
| WebSocket disconnections          | `phoenix_ws_connections`                   | Drops to 0 unexpectedly |
| Position monitor stuck            | `phoenix_open_positions`                   | Never decreasing        |

---

## 3. Kubernetes Monitoring

If you deploy to Kubernetes (manifests in `k8s/`), these commands give you
full visibility.

### 3.1 Prerequisites

```bash
# Install kubectl (macOS)
brew install kubectl

# Verify connection to your cluster
kubectl cluster-info

# Set the namespace for all commands
kubectl config set-context --current --namespace=phoenixtrader
```

### 3.2 Pod Status

```bash
# List all pods with status
kubectl get pods -o wide

# Watch pods in real time (updates every 2s)
kubectl get pods -w

# Describe a specific pod (events, conditions, resource usage)
kubectl describe pod <pod-name>
```

Pod status reference:

| Status             | Meaning                                              |
|--------------------|------------------------------------------------------|
| `Running`          | All containers are up                                |
| `Pending`          | Waiting for scheduling (check node resources)        |
| `CrashLoopBackOff` | Container keeps crashing — check logs               |
| `ImagePullBackOff` | Cannot pull the Docker image — check image name/tag |
| `OOMKilled`        | Out of memory — increase resource limits             |

### 3.3 Pod Logs

```bash
# Stream logs from a pod
kubectl logs -f deployment/api-gateway

# Last 100 lines
kubectl logs deployment/trade-executor --tail=100

# Logs from a specific container (if multi-container pod)
kubectl logs <pod-name> -c <container-name>

# Logs from a previous crashed instance
kubectl logs <pod-name> --previous
```

### 3.4 Resource Usage

```bash
# CPU and memory per pod (requires metrics-server)
kubectl top pods

# CPU and memory per node
kubectl top nodes

# Sort by memory usage
kubectl top pods --sort-by=memory
```

If `kubectl top` returns an error, install metrics-server:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

### 3.5 Horizontal Pod Autoscaler (HPA)

The platform has HPAs for `api-gateway` and `trade-parser` (see `k8s/hpa.yaml`):

```bash
# Check current HPA status
kubectl get hpa

# Detailed HPA info
kubectl describe hpa api-gateway-hpa
```

Example output:

```
NAME              REFERENCE           TARGETS   MINPODS   MAXPODS   REPLICAS
api-gateway-hpa   Deployment/api-gw   45%/70%   2         10        3
```

- **TARGETS**: current CPU utilization / target. Scaling happens when current > target.
- **REPLICAS**: current replica count.

### 3.6 Services and Ingress

```bash
# List all services
kubectl get svc

# Check the ingress configuration
kubectl get ingress

# Describe ingress (shows routing rules, TLS status)
kubectl describe ingress phoenixtrader-ingress
```

### 3.7 Events (Cluster-Wide Troubleshooting)

```bash
# Recent events sorted by time (great for debugging scheduling/crash issues)
kubectl get events --sort-by='.lastTimestamp' | tail -20

# Events for a specific pod
kubectl get events --field-selector involvedObject.name=<pod-name>
```

### 3.8 Exec into a Pod

```bash
# Open a shell inside a running pod
kubectl exec -it deployment/api-gateway -- /bin/sh

# Run a one-off command
kubectl exec deployment/api-gateway -- curl -s http://localhost:8011/health
```

---

## 4. Infrastructure Monitoring

### 4.1 PostgreSQL

#### From Docker

```bash
# Connect to psql
docker exec -it postgres psql -U phoenixtrader -d phoenixtrader

# Active connections
docker exec postgres psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT count(*) AS active_connections FROM pg_stat_activity WHERE state = 'active';"

# Database size
docker exec postgres psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT pg_size_pretty(pg_database_size('phoenixtrader')) AS db_size;"

# Table sizes (largest first)
docker exec postgres psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT relname AS table, pg_size_pretty(pg_total_relation_size(relid)) AS size
   FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 10;"

# Slow queries (running > 5s)
docker exec postgres psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT pid, now() - pg_stat_activity.query_start AS duration, query
   FROM pg_stat_activity WHERE state = 'active' AND now() - query_start > interval '5 seconds';"

# Connection pool stats
docker exec postgres psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT count(*) AS total, state FROM pg_stat_activity GROUP BY state;"
```

#### From Kubernetes

```bash
kubectl exec -it statefulset/postgres -- psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"
```

### 4.2 Redis

```bash
# Quick health check
docker exec redis redis-cli ping
# Expected: PONG

# Memory usage
docker exec redis redis-cli info memory | grep -E "used_memory_human|maxmemory_human"

# Connected clients
docker exec redis redis-cli info clients | grep connected_clients

# Hit/miss rate (cache effectiveness)
docker exec redis redis-cli info stats | grep -E "keyspace_hits|keyspace_misses"

# Key count
docker exec redis redis-cli dbsize

# Live command stream (watch all commands in real time — Ctrl+C to stop)
docker exec redis redis-cli monitor
```

Calculate hit rate: `hits / (hits + misses) * 100`. A healthy cache has >90% hit rate.

### 4.3 Kafka

```bash
# List all topics
docker exec kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 --list

# Describe a topic (partitions, replicas, ISR)
docker exec kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 --describe --topic parsed-trades

# Consumer group lag (critical — shows if consumers are falling behind)
docker exec kafka /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups

# Peek at messages on a topic (last 5)
docker exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic raw-messages \
  --from-beginning --max-messages 5

# List consumer groups
docker exec kafka /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --list
```

Consumer lag reference:

| LAG Value | Meaning                                    | Action                      |
|-----------|--------------------------------------------|-----------------------------|
| 0         | Consumer is caught up                      | Healthy                     |
| 1–100     | Small lag, normal during bursts            | Monitor                     |
| 100+      | Consumer is falling behind                 | Check consumer logs/scaling |
| Growing   | Lag increasing over time                   | Consumer may be stuck       |

#### Kafka Topics Reference

| Topic              | Producer             | Consumer              |
|--------------------|---------------------|-----------------------|
| `raw-messages`     | source-orchestrator | trade-parser          |
| `parsed-trades`    | trade-parser        | trade-gateway         |
| `approved-trades`  | trade-gateway       | trade-executor        |
| `execution-results`| trade-executor      | api-gateway (WS), notification-service |
| `exit-signals`     | position-monitor    | trade-executor        |
| `notifications`    | various             | notification-service  |
| `dlq-*`            | any (on failure)    | audit-writer          |

---

## 5. Grafana + Prometheus Stack (Optional)

For a visual dashboard with alerting, add Prometheus and Grafana to your stack.

### 5.1 Create the Configuration

Create `prometheus.yml` in the project root:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "api-gateway"
    static_configs:
      - targets: ["api-gateway:8011"]

  - job_name: "auth-service"
    static_configs:
      - targets: ["auth-service:8001"]

  - job_name: "trade-parser"
    static_configs:
      - targets: ["trade-parser:8006"]

  - job_name: "trade-gateway"
    static_configs:
      - targets: ["trade-gateway:8007"]

  - job_name: "trade-executor"
    static_configs:
      - targets: ["trade-executor:8008"]

  - job_name: "position-monitor"
    static_configs:
      - targets: ["position-monitor:8009"]

  - job_name: "notification-service"
    static_configs:
      - targets: ["notification-service:8010"]

  - job_name: "audit-writer"
    static_configs:
      - targets: ["audit-writer:8012"]

  - job_name: "source-orchestrator"
    static_configs:
      - targets: ["source-orchestrator:8002"]

  - job_name: "nlp-parser"
    static_configs:
      - targets: ["nlp-parser:8020"]
```

### 5.2 Add to Docker Compose

Add these services to `docker-compose.coolify.yml` (or create a separate
`docker-compose.monitoring.yml`):

```yaml
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    ports:
      - "9090:9090"
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.retention.time=30d"
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    volumes:
      - grafana-data:/var/lib/grafana
    ports:
      - "3001:3000"
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-changeme}
    depends_on:
      - prometheus
    restart: unless-stopped
```

Add volumes at the bottom:

```yaml
volumes:
  prometheus-data:
  grafana-data:
```

### 5.3 Start the Stack

```bash
docker compose -f docker-compose.coolify.yml up -d prometheus grafana
```

### 5.4 Configure Grafana

1. Open `http://<your-server>:3001` (login: `admin` / your password).
2. Go to **Connections > Data Sources > Add data source**.
3. Select **Prometheus**.
4. Set URL to `http://prometheus:9090`.
5. Click **Save & Test**.

### 5.5 Useful Grafana Queries (PromQL)

Use these in Grafana dashboards or the Prometheus UI at `http://<server>:9090`:

```promql
# Trade throughput (trades per minute)
rate(phoenix_trades_total[5m]) * 60

# Trade error rate (percentage)
rate(phoenix_trades_total{status="ERROR"}[5m]) / rate(phoenix_trades_total[5m]) * 100

# p99 trade execution latency
histogram_quantile(0.99, rate(phoenix_trade_latency_seconds_bucket[5m]))

# Kafka message throughput by topic
rate(phoenix_kafka_messages_total[5m])

# HTTP request rate by service
sum by(service) (rate(phoenix_http_requests_total[5m]))

# HTTP p95 latency
histogram_quantile(0.95, sum by(le, service) (rate(phoenix_http_latency_seconds_bucket[5m])))

# Active WebSocket connections
phoenix_ws_connections

# Circuit breaker state (should be 0)
phoenix_circuit_breaker_state

# Error rate by type
rate(phoenix_errors_total[5m])
```

### 5.6 Suggested Alert Rules

Create these in Grafana (**Alerting > Alert Rules**):

| Alert Name               | Condition                                       | Severity |
|--------------------------|------------------------------------------------|----------|
| High Trade Error Rate    | `rate(phoenix_trades_total{status="ERROR"}[5m]) > 0.1` | Critical |
| Circuit Breaker Open     | `phoenix_circuit_breaker_state == 1`           | Critical |
| Trade Latency Spike      | `histogram_quantile(0.99, ...) > 10`           | Warning  |
| Kafka Consumer Stalled   | `rate(phoenix_kafka_messages_total[5m]) == 0`  | Warning  |
| WebSocket Drop           | `phoenix_ws_connections == 0` (when expected > 0) | Warning |
| Open Positions Anomaly   | `phoenix_open_positions > 50`                  | Warning  |
| HTTP 5xx Spike           | `rate(phoenix_http_requests_total{status=~"5.."}[5m]) > 0.05` | Critical |

---

## 6. Quick Reference Cheat Sheet

### One-Liner Commands

```bash
# ---------- Docker ----------

# Are all containers healthy?
docker compose -f docker-compose.coolify.yml ps --format "table {{.Name}}\t{{.Status}}"

# Which container is eating memory?
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" | sort -k3 -h -r

# Grab errors from all services in the last hour
docker compose -f docker-compose.coolify.yml logs --since=1h 2>&1 | grep -iE "error|exception|traceback"

# Restart a misbehaving service
docker compose -f docker-compose.coolify.yml restart <service-name>

# Full rebuild and redeploy a single service
docker compose -f docker-compose.coolify.yml up -d --build <service-name>

# ---------- Metrics ----------

# Quick trade count check
curl -s http://localhost:8011/metrics | grep phoenix_trades_total

# Check if circuit breaker is open
curl -s http://localhost:8008/metrics | grep circuit_breaker

# ---------- Kafka ----------

# Consumer lag across all groups
docker exec kafka /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups 2>&1 | grep -v "^$"

# ---------- PostgreSQL ----------

# Quick row counts for key tables
docker exec postgres psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT 'trades' AS t, count(*) FROM trades UNION ALL
   SELECT 'positions', count(*) FROM positions UNION ALL
   SELECT 'users', count(*) FROM users;"

# ---------- Redis ----------

# Memory + key count at a glance
docker exec redis redis-cli info memory | grep used_memory_human && \
docker exec redis redis-cli dbsize

# ---------- Kubernetes ----------

# Everything at a glance
kubectl get pods,svc,hpa,ingress -n phoenixtrader

# Pod resource consumption
kubectl top pods -n phoenixtrader --sort-by=memory
```

### Emergency Runbook

#### Service Down (container restarting or unhealthy)

```bash
# 1. Check which service is down
docker compose -f docker-compose.coolify.yml ps | grep -v healthy

# 2. Read its logs
docker compose -f docker-compose.coolify.yml logs --tail=100 <service>

# 3. Common fixes:
#    - OOM: Increase memory limit in docker-compose.coolify.yml
#    - DB connection refused: Check postgres container health
#    - Kafka timeout: Check kafka container health
#    - Import error: Rebuild the image (code dependency missing)

# 4. Restart the service
docker compose -f docker-compose.coolify.yml restart <service>
```

#### High Memory Usage

```bash
# 1. Identify the culprit
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" | sort -k3 -h -r

# 2. If a service is near its limit, increase in docker-compose.coolify.yml:
#    deploy:
#      resources:
#        limits:
#          memory: 512M   # increase from 256M

# 3. Redeploy
docker compose -f docker-compose.coolify.yml up -d <service>
```

#### Trade Stuck in PENDING

```bash
# 1. Check the trade in the database
docker exec postgres psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT trade_id, status, created_at FROM trades WHERE status = 'PENDING' ORDER BY created_at DESC LIMIT 10;"

# 2. Check trade-gateway logs for approval flow
docker compose -f docker-compose.coolify.yml logs --tail=50 trade-gateway

# 3. Check Kafka consumer lag for approved-trades
docker exec kafka /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups 2>&1 | grep approved

# 4. If manual approval is on, approve via Discord bot (!approve <id>) or API
```

#### Kafka Consumer Lag Growing

```bash
# 1. Check lag
docker exec kafka /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups

# 2. Check consumer service logs
docker compose -f docker-compose.coolify.yml logs --tail=100 trade-parser

# 3. If the consumer is stuck, restart it
docker compose -f docker-compose.coolify.yml restart trade-parser
```

#### Database Connection Issues

```bash
# 1. Check postgres is running
docker compose -f docker-compose.coolify.yml ps postgres

# 2. Check connection count
docker exec postgres psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT count(*) FROM pg_stat_activity;"

# 3. If max connections reached (default 100), terminate idle connections:
docker exec postgres psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
   WHERE state = 'idle' AND query_start < now() - interval '10 minutes';"
```

---

## Appendix: Service Architecture Quick View

```
                         ┌──────────────┐
                         │  Dashboard   │ :3080
                         │  (nginx)     │
                         └──────┬───────┘
                                │
                         ┌──────▼───────┐
                    ┌────│ API Gateway  │────┐
                    │    │   :8011      │    │
                    │    └──────┬───────┘    │
                    │           │            │
              ┌─────▼──┐  ┌────▼────┐  ┌────▼──────┐
              │  Auth   │  │ System  │  │ WebSocket │
              │ :8001   │  │ Routes  │  │ /ws/*     │
              └─────────┘  └─────────┘  └───────────┘
                                │
     ┌──────────────────────────┼──────────────────────────┐
     │                    Kafka Topics                      │
     ├──────────┬──────────┬──────────┬──────────┬─────────┤
     │raw-msgs  │parsed    │approved  │exec-     │exit-    │
     │          │-trades   │-trades   │results   │signals  │
     └────┬─────┴────┬─────┴────┬─────┴────┬─────┴────┬────┘
          │          │          │          │          │
     ┌────▼──┐ ┌─────▼───┐ ┌───▼────┐ ┌───▼─────┐ ┌─▼──────┐
     │Source │ │ Trade   │ │ Trade  │ │ Trade   │ │Position│
     │Orch.  │ │ Parser  │ │Gateway │ │Executor │ │Monitor │
     │:8002  │ │ :8006   │ │ :8007  │ │ :8008   │ │ :8009  │
     └───────┘ └─────────┘ └────────┘ └─────────┘ └────────┘

     Infrastructure: PostgreSQL :5432 │ Redis :6379 │ Kafka :9092
```

All services expose `/health` (liveness) and `/metrics` (Prometheus) endpoints.
