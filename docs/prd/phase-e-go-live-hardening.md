# PRD: Phase E — Go-Live Hardening + Release

Version: 1.0 | Status: Draft | Date: 2026-04-18 | Author: Nova-PM

## Problem Statement

Phases A–D and F are code-change phases. Phase E is the final gate before production go-live: coordinated regression, quality, E2E, benchmarks, security review, release artifact, staged rollout, and observability. Phoenix has the infrastructure (`make go-live-regression`, 107-task YAML matrix, `make benchmark`, go-live checklist) but no consolidated go-live plan.

## Goals

1. 100% automated regression pass (`make go-live-regression` green).
2. Quality gates green (`make go-live-regression-quality`: ruff + mypy).
3. E2E coverage: `make test-e2e` green; all 107 YAML journeys pass in parallel.
4. Performance baseline: `make benchmark` run; p50/p95/p99 documented; no regression > 20% on p95.
5. Security review: 0 Sev-1 findings; Sev-2/3 documented.
6. Release artifact: SemVer, CHANGELOG, release notes, rollback plan.
7. Staged rollout: Paper (week 1) → Limited Live (week 2, low caps) → Full Live (week 3+).
8. Observability checklist: 8 metrics live before Stage 1.

## Non-Goals

New feature development; non-blocking optimization; refactoring for style; OpenClaw side-effect fixes beyond flagging; infra changes; automated rollback tooling; multi-region; feature flags beyond kill-switch.

## User Stories

- **US-1** QA runs `make go-live-regression` and sees all legs pass in < 10 min.
- **US-2** QA runs `scripts/regression/run_yaml_parallel.py` against staging — 107 tasks green in < 5 min.
- **US-3** Eng lead runs `make go-live-regression-quality` — ruff + mypy green (or documented exceptions).
- **US-4** SRE runs `make benchmark` — p50/p95/p99 documented; delta < 20% vs baseline.
- **US-5** Security lead reviews all Phase A-F diffs via `security-review` — 0 Sev-1.
- **US-6** Release manager: helix-release generates CHANGELOG, SemVer rationale, release notes, rollback plan.
- **US-7** PM: staged rollout plan documented with go/no-go criteria per stage.
- **US-8** SRE: observability checklist with 8 metrics, thresholds, dashboards, runbooks.

## Functional Requirements

### F-1: Automated Regression
`make go-live-regression` → `make test` + `make test-integration` + `make test-bridge` + `make test-dashboard`. All exit 0. Runtime < 10 min. Zero undocumented skips.

### F-2: E2E YAML Matrix
`PHOENIX_E2E_BASE_URL=... PHOENIX_API_BASE_URL=... python3 scripts/regression/run_yaml_parallel.py`. 107 tasks, 11 batches, 10 parallel Playwright workers. `last_run_report.json` → `failed=0`. Runtime < 5 min.

### F-3: Quality Gates
`make go-live-regression-quality` → ruff (E/F zero; W/N ≤ baseline) + mypy on `shared/` (zero or documented exceptions in `docs/dev/mypy-exceptions.md`).

### F-4: Benchmarks
`make benchmark` → `test_pm_book_latency.py` (p95 < 50ms), `test_pm_scan_throughput.py` (≥500 markets/min), NEW `test_signal_to_trade_latency.py` (p95 < 2s). `last_run_report.json` with p50/p95/p99. If baseline exists, delta > 20% triggers investigation.

### F-5: Security Review
All Phase A-F diffs reviewed. Automated pre-scan (`bandit`, `npm audit`, `gitleaks`). Manual review by security lead. Sev-1: secrets in code; SQL injection; auth bypass; insecure crypto. Deliverable: `docs/dev/security-findings-phase-e.md`. Sev-2/3 documented with mitigation or acceptance rationale.

### F-6: Release Artifact (helix-release)
Inputs: PRDs, commit history since last tag. Outputs:
- SemVer rationale (`docs/releases/v{X}-semver-rationale.md`): major if breaking, minor if additive, patch if bugfix-only.
- `CHANGELOG.md` entry (Added / Changed / Fixed / Removed sections).
- `docs/releases/v{X}.md`: Highlights, What's New, Breaking Changes, Migration Steps, Known Issues, Rollback Plan, Release Readiness Checklist.

### F-7: Staged Rollout (`docs/operations/go-live-rollout-plan.md`)

**Stage 1 — Paper Mode (Week 1):** 5+ agents paper-only; 7 consecutive days.
Go: 0 crashes; ingestion lag p95 < 5s; paper order success > 95%; 0 Sev-1 bugs. No-go: any Sev-1; crash > 0; lag p95 > 10s.

**Stage 2 — Limited Live (Week 2):** max 3 live agents; $500 position max; 10 trades/day platform cap; 7 days.
Go: Stage 1 passed; live order success > 90%; no unauthorized trades; circuit breaker never stuck OPEN > 5 min; drawdown < $200/agent. No-go: unauthorized trade; success < 85%; breaker failure.

**Stage 3 — Full Live (Week 3+):** remove caps; up to 20 agents.
Go: Stage 2 passed; 0 Sev-1/2 in 7 days; observability green. No-go: any Sev-1; metric breach.

Rollback: `POST /api/v2/agents/kill-switch`; revert to paper; RCA required.

### F-8: Observability Checklist (`docs/operations/go-live-observability.md`)

| Metric | Threshold | Dashboard | Runbook |
|---|---|---|---|
| Discord ingestion lag p95 | < 5s | /platform-health | discord-lag.md |
| Agent wake errors/hour | < 1 | /agent-health | agent-wake-failure.md |
| Broker order success rate | > 95% | /trades | broker-order-failure.md |
| Signal-to-trade latency p95 | < 2s | /performance | trade-latency.md |
| Circuit breaker state | CLOSED or HALF_OPEN | /platform-health | circuit-breaker-open.md |
| API 5xx error rate | < 1% | logs/APM | api-errors.md |
| DB connection pool saturation | < 80% | Postgres metrics | db-pool-saturation.md |
| Redis pub/sub lag (stream:signals) | < 1s | Redis metrics | redis-lag.md |

PagerDuty for Sev-1; Slack for Sev-2. `/platform-health` refreshes every 10s with color-coded badges.

## Acceptance Criteria

- AC1 `make go-live-regression` exits 0; all 4 legs pass in < 10 min.
- AC2 `run_yaml_parallel.py` 107 tasks, `failed=0`, < 5 min.
- AC3 `make lint` + `make typecheck` exit 0 or documented exceptions signed off.
- AC4 Benchmarks produced; p95 delta < 20% or investigated.
- AC5 Security findings doc exists; 0 Sev-1 or all remediated; security lead sign-off.
- AC6 CHANGELOG + release notes + SemVer rationale + rollback plan exist; release manager sign-off.
- AC7 Staged rollout plan exists with 3 stages + go/no-go + rollback.
- AC8 Observability checklist with 8 metrics, thresholds, dashboards, runbooks, alerts configured.
- AC9 QA sign-off.
- AC10 PM sign-off.
- AC11 Eng lead sign-off.

## Dependencies

- Phases A, B, C, D, F complete and merged to `main`.
- Staging env matches production (DB, Redis, broker keys).
- Test creds: Discord test channel, Robinhood paper, IBKR paper.
- Monitoring platform (Grafana/Datadog) configured.

## Risks

| # | Risk | Mitigation |
|---|---|---|
| R-1 | Late-emerging regressions under load | 3x regression on staging; Stage 1 runs 7 days; metric alerts |
| R-2 | Benchmark regression from Phase A refactor | Automated baseline diff; root-cause + fix before sign-off |
| R-3 | Hidden OpenClaw side effects | Grep for `BRIDGE_URL`, `OPENCLAW`, `openclaw.bridge`; E2E T054 catches spawn failure; Stage 1 surfaces |
| R-4 | IBKR adapter paper-vs-live divergence | Stage 2 low caps; circuit breaker; rollback to Robinhood-only |
| R-5 | Security audit finds Sev-1 late | Start security review in parallel; automated pre-scan |
| R-6 | Observability gap missed | Pre-launch synthetic-load dry-run; SRE on-call with runbooks |

## Out of Scope

New features; perf optimizations not fixing regressions; code-style refactors; Kafka migration; Alpaca adapter; automated rollback tooling; multi-region; feature flags beyond kill-switch.

## Open Questions

- **Q-1** SemVer: major (breaking) vs minor? helix-release + PM determine based on API/schema diff.
- **Q-2** Feature flags for rollout? Recommend hybrid (kill-switch already from Phase B + agent-level mode).
- **Q-3** Paper→Live cutover: convert in-place, terminate-respawn, or continue paper + new live agents? Recommend continue-paper + new-live.
- **Q-4** On-call: SRE primary, eng lead secondary; PagerDuty 24/7 Stage 1/2, business hours Stage 3.
- **Q-5** Baseline benchmarks exist? If no baseline, Phase E establishes; otherwise compare vs `main` pre-Phase-A.

## Go-Live Checklist Mapping

Existing `docs/dev/go-live-regression-checklist.md` items map to Phase E requirements: env+migrations → F-1; automated regression → AC1; manual smoke → AC9; feature acceptance → AC10; sign-offs → AC9-11; cutover day → F-7.

## File Paths

Existing infra: `Makefile`, `docs/dev/go-live-regression-checklist.md`, `tests/regression/user_journeys.yaml`, `scripts/regression/run_yaml_parallel.py`, `tests/benchmark/test_pm_book_latency.py`, `test_pm_scan_throughput.py`, `scripts/go_live_regression.sh`, `smoke_go_live_api.sh`.

Phase E creates: `docs/operations/go-live-rollout-plan.md`, `go-live-observability.md`, `docs/dev/security-findings-phase-e.md`, `docs/releases/v{X}.md`, `v{X}-semver-rationale.md`, `CHANGELOG.md` update, `tests/benchmark/last_run_report.json`, `tests/regression/last_run_report.json`.
