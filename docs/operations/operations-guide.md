# Phoenix v2 Operations Guide

This guide covers deployment, monitoring, backups, incident response, scaling, and troubleshooting for Phoenix v2.

---

## Deployment Procedures

### Standard Deployment (Docker Compose)

1. Clone the repo and set environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with production values
   ```

2. Start the stack:
   ```bash
   cd infra && docker compose -f docker-compose.production.yml up -d
   ```

3. Verify health:
   ```bash
   curl http://localhost:8011/health
   ```

### Coolify Deployment

1. Provision Coolify: `./infra/scripts/provision-coolify.sh`
2. Add the Phoenix project and configure env vars from `.env.coolify.example`
3. Deploy via Coolify using the production compose or Coolify-specific compose

### Rolling Updates

- Use `docker compose pull && docker compose up -d` for rolling updates.
- For zero-downtime, run multiple API replicas behind a load balancer (Nginx).

---

## Monitoring and Alerting

### Grafana Dashboards

- **URL**: `http://<host>:3001` (default admin password: `admin`)
- Dashboards are provisioned from `infra/observability/grafana/`.
- Metrics: API latency, request counts, Redis/Postgres health, node exporter (CPU, memory).

### Prometheus

- **URL**: `http://<host>:9090`
- Scrape targets: `phoenix-api`, `phoenix-bridge`, `node-exporter`, `postgres-exporter`, `redis-exporter`
- Config: `infra/observability/prometheus.yml`

### Alerting Rules

- Config: `infra/observability/alerting-rules.yml`
- Configure Alertmanager to send alerts to Slack, PagerDuty, or email.

---

## Database Backup and Restore

### Backup

```bash
./infra/scripts/db-backup.sh
```

Uses `pg_dump` → gzip → upload to MinIO `phoenix-backups` bucket. Env: `PG_HOST`, `PG_USER`, `PG_DATABASE`, `MC_ALIAS`, `RETENTION_DAYS` (default 30).

### Restore

```bash
# Download from MinIO, then:
gunzip -c phoenix_YYYYMMDD_HHMMSS.sql.gz | psql -h $PG_HOST -U $PG_USER -d $PG_DATABASE
```

---

## Incident Response Procedures

1. **Service down** — Check `docker ps`, logs (`docker compose logs -f phoenix-api`), and `/health` endpoint.
2. **Database issues** — Verify `pg_isready`, connection limits, and disk space.
3. **Redis issues** — Check `redis-cli ping`, memory usage, and eviction policy.
4. **Trade execution failures** — Review execution service logs, broker API status, and connector credentials.
5. **Escalation** — Document in an incident log; notify stakeholders per runbook.

---

## Scaling

### Horizontal Scaling

- Run multiple API replicas behind Nginx (load balancing).
- Ensure Redis and PostgreSQL can handle increased connections.
- Use `docker compose up -d --scale phoenix-api=3` (or equivalent) if supported by your compose setup.

### Adding Nodes

- Provision new OpenClaw nodes with `./infra/scripts/provision-local-node.sh` or `./infra/scripts/provision-coolify.sh`.
- Add WireGuard peers and register nodes with the control plane.
- Deploy the bridge service on each node.

---

## Troubleshooting Common Issues

| Issue | Possible cause | Action |
|-------|----------------|--------|
| 401 Unauthorized | Invalid or expired JWT | Re-login; check `JWT_SECRET_KEY` |
| 502 Bad Gateway | API not ready or crashed | Check API logs; restart `phoenix-api` |
| Connection refused to Redis | Redis down or wrong URL | Verify `REDIS_URL`; `docker compose ps redis` |
| Skills not syncing | MinIO or bridge unreachable | Check `MINIO_ENDPOINT`, `BRIDGE_URL`, `BRIDGE_TOKEN` |
| Agents not starting | Bridge unreachable or wrong token | Verify bridge health; check `BRIDGE_TOKEN` on node |
| WireGuard handshake stale | Network or config issue | Run `./infra/scripts/test_wireguard.sh`; restart `wg-quick` |
