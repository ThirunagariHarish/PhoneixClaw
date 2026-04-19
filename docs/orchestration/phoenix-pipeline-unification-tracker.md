# Phoenix Pipeline Unification — Delivery Tracker

**Start Date**: 2026-04-18  
**Scope**: All six phases (A-F), multi-week timeline, proper SDLC gates  
**Brokers**: Robinhood + Interactive Brokers (no Alpaca)  
**OpenClaw**: Full removal after QA

---

## Phase Dependencies

```
Phase A (Pipeline Consolidation) ─┐
Phase B (AI Flow Verification)   ─┤
Phase C (Backtesting DB)         ─┼──→ Phase D (Dashboard) ──→ Phase E (Go-Live)
Phase F (OpenClaw Removal)       ─┘
```

**Parallel track**: Phases A, B, C, F PRDs can all run in parallel  
**Sequential gates**: Phase D depends on Phase A architecture; Phase E depends on all others

---

## Phases

| Phase | Owner | Description | Status | Blocker | Artifact |
|-------|-------|-------------|--------|---------|----------|
| **A-PRD** | nova-pm | Pipeline consolidation PRD (port OldProject logic, Robinhood+IBKR adapters, dashboard UI) | pending | — | docs/prd/phase-a-pipeline-consolidation.md |
| **A-Arch** | atlas-architect | Pipeline architecture (broker routing, IBKR API selection, OldProject integration plan) | pending | Waiting A-PRD approval | — |
| **A-Impl** | devin-dev | Implement pipeline engine + broker adapters + dashboard | pending | Waiting A-Arch approval | — |
| **A-Review** | cortex-reviewer | Code review Phase A implementation | pending | Waiting A-Impl | — |
| **A-QA** | quill-qa | QA Phase A (end-to-end pipeline tests, broker integration) | pending | Waiting A-Review | — |
| **B-PRD** | nova-pm | AI flow verification PRD (trace Discord→Agent→Trade, fix gaps, add telemetry) | pending | — | docs/prd/phase-b-agent-wake-verification.md |
| **B-Arch** | atlas-architect | AI flow architecture audit (gap analysis, observability design) | pending | Waiting B-PRD approval | — |
| **B-Impl** | devin-dev | Fix gaps, add telemetry/observability | pending | Waiting B-Arch approval | — |
| **B-Review** | cortex-reviewer | Code review Phase B implementation | pending | Waiting B-Impl | — |
| **B-QA** | quill-qa | QA Phase B (end-to-end AI flow, observability validation) | pending | Waiting B-Review | — |
| **C-PRD** | nova-pm | Backtesting DB robustness PRD (audit coverage, naming, backfill tooling) | pending | — | docs/prd/phase-c-backtesting-db-robustness.md |
| **C-Arch** | atlas-architect | Backtesting DB architecture (coverage audit plan, backfill design) | pending | Waiting C-PRD approval | — |
| **C-Impl** | devin-dev | Audit implementation, backfill tooling, pipeline fixes | pending | Waiting C-Arch approval | — |
| **C-Review** | cortex-reviewer | Code review Phase C implementation | pending | Waiting C-Impl | — |
| **C-QA** | quill-qa | QA Phase C (coverage validation, backfill tests) | pending | Waiting C-Review | — |
| **F-PRD** | nova-pm | OpenClaw removal PRD (inventory, safe unwinding plan) | pending | — | docs/prd/phase-f-openclaw-removal.md |
| **F-Arch** | atlas-architect | OpenClaw removal architecture (dependency graph, migration plan) | pending | Waiting F-PRD approval | — |
| **F-Impl** | devin-dev | Remove OpenClaw (deprecate routes → remove service → drop DB → delete code) | pending | Waiting F-Arch approval | — |
| **F-Review** | cortex-reviewer | Code review Phase F implementation | pending | Waiting F-Impl | — |
| **F-QA** | quill-qa | QA Phase F (no regressions, all tests green) | pending | Waiting F-Review | — |
| **D-PRD** | nova-pm | Pipeline dashboard PRD (engine selector, stats, agent detail UI) | pending | Waiting A-Arch (design dependency) | docs/prd/phase-d-pipeline-dashboard.md |
| **D-Arch** | atlas-architect | Dashboard architecture (UI components, state management, API contracts) | pending | Waiting D-PRD + A-Arch | — |
| **D-Impl** | devin-dev | Complete dashboard implementation (Agents.tsx, Connectors.tsx, AgentDashboard.tsx) | pending | Waiting D-Arch approval | — |
| **D-Review** | cortex-reviewer | Code review Phase D implementation | pending | Waiting D-Impl | — |
| **D-QA** | quill-qa | QA Phase D (dashboard UI validation) | pending | Waiting D-Review | — |
| **E-Plan** | nova-pm | Go-live hardening plan (regression suite, E2E, benchmarks, release notes) | pending | Waiting A-QA + B-QA + C-QA + D-QA + F-QA | docs/prd/phase-e-go-live-hardening.md |
| **E-Exec** | devin-dev | Execute go-live checklist (make go-live-regression, make go-live-regression-quality) | pending | Waiting E-Plan approval | — |
| **E-Release** | helix-release | Version bump, changelog, release notes, tag | pending | Waiting E-Exec (all tests green) | — |

---

## Risks & Unknowns

| Risk | Mitigation | Owner |
|------|------------|-------|
| **IBKR API selection** (TWS vs Client Portal) — unknown if user needs local gateway | Atlas to research both options, document tradeoffs, get user decision in Phase A arch | atlas-architect |
| **OldProject pipeline logic** may be tightly coupled to Alpaca | Extract logic into broker-agnostic abstractions during Phase A impl | devin-dev |
| **OpenClaw removal** may have hidden dependencies | Comprehensive inventory + dependency graph in Phase F PRD/arch before touching code | nova-pm, atlas-architect |
| **2-year Discord history** may not exist for all channels | Phase C audit will quantify gaps; backfill tooling as contingency | devin-dev |

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-18 | Build all phases A-F, multi-week timeline | User confirmed "build everything" — drop "go live tomorrow" framing |
| 2026-04-18 | Brokers: Robinhood + IBKR (not Alpaca) | User decision — do not port Alpaca adapter from OldProject |
| 2026-04-18 | Delete OpenClaw after QA sign-off | User confirmed — safe unwinding required, no deletion until review+QA pass |
| 2026-04-18 | Discord flow: verify, don't rewrite | Discord ingestion already DB-backed; user wants audit + confirmation only |
| 2026-04-18 | All phases are must-haves | No fast-follow — ship all phases before go-live |

---

## Next Actions

1. **Immediate (parallel)**: Kick off PRDs for Phases A, B, C, F with nova-pm
2. **After PRD approvals**: Kick off architecture for Phases A, B, C, F with atlas-architect (parallel where possible)
3. **After A-Arch approval**: Kick off Phase D PRD (depends on A architecture for dashboard design)
4. **After all impl+review+QA complete**: Kick off Phase E go-live hardening

---

**Last Updated**: 2026-04-18 (pipeline tracker initialized)
