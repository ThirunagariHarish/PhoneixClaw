# Phoenix Operations Runbook

This runbook covers routine operational tasks for Phoenix Trade Bot.

## Daily Operations

### DLQ Cleanup

**Purpose:** Prevent unbounded growth of resolved dead letter messages (Phase B risk B-R3).

**Schedule:** Daily at 03:00 local time via systemd timer.

**Manual Execution:**

```bash
# Dry run — shows what would be deleted
python -m scripts.cleanup_dlq --dry-run

# Delete resolved entries older than 30 days (default)
python -m scripts.cleanup_dlq --days 30

# Custom retention (e.g., 7 days for aggressive cleanup)
python -m scripts.cleanup_dlq --days 7
```

**Systemd Timer Setup (Production):**

```bash
# Copy unit files
sudo cp infra/systemd/phoenix-cleanup-dlq.service /etc/systemd/system/
sudo cp infra/systemd/phoenix-cleanup-dlq.timer /etc/systemd/system/

# Enable timer
sudo systemctl daemon-reload
sudo systemctl enable phoenix-cleanup-dlq.timer
sudo systemctl start phoenix-cleanup-dlq.timer

# Verify timer is scheduled
sudo systemctl list-timers | grep phoenix-cleanup-dlq

# Check last run
sudo journalctl -u phoenix-cleanup-dlq.service -n 20
```

**Monitoring:**

- Metric: `phoenix_dlq_unresolved_total{connector_id}` (Prometheus)
- Alert: `DLQBacklog` fires if > 50 unresolved entries
- Check cron execution: `sudo journalctl -u phoenix-cleanup-dlq.service --since today`

**Troubleshooting:**

- Timer not running: `sudo systemctl status phoenix-cleanup-dlq.timer`
- Service failed: `sudo journalctl -u phoenix-cleanup-dlq.service -e`
- Database connection issues: verify `DATABASE_URL` in `.service` file matches production config

## Weekly Operations

### Log Retention Check

**Loki retention:** 30 days (720h) configured in `docker-compose.yml`.

**Verify retention:**

```bash
# Check Loki disk usage
docker compose exec loki du -sh /loki

# Query oldest logs
curl -G -s "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={job=~"phoenix-.*"}' \
  --data-urlencode "start=$(date -u -d '35 days ago' +%s)000000000" \
  --data-urlencode "end=$(date -u +%s)000000000" \
  --data-urlencode "limit=1" | jq
```

Logs older than 30 days should return empty.

### Prometheus Data Retention

**Default retention:** 15 days.

**Check storage size:**

```bash
docker compose exec prometheus du -sh /prometheus
```

**Increase retention (if needed):**

Edit `docker-compose.yml` Prometheus service:

```yaml
command:
  - '--storage.tsdb.retention.time=30d'
  - '--config.file=/etc/prometheus/prometheus.yml'
```

## Monthly Operations

### DLQ Review

Review unresolved DLQ entries to identify systemic issues.

```bash
# Query unresolved entries
psql $DATABASE_URL -c "
  SELECT connector_id, COUNT(*), MAX(created_at) as latest
  FROM dead_letter_messages
  WHERE resolved = false
  GROUP BY connector_id
  ORDER BY COUNT(*) DESC;
"

# Detailed view for a connector
psql $DATABASE_URL -c "
  SELECT id, error, payload->>'signal_type' as signal_type, created_at
  FROM dead_letter_messages
  WHERE connector_id = 'YOUR_CONNECTOR_ID' AND resolved = false
  ORDER BY created_at DESC
  LIMIT 10;
"
```

**Action items:**
- If same error repeats > 10 times: file bug ticket
- If payload schema changed: update parser tool
- If external API down: check circuit breaker config

### Observability Stack Health

**Verify all exporters are UP:**

```bash
curl -s http://localhost:9090/api/v1/targets | \
  jq -r '.data.activeTargets[] | "\(.labels.job): \(.health)"'
```

**Check alert rules loaded:**

```bash
curl -s http://localhost:9090/api/v1/rules | \
  jq '.data.groups[].rules[] | select(.type == "alerting") | .name'
```

**Grafana dashboard health:**

1. Open http://localhost:3003
2. Navigate to each dashboard
3. Verify panels show data (not "No data")
4. Check time range matches expected activity

## Emergency Procedures

### DLQ Overwhelmed (> 500 unresolved)

**Symptoms:**
- Alert: `DLQBacklog` firing
- Metric: `phoenix_dlq_unresolved_total > 500`

**Root cause diagnosis:**

```bash
# Group by error message
psql $DATABASE_URL -c "
  SELECT LEFT(error, 100) as error_prefix, COUNT(*)
  FROM dead_letter_messages
  WHERE resolved = false
  GROUP BY error_prefix
  ORDER BY COUNT(*) DESC
  LIMIT 5;
"
```

**Mitigation:**

1. If same error repeats: fix the underlying issue first
2. If external API down: wait for recovery + replay via `/admin/dlq/{id}/replay`
3. If invalid signals: discard via `/admin/dlq/{id}/discard`
4. If DB schema changed: run Alembic migration + replay

**Mass discard (use with caution):**

```bash
# Discard all entries for a connector (e.g., test signals)
curl -X POST http://localhost:8011/api/v2/admin/dlq/bulk-discard \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"connector_id": "test-connector"}'
```

### Circuit Breaker Stuck Open

**Symptoms:**
- Alert: `CircuitBreakerOpen` firing
- Metric: `phoenix_circuit_breaker_state{name="robinhood"} == 2`

**Reset breaker (if external service recovered):**

```bash
# Force reset via admin endpoint
curl -X POST http://localhost:8011/admin/circuit-breaker/reset \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "robinhood"}'
```

**If breaker immediately re-opens:**
- External service still unhealthy
- Check service status: Robinhood API, yfinance, etc.
- Review error logs: `{job="phoenix-api"} | json | level="ERROR" | message =~ "circuit"`

## Reference

### DLQ Admin Endpoints

- `GET /api/v2/admin/dlq` — list unresolved entries
- `POST /api/v2/admin/dlq/{id}/replay` — re-process a DLQ entry
- `POST /api/v2/admin/dlq/{id}/discard` — mark as resolved without retry
- CLI: `python -m scripts.replay_dlq --connector-id XYZ`

### Key Metrics

- `phoenix_dlq_unresolved_total{connector_id}` — unresolved DLQ count
- `phoenix_circuit_breaker_state{name}` — 0=closed, 1=half_open, 2=open
- `phoenix_redis_stream_lag_seconds{stream_key}` — stream lag
- `phoenix_agent_heartbeat_age_seconds{agent_id}` — agent liveness

### Alert Thresholds

See `infra/observability/alerting-rules.yml` for full list:
- `DLQBacklog`: > 50 unresolved
- `CircuitBreakerOpen`: state=2 for 5min
- `StreamLagHigh`: > 300s for 2min
- `AgentOffline`: heartbeat age > 180s for 3min

## See Also

- [Observability Stack README](../../infra/observability/README.md)
- [Phase B Architecture](../architecture/phase-b-agent-wake-verification.md)
- [Monitoring Guide](./MONITORING.md)
