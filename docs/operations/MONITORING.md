# PhoenixTrade Platform — Monitoring Guide

This guide walks you through monitoring every layer of the PhoenixTrade platform on k3s:
pods and containers, application metrics, infrastructure components (PostgreSQL, Redis, MinIO),
and observability tooling.

For deployment and upgrade workflows, see `docs/operations/deployment-guide.md`.

---

## Table of Contents

1. [Pod Monitoring (k3s)](#1-pod-monitoring-k3s)
2. [Application Metrics (Prometheus Endpoints)](#2-application-metrics-prometheus-endpoints)
3. [Infrastructure Monitoring](#3-infrastructure-monitoring)
4. [Grafana + Prometheus Stack (Future)](#4-grafana--prometheus-stack-future)
5. [Quick Reference Cheat Sheet](#5-quick-reference-cheat-sheet)

---

## 1. Pod Monitoring (k3s)

All commands assume you have kubectl configured for your k3s cluster. Phoenix runs in the `phoenix` namespace.

### 1.1 Check Pod Status

```bash
# Show all pods with status
kubectl get pods -n phoenix

# Wide output (includes node, IP)
kubectl get pods -n phoenix -o wide

# Watch pods in real time (updates every 2s)
kubectl get pods -n phoenix -w

# Shortcut via Makefile (if kubectl context is set)
make prod-status
```

Output columns to watch:

| Column  | Meaning                                                      |
|---------|--------------------------------------------------------------|
| STATUS  | `Running`, `Pending`, `CrashLoopBackOff`, `OOMKilled`, `ImagePullBackOff` — only Running is healthy |
| READY   | `1/1` means container is running and passed readiness probe |
| RESTARTS | High restart count indicates a failing service |

#### Pod Status Reference

| Status             | Meaning                                              | Action                                  |
|--------------------|------------------------------------------------------|-----------------------------------------|
| `Running`          | All containers are up                                | Healthy state                           |
| `Pending`          | Waiting for scheduling (check node resources)        | Check `kubectl describe pod <name> -n phoenix` |
| `CrashLoopBackOff` | Container keeps crashing                             | Check logs with `kubectl logs -n phoenix <pod> --previous` |
| `ImagePullBackOff` | Cannot pull the Docker image                         | Verify image tag in values.yaml         |
| `OOMKilled`        | Out of memory                                        | Increase `resources.<svc>.memory` in values.yaml |

### 1.2 Real-Time Resource Usage

```bash
# Live CPU and memory for every pod (requires metrics-server)
kubectl top pods -n phoenix

# Sort by memory usage
kubectl top pods -n phoenix --sort-by=memory

# Sort by CPU
kubectl top pods -n phoenix --sort-by=cpu

# Node-level resource usage
kubectl top nodes
```

Key columns:
- **CPU** — sustained >80% means the service needs more resources or horizontal scaling.
- **MEMORY** — compare against `resources.<svc>.memory` in `helm/phoenix/values.yaml`.

If `kubectl top` returns an error, install metrics-server:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

### 1.3 Reading Logs

```bash
# Tail all Phoenix service logs (with pod prefix)
kubectl logs -n phoenix -l app.kubernetes.io/part-of=phoenix --tail=100 -f --prefix

# Tail a single service
kubectl logs -n phoenix deployment/phoenix-api -f

# Last 200 lines only
kubectl logs -n phoenix deployment/phoenix-execution --tail=200

# Logs from the last 30 minutes
kubectl logs -n phoenix deployment/phoenix-automation --since=30m

# Logs from a previous crashed instance
kubectl logs -n phoenix <pod-name> --previous

# Filter for errors (pipe through grep)
kubectl logs -n phoenix deployment/phoenix-api --tail=500 | grep -iE "error|exception|traceback"
```

### 1.4 Health Check Interpretation

Every Python service has a `/health` endpoint that Kubernetes probes every 15 seconds via liveness and readiness checks.

Manually test a health endpoint:

```bash
# Port-forward to the service
kubectl port-forward -n phoenix deployment/phoenix-api 8011:8011 &
curl http://localhost:8011/health

# Expected response: {"status": "ok", ...}
```

### 1.5 Restart a Single Service

```bash
# Rollout restart (recreates pods with zero downtime)
kubectl rollout restart -n phoenix deployment/phoenix-api

# Check rollout status
kubectl rollout status -n phoenix deployment/phoenix-api
```

### 1.6 Upgrading a Service (Rebuild and Deploy)

Phoenix uses Helm for deployments. To deploy a new image version:

#### Via GitHub Actions CI/CD (Recommended)

Tag a new release:

```bash
git tag v1.2.3
git push origin v1.2.3
```

The CD workflow builds images, pushes to GHCR, and runs `helm upgrade` on the VPS.

#### Manual Helm Upgrade

After code changes, rebuild locally or pull the new tag from GHCR:

```bash
cd /opt/phoenix
git pull
helm upgrade phoenix helm/phoenix \
  -f helm/phoenix/values.prod.yaml \
  -n phoenix \
  --set image.tag=v1.2.3 \
  --wait --timeout=15m
```

For local development (using locally built images):

```bash
# Build images
make docker-build-services

# Upgrade chart
helm upgrade phoenix helm/phoenix -n phoenix --wait
```

### 1.7 k9s and Kubectl Dashboard (Optional)

Phoenix deployments are typically managed via `kubectl` directly. For a terminal UI:

```bash
# Install k9s (macOS)
brew install k9s

# Launch k9s
k9s -n phoenix
```

k9s provides an interactive TUI for viewing pods, logs, events, and resource usage.

For a full web UI, Lens Desktop is a popular option (https://k8slens.dev/).

---

## 2. Application Metrics (Prometheus Endpoints)

Every Python service exposes a `/metrics` endpoint that returns Prometheus-format
text. These are defined in `shared/metrics.py`.

### 2.1 Service Port Reference

| Service                    | Port  | Metrics URL (inside cluster)                          |
|----------------------------|-------|-------------------------------------------------------|
| phoenix-api                | 8011  | `http://phoenix-api:8011/metrics`                     |
| phoenix-ws-gateway         | 8031  | `http://phoenix-ws-gateway:8031/metrics`              |
| phoenix-execution          | 8020  | `http://phoenix-execution:8020/metrics`               |
| phoenix-broker-gateway     | 8040  | `http://phoenix-broker-gateway:8040/metrics`          |
| phoenix-inference-service  | 8045  | `http://phoenix-inference-service:8045/metrics`       |
| phoenix-llm-gateway        | 8050  | `http://phoenix-llm-gateway:8050/metrics`             |
| phoenix-feature-pipeline   | 8055  | `http://phoenix-feature-pipeline:8055/metrics`        |
| phoenix-discord-ingestion  | 8060  | `http://phoenix-discord-ingestion:8060/metrics`       |
| phoenix-agent-orchestrator | 8070  | `http://phoenix-agent-orchestrator:8070/metrics`      |
| phoenix-prediction-monitor | 8075  | `http://phoenix-prediction-monitor:8075/metrics`      |
| phoenix-backtesting        | 8085  | `http://phoenix-backtesting:8085/metrics`             |
| phoenix-automation         | —     | Worker (no HTTP endpoint, no metrics)                 |
| phoenix-dashboard          | 80    | N/A (static nginx, no metrics)                        |
| edge-nginx                 | 80    | N/A (reverse proxy, no metrics)                       |

### 2.2 Available Metrics

| Metric Name                        | Type      | Labels                    | Description                                |
|------------------------------------|-----------|---------------------------|--------------------------------------------|
| `phoenix_trades_total`             | Counter   | `service`, `status`       | Total trades processed (EXECUTED, REJECTED, ERROR) |
| `phoenix_trade_latency_seconds`    | Histogram | `service`                 | End-to-end trade execution latency         |
| `phoenix_open_positions`           | Gauge     | `service`                 | Current number of open positions           |
| `phoenix_http_requests_total`      | Counter   | `service`, `method`, `path`, `status` | HTTP requests served        |
| `phoenix_http_latency_seconds`     | Histogram | `service`, `method`, `path` | HTTP request latency                     |
| `phoenix_ws_connections`           | Gauge     | `channel`                 | Active WebSocket connections               |
| `phoenix_circuit_breaker_state`    | Gauge     | `service`                 | 0=closed, 1=open, 2=half-open             |
| `phoenix_errors_total`             | Counter   | `service`, `error_type`   | Application-level errors                   |

### 2.3 Query Metrics from the Terminal

```bash
# Port-forward to a service
kubectl port-forward -n phoenix deployment/phoenix-api 8011:8011 &
curl -s http://localhost:8011/metrics | head -40

# Filter for a specific metric
curl -s http://localhost:8011/metrics | grep phoenix_trades_total

# Check trade execution latency buckets
kubectl port-forward -n phoenix deployment/phoenix-execution 8020:8020 &
curl -s http://localhost:8020/metrics | grep phoenix_trade_latency

# Check open positions
kubectl port-forward -n phoenix deployment/phoenix-prediction-monitor 8075:8075 &
curl -s http://localhost:8075/metrics | grep phoenix_open_positions

# Check circuit breaker state (0=healthy)
curl -s http://localhost:8020/metrics | grep phoenix_circuit_breaker_state
```

### 2.4 What to Watch

| Situation                         | Metric to Check                            | Threshold               |
|-----------------------------------|--------------------------------------------|-------------------------|
| Trades failing                    | `phoenix_trades_total{status="ERROR"}`     | Any sudden spike        |
| Slow execution                    | `phoenix_trade_latency_seconds`            | p99 > 5s is concerning  |
| Circuit breaker tripped           | `phoenix_circuit_breaker_state`            | Value = 1 (open)        |
| WebSocket disconnections          | `phoenix_ws_connections`                   | Drops to 0 unexpectedly |
| Position monitor stuck            | `phoenix_open_positions`                   | Never decreasing        |

---

## 3. Infrastructure Monitoring

### 3.1 PostgreSQL

#### Connect to psql

```bash
# Connect interactively
kubectl exec -it -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader

# Run a single query
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT count(*) AS active_connections FROM pg_stat_activity WHERE state = 'active';"
```

#### Common Queries

```bash
# Active connections
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT count(*) AS active_connections FROM pg_stat_activity WHERE state = 'active';"

# Database size
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT pg_size_pretty(pg_database_size('phoenixtrader')) AS db_size;"

# Table sizes (largest first)
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT relname AS table, pg_size_pretty(pg_total_relation_size(relid)) AS size
   FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 10;"

# Slow queries (running > 5s)
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT pid, now() - pg_stat_activity.query_start AS duration, query
   FROM pg_stat_activity WHERE state = 'active' AND now() - query_start > interval '5 seconds';"

# Connection pool stats
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT count(*) AS total, state FROM pg_stat_activity GROUP BY state;"
```

### 3.2 Redis

```bash
# Quick health check
kubectl exec -n phoenix deployment/redis -- redis-cli ping
# Expected: PONG

# Memory usage
kubectl exec -n phoenix deployment/redis -- redis-cli info memory | grep -E "used_memory_human|maxmemory_human"

# Connected clients
kubectl exec -n phoenix deployment/redis -- redis-cli info clients | grep connected_clients

# Hit/miss rate (cache effectiveness)
kubectl exec -n phoenix deployment/redis -- redis-cli info stats | grep -E "keyspace_hits|keyspace_misses"

# Key count
kubectl exec -n phoenix deployment/redis -- redis-cli dbsize

# Live command stream (watch all commands in real time — Ctrl+C to stop)
kubectl exec -n phoenix deployment/redis -- redis-cli monitor
```

Calculate hit rate: `hits / (hits + misses) * 100`. A healthy cache has >90% hit rate.

### 3.3 MinIO (S3-compatible storage)

```bash
# Check MinIO logs
kubectl logs -n phoenix minio-0 --tail=100

# Access MinIO console (port-forward)
kubectl port-forward -n phoenix minio-0 9001:9001
# Open http://localhost:9001 in browser
# Login with MINIO_ROOT_USER and MINIO_ROOT_PASSWORD from SealedSecret
```

### 3.4 Disk Usage (PVCs)

```bash
# List all PVCs
kubectl get pvc -n phoenix

# Describe a PVC (shows size and bound PV)
kubectl describe pvc postgres-data-postgres-0 -n phoenix

# Check disk usage on the node
df -h
```

---

## 4. Grafana + Prometheus Stack (Future)

Observability tooling (Prometheus + Grafana) is planned but currently outside the Helm chart.

For now, metrics are exposed via `/metrics` endpoints on each service. A future deliverable will add:
- Prometheus scrape configs
- Grafana dashboards for trade latency, error rates, position monitoring
- Alert rules for critical thresholds

Placeholder configuration exists in `infra/observability/prometheus.yml` and `infra/observability/grafana-dashboards/`.

To experiment locally, run Prometheus/Grafana via the local dev stack:

```bash
make infra-up  # Starts Postgres, Redis (and Prometheus/Grafana if configured)
```

---

## 5. Quick Reference Cheat Sheet

### One-Liner Commands

```bash
# ---------- Pod Status ----------

# Are all pods healthy?
kubectl get pods -n phoenix --no-headers | awk '{if ($2 != "1/1" || $3 != "Running") print $0}'

# Which pod is eating memory?
kubectl top pods -n phoenix --sort-by=memory

# Grab errors from all services in the last hour
kubectl logs -n phoenix -l app.kubernetes.io/part-of=phoenix --since=1h --prefix 2>&1 | grep -iE "error|exception|traceback"

# Restart a misbehaving service
kubectl rollout restart -n phoenix deployment/phoenix-api

# ---------- Metrics ----------

# Quick trade count check
kubectl port-forward -n phoenix deployment/phoenix-api 8011:8011 &
curl -s http://localhost:8011/metrics | grep phoenix_trades_total

# Check if circuit breaker is open
kubectl port-forward -n phoenix deployment/phoenix-execution 8020:8020 &
curl -s http://localhost:8020/metrics | grep circuit_breaker

# ---------- PostgreSQL ----------

# Quick row counts for key tables
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT 'trades' AS t, count(*) FROM trades UNION ALL
   SELECT 'positions', count(*) FROM positions UNION ALL
   SELECT 'users', count(*) FROM users;"

# ---------- Redis ----------

# Memory + key count at a glance
kubectl exec -n phoenix deployment/redis -- redis-cli info memory | grep used_memory_human
kubectl exec -n phoenix deployment/redis -- redis-cli dbsize

# ---------- Kubernetes ----------

# Everything at a glance
kubectl get pods,svc,ingressroute,certificate -n phoenix

# Pod resource consumption
kubectl top pods -n phoenix --sort-by=memory

# Recent events (cluster-wide troubleshooting)
kubectl get events -n phoenix --sort-by='.lastTimestamp' | tail -20

# Describe a pod (events, conditions, resource usage)
kubectl describe pod <pod-name> -n phoenix
```

### Emergency Runbook

#### Service Down (pod restarting or unhealthy)

```bash
# 1. Check which service is down
kubectl get pods -n phoenix | grep -vE "Running.*1/1"

# 2. Read its logs
kubectl logs -n phoenix <pod-name> --tail=100

# 3. Check previous logs if CrashLoopBackOff
kubectl logs -n phoenix <pod-name> --previous

# 4. Common fixes:
#    - OOM: Increase resources.<svc>.memory in helm/phoenix/values.yaml
#    - DB connection refused: Check postgres pod health (kubectl logs -n phoenix postgres-0)
#    - Import error: Rebuild image (tag a new release or helm upgrade)

# 5. Restart the deployment
kubectl rollout restart -n phoenix deployment/<service-name>

# 6. If restart doesn't help, check events
kubectl describe pod <pod-name> -n phoenix | grep -A 10 Events
```

#### High Memory Usage

```bash
# 1. Identify the culprit
kubectl top pods -n phoenix --sort-by=memory

# 2. If a pod is near its limit, increase in helm/phoenix/values.yaml:
#    resources:
#      <service>:
#        memory: 4Gi   # increase from 2Gi

# 3. Apply the change
cd /opt/phoenix
helm upgrade phoenix helm/phoenix -f helm/phoenix/values.prod.yaml -n phoenix --wait

# 4. Monitor the rollout
kubectl rollout status -n phoenix deployment/<service-name>
```

#### Trade Stuck in PENDING

```bash
# 1. Check the trade in the database
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT trade_id, status, created_at FROM trades WHERE status = 'PENDING' ORDER BY created_at DESC LIMIT 10;"

# 2. Check execution service logs
kubectl logs -n phoenix deployment/phoenix-execution --tail=100

# 3. Check automation service logs (approval flow)
kubectl logs -n phoenix deployment/phoenix-automation --tail=100

# 4. If manual approval is on, approve via Discord bot (!approve <id>) or API
```

#### Database Connection Issues

```bash
# 1. Check postgres is running
kubectl get pods -n phoenix | grep postgres

# 2. Check connection count
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT count(*) FROM pg_stat_activity;"

# 3. If max connections reached (default 100), terminate idle connections:
kubectl exec -n phoenix postgres-0 -- psql -U phoenixtrader -d phoenixtrader -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
   WHERE state = 'idle' AND query_start < now() - interval '10 minutes';"

# 4. Check SealedSecret unsealed correctly
kubectl get secret phoenix-secrets -n phoenix -o yaml | grep POSTGRES_PASSWORD
```

#### Pods Stuck in Pending

```bash
# 1. Check PVC binding
kubectl get pvc -n phoenix

# 2. Describe the pod to see scheduling errors
kubectl describe pod <pod-name> -n phoenix

# 3. Common causes:
#    - Insufficient node resources (check kubectl top nodes)
#    - PVC not binding (check kubectl describe pvc <name> -n phoenix)
#    - Image pull failure (check kubectl describe pod <name> -n phoenix | grep -A 5 Events)
```

#### TLS Certificate Not Issuing

```bash
# 1. Check certificate status
kubectl get certificate -n phoenix

# 2. Describe the certificate
kubectl describe certificate phoenix-tls -n phoenix

# 3. Check cert-manager logs
kubectl logs -n cert-manager -l app=cert-manager --tail=100

# 4. Verify ClusterIssuer exists
kubectl describe clusterissuer letsencrypt-prod

# 5. Verify DNS is pointing to the VPS
dig cashflowus.com +short
```

---

## Appendix: Service Architecture Quick View

```
Internet
   │
   ▼
Traefik (k3s built-in) ─── HTTPS ───▶ edge-nginx (ClusterIP :80)
                                          │
                                ┌─────────┤ /api/* /auth/* /ws/*
                                ▼         │
                          phoenix-api (:8011)  phoenix-ws-gateway (:8031)
                                │             phoenix-dashboard (:80)
               ┌────────────────┼────────────────┐
               ▼                ▼                 ▼
         phoenix-execution  phoenix-llm-gateway  phoenix-broker-gateway
         phoenix-automation phoenix-inference   phoenix-agent-orchestrator
         phoenix-discord-ingestion               phoenix-feature-pipeline
         phoenix-prediction-monitor              phoenix-backtesting
               │
  ┌────────────┼──────────┐
  ▼            ▼           ▼
postgres    redis       minio
(StatefulSet) (Deployment) (StatefulSet)
  :5432       :6379       :9000
```

All services communicate on the internal Kubernetes ClusterIP network. Only Traefik exposes HTTPS to the internet via the IngressRoute.

All services expose `/health` (liveness) and `/metrics` (Prometheus) endpoints.
