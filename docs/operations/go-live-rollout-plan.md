# Staged Rollout Plan — v2.0.0 Go-Live

**Version:** v2.0.0  
**Rollout Owner:** (TBD — Release Manager)  
**Go-Live Target Date:** 2026-04-XX (TBD)  
**Plan Status:** Draft

---

## Overview

This document defines the 3-stage rollout strategy for Phoenix Trade Bot v2.0.0, ensuring production stability through progressive validation. Each stage has explicit go/no-go criteria and rollback triggers.

**Rollout Philosophy:**
- **Start conservative:** Paper trading only, no live capital at risk.
- **Expand incrementally:** Limited live capital with single-agent smoke test.
- **Full deployment:** All agents, all features, with continuous monitoring.

---

## Stage 1: Paper Trading Only

**Duration:** 48 hours minimum  
**Capital at Risk:** $0 (all trades simulated)  
**Scope:**
- Deploy v2.0.0 to production environment.
- All new agents created with `paper_mode=true`.
- No live broker credentials provisioned.
- Existing live agents remain paused (not migrated yet).

### Deployment Steps

1. **Pre-deployment:**
   - [ ] Backup production database: `pg_dump -U postgres phoenix_trade_bot > backup_pre_v2.0.0.sql`
   - [ ] Freeze production deploys (hotfixes only, subject to Release Manager approval).
   - [ ] Notify users of upcoming maintenance window (30 minutes expected).

2. **Deploy v2.0.0:**
   ```bash
   # 1. Pull release tag
   git fetch origin
   git checkout v2.0.0

   # 2. Run database migrations
   make db-upgrade
   # Verify migrations applied: 046, 047, 048

   # 3. Update environment variables
   # Remove: BRIDGE_TOKEN
   # Add (if not present): ROBINHOOD_MCP_URL, IB_GATEWAY_HOST

   # 4. Rebuild and restart services
   docker compose build
   docker compose up -d

   # 5. Verify API health
   curl https://prod-host/health
   ```

3. **Post-deployment verification:**
   - [ ] API `/health` endpoint returns 200 OK.
   - [ ] Dashboard loads without errors.
   - [ ] Login flow works (JWT auth).
   - [ ] Agents list loads (empty or with existing agents paused).

4. **Create paper-mode test agent:**
   ```bash
   # Create a single paper-mode agent via API
   curl -X POST https://prod-host/api/v2/agents \
     -H "Authorization: Bearer $JWT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "Paper Test Agent v2.0",
       "type": "trading",
       "connector_id": "'$CONNECTOR_ID'",
       "engine_type": "pipeline",
       "paper_mode": true
     }'
   ```

5. **Inject synthetic signals:**
   - Use Discord channel or manual signal injection script.
   - Target: 50+ signals over 48 hours.
   - Monitor: signal-to-trade latency, paper trades logged to `paper_trades.json`.

### Go/No-Go Criteria

**Go to Stage 2 if ALL are true:**
- [ ] 48 hours elapsed with no critical errors.
- [ ] Paper agent processed 50+ signals successfully.
- [ ] Signal-to-trade p95 latency < 2s (measured via benchmark or Grafana).
- [ ] Zero Sev-1 or Sev-2 errors in application logs.
- [ ] No database deadlocks or connection pool exhaustion.
- [ ] Dashboard trades tab displays paper trades correctly.
- [ ] `decision_trail` JSON visible via eye icon for all paper trades.

**No-Go (Rollback to v1.15.3) if ANY are true:**
- [ ] Agent creation requests fail with 500 or database errors.
- [ ] Paper trades not logged (signal processed but no `paper_trades.json` entry).
- [ ] Signal-to-trade p95 > 5s (indicating pipeline bottleneck).
- [ ] Sev-1 security finding identified (e.g., credential leak, SQL injection).
- [ ] Database migration caused data corruption (verified via checksum mismatch).

### Rollback Trigger

If no-go criteria met, execute immediate rollback:

```bash
# 1. Restore database backup
psql -U postgres phoenix_trade_bot < backup_pre_v2.0.0.sql

# 2. Revert code to v1.15.3
git checkout v1.15.3

# 3. Rebuild and restart
docker compose up -d --build

# 4. Verify health
curl https://prod-host/health
```

Notify users of rollback and postpone go-live until root cause resolved.

---

## Stage 2: Limited Live Capital (Single Agent)

**Duration:** 7 days minimum  
**Capital at Risk:** $500 maximum (single agent, position limits enforced)  
**Scope:**
- Promote one paper-mode agent to live trading.
- Enable Robinhood MCP credentials for this agent only.
- All other agents remain in paper mode or paused.

### Deployment Steps

1. **Select agent for promotion:**
   - Choose agent with highest paper-mode success rate (>80% win rate or >50 successful trades).
   - Verify agent has passed backtesting approval (`status=backtesting_approved`).

2. **Enable live credentials:**
   ```bash
   # Update agent config to enable live mode
   curl -X PATCH https://prod-host/api/v2/agents/$AGENT_ID \
     -H "Authorization: Bearer $JWT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"paper_mode": false}'

   # Verify credentials injected (check agent working directory)
   # Expect: .claude/settings.json has ROBINHOOD_USERNAME/PASSWORD env vars
   ```

3. **Configure position limits:**
   - Agent-level risk chain: max $500 total exposure, max $100 per position.
   - Global risk chain: max 5 concurrent positions across all agents.

4. **Monitor first live trade:**
   - Watch logs in real-time: `docker compose logs -f phoenix-api`
   - Dashboard trades tab: verify trade appears with `status=open`, broker order ID populated.
   - Check Robinhood app: confirm order executed and filled.

5. **7-day soak period:**
   - Target: 20+ live trades over 7 days.
   - Monitor: PnL, trade latency, broker API errors, circuit breaker state.

### Go/No-Go Criteria

**Go to Stage 3 if ALL are true:**
- [ ] 7 days elapsed with no critical live-trading errors.
- [ ] Agent executed 20+ live trades successfully.
- [ ] Live trade latency p95 < 3s (including broker network round-trip).
- [ ] Zero broker API failures or circuit breaker OPEN states lasting > 5 minutes.
- [ ] PnL tracking accurate (DB values match Robinhood app within $0.10).
- [ ] No duplicate orders (each signal → exactly one broker order).
- [ ] No position leaks (all open positions have corresponding `agent_trades` row).

**No-Go (Pause Live Trading) if ANY are true:**
- [ ] Agent placed order but broker rejected (and agent did not record rejection).
- [ ] Trade executed on broker side but `agent_trades` row not inserted (orphaned order).
- [ ] Circuit breaker stuck in OPEN state (indicates sustained broker failures).
- [ ] Live trade latency p95 > 10s (unacceptable user experience).
- [ ] PnL calculation error > $10 (indicates incorrect entry/exit price tracking).

### Rollback Trigger

If no-go criteria met, pause live trading (do NOT fully roll back to v1.15.3):

```bash
# 1. Pause the live agent
curl -X POST https://prod-host/api/v2/agents/$AGENT_ID/pause \
  -H "Authorization: Bearer $JWT_TOKEN"

# 2. Set all agents to paper mode
UPDATE agents SET paper_mode = true WHERE paper_mode = false;

# 3. Investigate root cause (logs, DB query, broker API status)
# 4. Fix and re-test in Stage 1 paper mode
# 5. Retry Stage 2 after fix verified
```

Do NOT revert code or database unless data corruption is detected.

---

## Stage 3: Full Live Deployment

**Duration:** Indefinite (production steady-state)  
**Capital at Risk:** Per-agent limits enforced by risk chain ($5,000 max per agent, $50,000 global cap)  
**Scope:**
- Promote all approved agents to live trading.
- Enable full pipeline engine for all new agents (`engine_type=pipeline`).
- Monitor continuously via Grafana dashboards and Prometheus alerts.

### Deployment Steps

1. **Promote approved agents:**
   - Identify all agents with `status=backtesting_approved` and paper-mode win rate > 70%.
   - Batch-update via API or SQL:
     ```sql
     UPDATE agents
     SET paper_mode = false
     WHERE status = 'backtesting_approved'
       AND id IN (...);  -- Explicit allowlist of agent IDs
     ```

2. **Enable Prometheus alerts:**
   - Configure alerts for:
     - Agent heartbeat failure (no heartbeat in 10 minutes).
     - Circuit breaker OPEN for > 5 minutes.
     - Signal-to-trade latency p95 > 3s.
     - API error rate > 1% (5xx responses).
   - Alert destination: PagerDuty / Slack / email.

3. **Monitor Grafana dashboards:**
   - Agent wake-flow dashboard (`infra/observability/grafana/agent-wake-flow.json`).
   - Broker adapter circuit breaker states.
   - Redis stream lag (expect < 1s).

4. **Daily health checks:**
   - Review logs for WARNING/ERROR entries.
   - Check PnL accuracy across all agents (reconcile with broker statements).
   - Verify no position leaks (all open positions tracked in DB).

### Go/No-Go Criteria

**Steady-State Production if ALL are true:**
- [ ] All promoted agents executing trades successfully.
- [ ] No circuit breaker OPEN states lasting > 5 minutes.
- [ ] Signal-to-trade latency p95 < 3s across all agents.
- [ ] API uptime > 99.5% (measured over 30 days).
- [ ] Zero data-loss incidents (all trades recorded in DB).

**Rollback to Stage 2 (Limited Live) if ANY are true:**
- [ ] Multiple agents failing simultaneously (indicates platform-wide issue).
- [ ] Database deadlock or connection pool exhaustion.
- [ ] Broker API downtime > 30 minutes (Robinhood or IBKR outage).
- [ ] Sev-1 security incident (credential leak, unauthorized access).

### Emergency Kill Switch

If catastrophic failure occurs (e.g., runaway agent placing hundreds of orders), trigger kill switch:

```bash
# Pause ALL agents immediately
curl -X POST https://prod-host/api/v2/agents/kill-switch \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Emergency stop - runaway trades detected"}'

# Verify all agents paused
curl https://prod-host/api/v2/agents \
  -H "Authorization: Bearer $JWT_TOKEN" \
  | jq '.[] | select(.status != "paused")'
# Expected: empty result
```

**Post-Kill-Switch Actions:**
1. Investigate root cause (logs, DB, broker statements).
2. Cancel any open orders on broker side manually.
3. Reconcile positions (DB vs broker app).
4. Fix bug and re-test in Stage 1 paper mode.
5. Obtain PM/Eng Lead approval before resuming live trading.

---

## Rollback Decision Matrix

| Incident Severity | Stage 1 (Paper) | Stage 2 (Limited Live) | Stage 3 (Full Live) |
|-------------------|-----------------|------------------------|---------------------|
| **Sev-1:** Data corruption, credential leak, unauthorized access | Full rollback to v1.15.3 | Full rollback to v1.15.3 | Kill switch + incident response |
| **Sev-2:** Broker API failures, agent crashes, > 5% error rate | Continue (fix in hotfix) | Pause live agents, keep paper mode | Roll back to Stage 2 (limited live only) |
| **Sev-3:** Latency spikes, non-critical errors, UI glitches | Continue (monitor) | Continue (monitor) | Continue (monitor, schedule fix) |
| **Sev-4:** Cosmetic issues, non-blocking warnings | Continue | Continue | Continue |

---

## Communication Plan

### Pre-Deployment (Stage 1)
- [ ] Email all users 48 hours before deployment: "v2.0.0 upgrade scheduled for [DATE], 30-minute maintenance window."
- [ ] Post banner on dashboard: "System upgrade in progress. Paper trading only for 48 hours."

### Stage 1 → Stage 2 Transition
- [ ] Internal announcement: "Stage 1 complete, proceeding to limited live trading with Agent [ID]."
- [ ] Update dashboard banner: "Limited live trading enabled for select agents."

### Stage 2 → Stage 3 Transition
- [ ] Email all users: "v2.0.0 fully deployed. All approved agents now live."
- [ ] Remove dashboard banner.
- [ ] Post release notes link: [docs/releases/v2.0.0.md](../releases/v2.0.0.md)

### Rollback Scenario
- [ ] Immediate Slack/email notification: "v2.0.0 rollback initiated due to [REASON]. ETA: 15 minutes."
- [ ] Dashboard banner: "System rolled back to v1.15.3. All live trading paused."
- [ ] Post-mortem within 48 hours: root cause, remediation steps, re-deployment timeline.

---

## Sign-Off

| Role | Name | Signature / Date | Stage 1 Go | Stage 2 Go | Stage 3 Go |
|------|------|------------------|------------|------------|------------|
| Release Manager | | | | | |
| Engineering Lead | | | | | |
| Product Manager | | | | | |
| QA Lead | | | | | |
| Security Lead | | | | | |

---

**Document Version:** 1.0  
**Last Updated:** 2026-04-18  
**Next Review:** Upon Stage 1 completion
