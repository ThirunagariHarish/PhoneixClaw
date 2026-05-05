# Enterprise-Readiness Gap Analysis — Phoenix Trade Bot

**Date:** 2026-05-05
**Scope:** Single-tenant k3s production at https://cashflowus.com/
**Author:** atlas-architect (audit phase)
**Status:** Active — top quick wins shipped in commits `8b16264`, `a52c176`, and the commit that adds this file.

---

## Executive summary

Phoenix has solid foundations (agent-first design, circuit breakers, repository pattern, Redis bus, sealed secrets, daily Postgres CronJob, pre-upgrade `pg_dump` artifacts). Five enterprise-readiness gaps remain:
1. Observability lacks distributed tracing and JSON-structured logging
2. RBAC + NetworkPolicies absent (single-node masks the risk; multi-tenant or audit context exposes it)
3. DR has no documented RTO/RPO yet (added today in `DEPLOYMENT.md`)
4. Connection-pool exhaustion + query timeouts have no metrics until commit ships these gauges
5. Secret rotation, dep CVE scanning, and audit logging are partially manual

---

## 1. Observability

| Gap | Severity | Effort | Action |
|---|---|---|---|
| No distributed tracing across 16 services | P0 | L | Adopt OpenTelemetry SDK; instrument FastAPI; propagate TraceId via HTTP headers |
| Unstructured logs lose context across services | P1 | M | `python-json-logger`; inject TraceId/SpanId into every line; ship to Loki |
| No centralized log aggregation | P1 | M | Deploy Loki agent; 30d full retention, 1y sampled |
| Missing key metrics (DB pool, queue depth, LLM tokens) | P1 | S | **Pool gauges shipped today.** LLM tokens + queue depth still TBD |
| No PrometheusRule alerts | P1 | M | Add `PhoenixAPIDown`, `PostgresUnavailable`, `AgentOOMKilled`, `CircuitBreakerOpen` |

## 2. Security

| Gap | Severity | Effort | Action |
|---|---|---|---|
| No RBAC; everything runs `default` ServiceAccount | P0 | M | Per-deployment SA + Role with least privilege |
| No NetworkPolicies | P1 | M | Default-deny; explicit `api→postgres/redis`, `edge-nginx→api/dashboard`, `broker-gateway→external:443` |
| No PodSecurityStandards | P1 | M | Enforce `restricted`; `runAsNonRoot: true`, drop ALL capabilities |
| No CVE scanning in CI | P1 | S | **Trivy added to CD validate job today (warn-only; flip to fail after triage).** |
| Secrets rotation manual | P2 | M | Document 90-day cadence; zero-downtime rotation playbook |
| Audit logging partial (only broker-gateway has it) | P1 | M | Add audit middleware to FastAPI; `audit_events` table |

## 3. Reliability

| Gap | Severity | Effort | Action |
|---|---|---|---|
| No idempotency on trade execution | P0 | M | `Idempotency-Key` header; cache responses in Redis 24h |
| DB pool exhaustion not monitored | P1 | S | **Shipped today: `phoenix_db_pool_*` gauges.** |
| No retry logic in API routes | P1 | M | `tenacity` decorator on DB/Redis calls |
| Agent OOM kills are silent | P1 | S | Catch exit code; write `agent.error_message`; fire notification |
| No circuit breaker on Anthropic API | P2 | M | Wrap Anthropic SDK; cached/degraded fallback |
| `/health` returned 200 even when degraded | P1 | S | **Already fixed before this audit** (`apps/api/src/main.py:880-899`) |

## 4. Scalability

| Gap | Severity | Effort | Action |
|---|---|---|---|
| `phoenix-api` is single-replica (in-memory `_running_tasks` dict) | P0 | L | Move to Redis hash; enable HPA 2-4 replicas |
| `broker-gateway` is single-replica | P1 | L | Move session pool to Redis (or accept) |
| No HPA anywhere | P1 | M | Add for `discord-ingestion`, `feature-pipeline`, `inference-service` |
| Some pods missing CPU requests | P2 | S | Fill in `resources.requests.cpu` for QoS Guaranteed |
| Redis is single-instance | P1 | M | Sentinel (3 nodes) or managed |
| No autoscaling for backtests | P2 | M | `backtesting-large` Deployment with 4Gi for big jobs |

## 5. Maintainability

| Gap | Severity | Effort | Action |
|---|---|---|---|
| Services lack type hints (only `shared/` is typed) | P2 | L | Extend MyPy to `services/` + `apps/api/src/`; incremental |
| `agent_gateway.py` is 700+ lines, mixed concerns | P2 | M | Split into `BacktestOrchestrator`, `LiveAgentManager`, `PositionMonitorManager` |
| Dead `test-bridge` reference in Makefile | P2 | S | Remove from `go-live-regression`; grep for `openclaw`/`bridge` |
| No dep lock file (ranges in `pyproject.toml`) | P1 | S | Migrate to `uv` or commit `requirements.lock` |
| Test coverage gaps; no CI coverage report | P2 | M | `pytest --cov` in CI; gate at 80% |
| No code complexity metrics | P2 | S | `radon cc -a` in lint step |

## 6. DevOps maturity

| Gap | Severity | Effort | Action |
|---|---|---|---|
| No lint gate in CD | P0 | S | **Shipped today: ruff in CD validate job.** |
| No smoke test post-deploy | P1 | S | **Shipped today: 6-attempt `/health` poll after `helm upgrade`.** |
| No Helm chart linting in CI | P2 | S | `helm lint helm/phoenix` step |
| No automated rollback on failed deploy | P1 | M | Detect unhealthy → `helm rollback` |
| No blue/green / canary | P2 | L | Argo Rollouts or Flagger; canary 10% for 5 min |
| Mutable `latest` tag still pushed | P2 | S | Remove; pin only immutable `main-<sha>` or `v*` |

## 7. Disaster recovery

| Gap | Severity | Effort | Action |
|---|---|---|---|
| No documented RTO/RPO targets | P0 | S | **Shipped today in `DEPLOYMENT.md`** |
| No restoration drills | P0 | M | Quarterly drill: scratch namespace, restore from artifact, verify, log MTTR |
| MinIO backup has no offsite copy | P1 | M | Push CronJob dump to S3 with 7d retention |
| No Redis persistence | P1 | S | Enable AOF (`appendonly yes`), 1s fsync, PVC for `/data` |
| Sealed-secrets key backup is manual | P1 | S | Monthly CronJob; encrypt with GPG; push to S3 |
| Missing runbooks for DB corruption, etcd failure, cert renewal stuck | P2 | M | One MD file per scenario in `docs/operations/runbooks/` |

## 8. Data integrity

| Gap | Severity | Effort | Action |
|---|---|---|---|
| No migration rollback tests | P1 | M | CI: `db-upgrade` then `db-downgrade` on test DB |
| Race condition in agent approval (concurrent approves) | P1 | M | Unique constraint on `agent_sessions(agent_id, session_role)`; catch IntegrityError → 409 |
| No transaction isolation on trade execution | P1 | M | `SERIALIZABLE` or Redis distributed lock per agent |
| Cascading deletes not audited | P2 | S | Verify `ondelete="CASCADE"` on FK constraints; document |
| No DB schema diagram | P2 | M | `eralchemy` → `docs/architecture/schema.png` |
| No per-query timeout overrides | P2 | S | Context manager for long analytics queries |

---

## Top 5 quick wins — status

| # | Win | Status |
|---|---|---|
| 1 | Lint gate in CD | ✅ shipped today |
| 2 | Document RTO/RPO targets | ✅ shipped today |
| 3 | Expose DB pool metrics | ✅ shipped today |
| 4 | CVE scan (Trivy) in CI | ✅ shipped today (warn-only) |
| 5 | Smoke test post-deploy | ✅ shipped today |

## Top 5 strategic items — pending user decision

| # | Item | Why it matters | Effort |
|---|---|---|---|
| 1 | Refactor phoenix-api for horizontal scaling | Single-replica = ceiling; OOM = full outage | L |
| 2 | OpenTelemetry distributed tracing | Cross-service debug today is `kubectl logs` per pod | L |
| 3 | RBAC + NetworkPolicies | Currently any pod can talk to any pod | M-L |
| 4 | Quarterly DR restoration drills | Backups exist but never tested end-to-end | M |
| 5 | Blue/green or canary deployment | Reduce blast radius; current deploys are atomic | L |

---

## SelfAgentBot port candidates (deeper integration)

From SelfAgentBot survey today, ranked by value-to-effort:

| Pattern | Value | Effort | Note |
|---|---|---|---|
| Kill-switch FSM (portfolio risk) | High | Low | FSM with HEALTHY → THROTTLED → FROZEN → QUARANTINED states; reads `shared/kill_switch.json`; guards trade execution |
| Token-bucket rate limiter | High | Low | Async + sync; per-API quota mgmt; prevents 429 cascades |
| Telegram alerter with breaker | High | Low | Operational visibility + circuit breaker on alert channel |
| Trailing-stop durable loop | High | Medium | Single-writer JSONL queue, atomic file I/O, heartbeat |
| Shadow mode | High | Low | Per-agent live/shadow/paper; logs would-be orders to JSONL |
| Backtest engine (signal replay) | Medium | High | Replays Discord signals through TA gate |
| Prometheus metrics exporter | Medium | Low | 80-LOC HTTP server reading `shared/*.json` |
| SQLite audit layer | Medium | Medium | WAL mode, schema versioning, dual-write |
| Kelly criterion position sizer | Medium | Low | Half-Kelly given win-rate + R:R |
| Inbox consumer ring buffer | Medium | Medium | Real-time signal stream + replay |
| IBKR adapter | Medium | High | Diversify beyond Robinhood |

---

## References

- [OpenTelemetry 2026: The Unified Observability Standard](https://techbytes.app/posts/opentelemetry-2026-unified-observability-standard/)
- [Building Enterprise-Grade Observability](https://medium.com/@manojnair_66308/building-enterprise-grade-observability-a-complete-guide-to-logs-traces-and-metrics-bcc48ded8e74)
- [Kubernetes Security Checklist for 2026](https://www.sentinelone.com/cybersecurity-101/cloud-security/kubernetes-security-checklist/)
- [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
- [Production Database Disaster Recovery 2026](https://hostperl.com/blog/production-database-disaster-recovery-bulletproof-backup-systems-2026)
- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — multi-agent DAG with risk-judge
- [autotradelab — backtest framework comparison](https://autotradelab.com/blog/backtrader-vs-nautilusttrader-vs-vectorbt-vs-zipline-reloaded)
- [Tecton — Robinhood feature store with Feast](https://www.tecton.ai/apply/session-video-archive/how-robinhood-built-a-feature-store-using-feast/)
