# Polymarket Tab v1.0 — Release Readiness Checklist

**Release**: Phoenix Trade Bot `0.2.0`
**Date**: 2026-04-07
**Release manager**: Helix
**Status**: Awaiting user go/no-go

## Scope confirmation

- [x] 15 implementation phases complete
- [x] v1.0 features F1, F2, F3, F9, F10, F12, F13 shipped
- [x] v1.1+ features F4, F5, F6, F7, F8, F11 explicitly deferred and documented
- [x] Backtester OOM fix bundled

## Quality gates

- [x] **Tests**: 215+ new tests passing (unit, integration, chaos, benchmark).
      Pre-existing suite green.
- [x] **Cortex**: APPROVED on all phases. All blockers and must-fixes resolved.
- [x] **Quill**: regression green. BUG-1 and BUG-2 resolved and verified.
- [x] **Lint**: Ruff clean on touched paths.
- [x] **Typecheck**: MyPy clean on `shared/`.
- [ ] **Manual smoke** on staging — *user to confirm before tagging*.

## PRD acceptance criteria

- [x] Polymarket tab visible in dashboard nav
- [x] Market discovery returns live Polymarket markets
- [x] User can create a new Polymarket agent from a template
- [x] New agents start in paper mode and cannot bypass it
- [x] Promote-to-live requires signed attestation + role + dwell time + recent backtest
- [x] Polymarket positions traverse the 3-layer risk chain
- [x] Backtester can replay historical Polymarket markets
- [x] Morning briefing includes a Polymarket section
- [x] No regression in existing equities/options flows

## Database migrations

- [x] `029_pm_v1_0_initial.py` — reviewed, reversible
- [x] `030_pm_paper_mode_since.py` — reviewed, reversible
- [x] `031_pm_last_backtest_at.py` — reviewed, reversible, has unit test
      (`tests/unit/test_migration_031.py`)
- [x] `032_agents_tab_fix.py` — reviewed (bundled fix, reversible)
- [x] Migration order verified against current head
- [x] Downgrade path tested in dev

## Documentation

- [x] `CHANGELOG.md` updated with `0.2.0` entry
- [x] `docs/releases/polymarket-v1.0.md` — user-facing release notes
- [x] `docs/releases/polymarket-v1.0-readiness.md` — this file
- [x] `docs/LEGAL.md` — jurisdiction disclaimer present
- [x] `docs/RUNBOOK.md` — operational procedures present
- [x] `docs/prd/` — Polymarket Tab v1.0 PRD archived
- [x] `docs/architecture/` — Polymarket architecture archived
- [x] `docs/qa/` — QA reports archived

## Open risks

| Risk                                                    | Severity | Mitigation                                                                                  |
| ------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------- |
| Polymarket API rate limits under heavy discovery scans  | Medium   | Discovery service has backoff; benchmark `test_pm_scan_throughput` enforces a ceiling      |
| Jurisdictional / TOS exposure for users                 | High     | Paper-mode default, attestation gate, `LEGAL.md`, no auto-promote                           |
| Single-venue concentration                              | Low      | Documented as known limitation; F4 (Kalshi) tracked for v1.1                                |
| Schema rollback drops paper-mode state                  | Low      | Documented in rollback plan; users warned to flatten live positions before downgrading      |
| Backtester OOM fix interactions with other workers      | Low      | `WEB_CONCURRENCY=2` and 2G memory observed stable in dev; monitor in prod for first 48h     |

## No P0/P1 bugs

- [x] No open P0 bugs
- [x] No open P1 bugs
- [x] BUG-1 (Quill) resolved
- [x] BUG-2 (Quill) resolved

## Version bump

- [x] Current: `pyproject.toml` `version = "0.1.0"`
- [x] Proposed: `0.2.0` (minor — new feature, no breaking changes)
- [ ] **User confirmation required** before Helix edits `pyproject.toml`
- Note: `apps/dashboard/package.json` is at `2.0.0` and tracks the dashboard
  independently — no bump proposed there unless user requests alignment.

## Rollback plan

Documented in `docs/releases/polymarket-v1.0.md` § Rollback. Summary:

1. Disable Polymarket tab / pause `pm_*` agents.
2. Redeploy previous image tag.
3. Optionally `alembic downgrade 028` (drops PM tables — flatten live positions
   first).
4. Equities/options flows unaffected.

## Tagging plan (pending user authorization)

If approved:

1. Helix bumps `pyproject.toml` to `0.2.0`.
2. User commits release artifacts (Helix will not commit).
3. User tags: `git tag -a v0.2.0 -m "Polymarket Tab v1.0"`.
4. User pushes tag: `git push origin v0.2.0`.

Helix will **not** push, tag, or publish without explicit per-action
authorization.

## Sign-off

- [ ] Engineering lead
- [ ] QA (Quill)
- [ ] Architecture (Cortex)
- [ ] Product
- [ ] Release manager (Helix) — pending above
