# Go-live regression checklist

Use this for staging/production sign-off. Do not ship until **Go** criteria are met.

## 1. Environment and migrations

| Check | Owner | Date | Pass/Fail |
|-------|--------|------|-----------|
| Postgres + Redis available to API | | | |
| `DATABASE_URL` / k3s secrets match runtime | | | |
| Alembic at head (includes `038_decision_trail` for `agent_trades.decision_trail`) | | | |

Commands (local or CI image with repo root):

```bash
make db-alembic-heads    # expect: 038_decision_trail (head)
make db-current          # on target DB; must equal head after upgrade
make db-upgrade          # apply pending migrations when safe
```

## 2. Automated regression

| Step | Command | Pass/Fail |
|------|---------|-----------|
| **Primary gate** | `make go-live-regression` | Runs `test` (repo unit + `apps/api/tests/unit`), `test-integration`, `test-dashboard` (NOTE: `test-bridge` removed in v2.0.0) |
| Optional: ruff + mypy | `make go-live-regression-quality` | May fail until repo-wide lint/mypy cleanup |
| API integration tests | `make test-api-all` | Includes `apps/api/tests/integration/` (route drift / DB) |
| API unit only | `make test-api` | Subset of `make test` second leg |
| Playwright E2E | `make test-e2e` | Requires API :8011 + dashboard :3000 |
| Alembic head check | `make db-alembic-heads` | Expect `038_decision_trail (head)` or later (046-048 in v2.0.0) |
| Script wrapper | `./scripts/go_live_regression.sh` | Same as `go-live-regression`; set `SKIP_E2E=0` to append E2E |
| **NEW: Benchmark** | `make benchmark` | Signal-to-trade latency p95 < 2s |

## 3. Manual smoke (QA / PM spot-check)

| Check | Owner | Date | Pass/Fail |
|-------|--------|------|-----------|
| Login; Agents list loads | | | |
| Agent detail → Live → Trades; eye icon / decision trail | | | |
| Backtesting tab loads for an agent | | | |
| Connectors / Robinhood (if in scope) | | | |
| Create agent (if used) without 502 | | | |
| Live pipeline in **paper** only first; no live-money smoke until signed off | | | |

API smoke (replace env vars):

```bash
export API_BASE_URL=https://your-host
export JWT_TOKEN=...
export AGENT_ID=...
./scripts/smoke_go_live_api.sh
```

## 4. PM feature acceptance

| Capability | Staging | Prod | Deferred |
|------------|---------|------|----------|
| Live path: signal → decision → execute → trades in UI/API | | | |
| `decision_trail` stored and visible | | | |
| Position monitor + sell-signal routing (file-based) | | | |
| Backtesting metrics / artifacts in UI | | | |
| Robinhood connector path | | | |
| **NEW v2.0:** Pipeline engine (`engine_type=pipeline`) | | | |
| **NEW v2.0:** IBKR Gateway broker adapter | | | |
| **NEW v2.0:** Observability dashboards (Grafana) | | | |

## 5. Go / no-go

**Go:** All automated steps green on release candidate; manual smoke pass; DB migrated; no open P0/P1 on auth or execution; security audit complete; observability metrics instrumented; rollout plan reviewed.

**No-go:** Failing `tests/integration/` or critical `tests/e2e/`; DB behind head; cannot list/post live trades; Sev-1 security finding unresolved; benchmark latency > 2s p95.

**Reference Documentation:**
- [Staged Rollout Plan](../operations/go-live-rollout-plan.md) — 3-stage deployment with go/no-go criteria
- [Observability Checklist](../operations/go-live-observability.md) — 8 metrics, thresholds, dashboards, runbooks
- [Security Findings](security-findings-phase-e.md) — Audit template and checklist
- [Release Notes v2.0.0](../releases/v2.0.0.md) — Breaking changes and migration steps

| Role | Name | Signature / Date |
|------|------|------------------|
| QA Lead | | |
| PM / Product Manager | | |
| Eng Lead / Engineering Lead | | |
| Security Lead | | |
| Release Manager | | |

## 6. Day-of cutover

- [ ] Freeze deploys after RC (hotfixes only).
- [ ] Run `make db-upgrade` (or equivalent) before/with API rollout.
- [ ] Post-deploy: login, one agent page, `./scripts/smoke_go_live_api.sh`, optional one paper signal.
- [ ] Monitor: API errors, agent heartbeats, trade inserts.
