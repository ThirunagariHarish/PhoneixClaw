# Phoenix Observability Stack

This directory contains configuration for the Phoenix observability stack: Prometheus, Grafana, Loki, and Promtail.

## Components

- **Prometheus** (`prometheus.yml`) — scrapes 12+ Phoenix services on `/metrics` endpoints
- **Grafana** — visualization dashboards (dashboards imported via `grafana/` directory)
- **Loki** — log aggregation with 30-day retention (720h)
- **Promtail** — log collector for Docker containers
- **Alerting** (`alerting-rules.yml`) — Prometheus alert rules

## Quick Start

### 1. Start the Stack

```bash
# From repo root
make up
# Or manually:
docker compose up -d prometheus grafana loki promtail
```

### 2. Access Dashboards

- Grafana: http://localhost:3003 (default: admin/admin)
- Prometheus: http://localhost:9090
- Loki: http://localhost:3100

### 3. Import Grafana Dashboards

1. Navigate to Grafana → Dashboards → Import
2. Upload JSON files from `grafana/dashboards/`:
   - `agent-wake-flow.json` — Phase B end-to-end flow metrics
   - Additional dashboards as configured

Alternative — automated import via provisioning (already configured in docker-compose):
- Dashboards in `grafana/dashboards/` are auto-imported on Grafana startup
- Data sources in `grafana/datasources/` are auto-configured

### 4. Verify Prometheus Scrape Targets

```bash
# Check all targets are UP
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job, health}'
```

Expected targets (subset):
- phoenix-api
- phoenix-llm-gateway
- phoenix-orchestrator
- node-exporter
- postgres-exporter

### 5. Trigger Test Alerts

#### DLQ Backlog Alert
```bash
# Manually insert unresolved DLQ entries
psql $DATABASE_URL -c "INSERT INTO dead_letter_messages (connector_id, payload, error) VALUES ('test-connector', '{}'::jsonb, 'test') FROM generate_series(1, 60);"

# Check alert firing (wait ~2 min for scrape + evaluation)
curl http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | select(.labels.alertname == "DLQBacklog")'
```

#### Circuit Breaker Open Alert
```bash
# Trigger circuit breaker via API (requires running service)
# Manually set gauge to 2 (OPEN state):
curl -X POST http://localhost:8011/admin/test/circuit-breaker/open

# Check alert
curl http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | select(.labels.alertname == "CircuitBreakerOpen")'
```

#### Stream Lag Alert
```bash
# Check current lag metric
curl -s http://localhost:9090/api/v1/query?query=phoenix_redis_stream_lag_seconds | jq '.data.result'

# If lag > 300s, alert should fire after 2min
```

## Loki Log Queries

### Query by correlation_id
```
{job="phoenix-api"} | json | correlation_id="<UUID>"
```

### All ERROR logs in last hour
```
{job=~"phoenix-.*"} | json | level="ERROR" | line_format "{{.timestamp}} {{.message}}"
```

### DLQ writes
```
{job=~"phoenix-.*"} | json | message =~ "(?i)dead letter"
```

### Logs for specific agent
```
{job="phoenix-api"} | json | agent_id="<AGENT_ID>"
```

## Retention

- **Loki**: 30 days (720h) — configured via `docker-compose.yml` command args
- **Prometheus**: 15 days (default) — increase via `--storage.tsdb.retention.time` if needed

## DLQ Cleanup Cron

Automated cleanup of resolved DLQ entries older than 30 days runs daily at 03:00 via systemd timer.

### Manual Execution
```bash
# Dry run
python -m scripts.cleanup_dlq --dry-run

# Actual cleanup (30 days)
python -m scripts.cleanup_dlq --days 30

# Custom threshold (e.g., 7 days)
python -m scripts.cleanup_dlq --days 7
```

### Systemd Deployment (Production)
```bash
# Copy unit files
sudo cp infra/systemd/phoenix-cleanup-dlq.service /etc/systemd/system/
sudo cp infra/systemd/phoenix-cleanup-dlq.timer /etc/systemd/system/

# Enable and start timer
sudo systemctl daemon-reload
sudo systemctl enable phoenix-cleanup-dlq.timer
sudo systemctl start phoenix-cleanup-dlq.timer

# Check timer status
sudo systemctl list-timers | grep phoenix-cleanup-dlq
sudo systemctl status phoenix-cleanup-dlq.timer

# View last run logs
sudo journalctl -u phoenix-cleanup-dlq.service -n 50
```

## Metrics Reference

### Phase B Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `phoenix_dlq_unresolved_total{connector_id}` | Gauge | Unresolved DLQ entries (refreshed every 15s) |
| `phoenix_circuit_breaker_state{name, state}` | Gauge | Circuit breaker state (0=closed, 1=half_open, 2=open) |
| `phoenix_redis_stream_lag_seconds{stream_key}` | Gauge | Redis stream lag vs consumer cursor |
| `phoenix_tool_duration_seconds{tool}` | Histogram | Tool call latency distribution |
| `phoenix_agent_sessions_created_total` | Counter | Agent sessions spawned |
| `phoenix_subagent_spawned_total` | Counter | Position monitor sub-agents spawned |
| `phoenix_discord_messages_total` | Counter | Discord messages ingested |

## Troubleshooting

### Grafana dashboard shows "No data"
1. Check Prometheus is scraping target: `curl http://localhost:9090/api/v1/targets`
2. Verify metric exists: `curl http://localhost:9090/api/v1/query?query=phoenix_dlq_unresolved_total`
3. Check Grafana data source: Dashboards → Settings → Data source should be "Prometheus"

### Loki logs not appearing
1. Check Promtail status: `docker compose logs promtail`
2. Verify Loki is reachable: `curl http://localhost:3100/ready`
3. Check Promtail targets: `curl http://localhost:9080/targets` (if Promtail exposes API)

### Alerts not firing
1. Check alerting rules loaded: `curl http://localhost:9090/api/v1/rules`
2. Verify alert condition met: manually query the metric
3. Check Prometheus logs: `docker compose logs prometheus`

### DLQ gauge shows 0 but entries exist
1. Check background refresher is running (API logs should show "Starting DLQ gauge background refresher")
2. Manually trigger refresh by restarting API: `docker compose restart phoenix-api`
3. Verify database connectivity from API container

## References

- [Phase B Architecture Doc](../../docs/architecture/phase-b-agent-wake-verification.md)
- [Prometheus Query Docs](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Loki LogQL Docs](https://grafana.com/docs/loki/latest/logql/)
- [Grafana Dashboard Provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
