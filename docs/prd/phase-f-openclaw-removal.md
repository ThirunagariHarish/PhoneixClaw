# PRD: Phase F — OpenClaw Safe Removal

Version: 1.0 | Status: Draft | Date: 2026-04-18 | Author: Nova-PM | Reviewers: atlas-architect, cortex-reviewer, quill-qa

## Problem Statement

OpenClaw is a legacy distributed agent-runtime architecture that the Phoenix Trade Bot platform no longer needs. It remains entangled with the codebase via:

- `openclaw/bridge/` — Bridge Service sidecar
- `services/skill-sync/` — Skill distribution service
- `openclaw/skills/` — Central skill catalog (115+ markdown files)
- `openclaw/configs/` — Agent config templates (SOUL/HEARTBEAT/AGENTS/TOOLS)
- `shared/db/models/openclaw_instance.py` — DB model (already flagged DEPRECATED in V3)
- API routes (`apps/api/src/routes/skills.py`), tests, docs, Makefile targets, docker-compose services, env vars, migrations

Removing OpenClaw reduces maintenance burden, eliminates developer confusion, and unblocks future work. Phase F is a **pure deletion refactor**: no behavior replacement, no new features.

## Goals

1. Complete inventory of every OpenClaw reference (services, DB, API, tests, docs, config, agent tooling).
2. Dependency graph (directed; Mermaid/DOT) showing removal order.
3. Safe phased removal with DB-safe migration.
4. Gate enforcement: cortex-reviewer + quill-qa sign-off before final deletion.
5. Zero regressions (`make go-live-regression` green after each phase and final).
6. No orphaned artifacts (env vars, Make targets, imports, doc links).

## Non-Goals

- Replacing OpenClaw functionality (deletion only)
- Agent runtime changes (Claude Code sessions via AgentGateway remain unchanged)
- New infrastructure
- Phase A/B/C work
- Skill-system redesign

## Inventory Template (filled by Atlas)

### 4.1 Services
| Service Path | Purpose | Depends On | Depended On By | Action |
|---|---|---|---|---|
| `openclaw/bridge/` | Bridge sidecar | `shared/db/models/openclaw_instance.py` | API routes, docker-compose | Delete (4e) |
| `services/skill-sync/` | Skill distribution | `openclaw/skills/`, DB model | Makefile, docker-compose | Delete (4e) |
| `openclaw/skills/` | Skill catalog (115+ files) | None | skill-sync, skills route | Delete (4e) |
| `openclaw/configs/` | Agent config templates | None | Bridge tests, docs | Delete (4e) |

### 4.2 Database
| Table / Column | Created In | FKs | Action |
|---|---|---|---|
| `openclaw_instances` | `001_initial_v2_tables.py` | None (FK removed in V3) | New Alembic migration to DROP (4c) |
| `automations.instance_id` comment | `003_remaining_tables.py` line 59 | None | Update comment (4a) |

### 4.3 API Routes
| Route | File | Action |
|---|---|---|
| `POST /api/v2/skills/sync` | `apps/api/src/routes/skills.py` line 79 | Delete or return 410 (4a) |

### 4.4 Tests
| Path | Action |
|---|---|
| `openclaw/bridge/tests/**` | Delete with `openclaw/bridge/` (4e) |
| `tests/regression/test_skill_sync_regression.py` | Delete (4d) |
| `openclaw/configs/tests/**` | Delete with `openclaw/configs/` (4e) |

### 4.5 Documentation
| Doc | Action |
|---|---|
| `docs/operations/OPENCLAW_SETUP_GUIDE.md` | Delete (4d) |
| `docs/operations/OPENCLAW_AGENT_LOGS.md` | Delete (4d) |
| `docs/adrs/003-openclaw-bridge-pattern.md` | Mark SUPERSEDED (4d) |
| `docs/development/skill-development-guide.md` | Remove OpenClaw sync sections (4d) |
| `docs/operations/configuration-guide.md` | Remove BRIDGE_* env var sections (4d) |
| `docs/prd/PRD.md` | Update references (4d) |

### 4.6 Configuration
| Location | Item | Action |
|---|---|---|
| `.env.example` line 26 | `BRIDGE_TOKEN` | Delete (4a) |
| `Makefile` lines 7, 34, 46, 127 | `run-bridge`, `test-bridge`, `LOCAL_BRIDGE` | Delete (4a) |
| `docker-compose.yml` lines 46–59 | `phoenix-bridge` service | Delete (4b) |
| `infra/docker-compose.production.yml` | Any bridge refs | Delete (4b) |
| `CLAUDE.md` line 27 | `openclaw/bridge/` reference | Remove line (4a) |

### 4.7 Agent Tooling
Grep `agents/` for OpenClaw references; update or remove any CLAUDE.md or tool scripts that assume OpenClaw.

### 4.8 Infra & Scripts
| File | Action |
|---|---|
| `infra/scripts/deploy-openclaw.sh` | Delete (4d) |
| `infra/scripts/provision-local-node.sh` | Remove OpenClaw sections (4d) |
| `infra/scripts/sync-skills.sh` | Delete (4d) |
| `infra/systemd/bridge.service` | Delete (4d) |
| `infra/systemd/openclaw.service` | Delete (4d) |
| `infra/observability/grafana/openclaw-instances.json` | Delete (4d) |
| `infra/wireguard/client.conf.template` | Mark deprecated (4d) |
| `scripts/register_openclaw_instance.py` | Delete (4d) |

## Dependency Graph (filled by Atlas)

Atlas produces a Mermaid or DOT graph with nodes = services/tables/routes/tests/docs/config, edges = "depends on" / "is called by", and a topological ordering that guarantees no orphan dependencies during removal.

## Phased Removal Plan

### Phase 4a: Deprecate Routes & Config
- Mark `POST /api/v2/skills/sync` deprecated (410 Gone) or remove
- Remove `BRIDGE_TOKEN`, `BRIDGE_URL` from `.env.example`
- Remove `run-bridge`, `test-bridge`, `LOCAL_BRIDGE` from Makefile
- Remove `openclaw/bridge/` from `CLAUDE.md`
- Update migration comment line 59

**Gate:** code review + unit tests green.

### Phase 4b: Remove Bridge Service
- Delete `phoenix-bridge` service block in `docker-compose.yml`
- Delete production bridge service if present
- Stop running containers

**Gate:** `make dev-run` + `make test` green.

### Phase 4c: Drop DB Table
- New Alembic migration: `DROP TABLE openclaw_instances`
- Downgrade recreates table
- Remove OpenClaw import from `shared/db/migrations/env.py` line 15

**Gate:** `make db-upgrade` + `make db-downgrade` succeed; integration tests green.

### Phase 4d: Delete Tests, Docs, Infra Scripts
- Delete files listed in §4.4–4.8 with "Delete (4d)"
- Update docs marked with "Mark SUPERSEDED" or "Remove sections"

**Gate:** `make test`, `make test-integration`, `make test-dashboard` all green; no broken links.

### Phase 4e: Final Directory Deletion
- Delete directories: `openclaw/bridge/`, `openclaw/configs/`, `openclaw/skills/`, `services/skill-sync/`
- Delete `shared/db/models/openclaw_instance.py`
- Grep entire codebase for residuals:
  - `rg -i "openclaw|bridge.*token|skill.*sync" --type py --type md --type yml`
- Remove any surviving imports, comments, env defaults

**Gate: cortex-reviewer + quill-qa full regression MUST pass before this commit is merged.**

## Acceptance Criteria

1. Atlas completes the inventory (all TBD cells filled).
2. Atlas produces the dependency graph.
3. Each phase (4a–4e) is committed and regression-green before the next.
4. No env var, Makefile target, import, or doc references OpenClaw after 4e.
5. `rg -i "openclaw|bridge.*token|skill.*sync"` returns zero results in `apps/`, `services/`, `shared/`, `tests/` (migrations and git history excluded).
6. `openclaw_instances` table does not exist post-4c; downgrade path verified.
7. `openclaw/`, `services/skill-sync/`, `shared/db/models/openclaw_instance.py` do not exist post-4e.
8. `make go-live-regression` green after 4e.
9. cortex-reviewer + quill-qa sign-offs recorded on the deletion PR.

## User Stories (internal)

1. **Developer**: cloning the repo, I see no OpenClaw references — no confusion about the agent runtime.
2. **Developer**: `make dev-run` starts only active services; no dead containers.
3. **QA**: no skipped tests for deleted services; full confidence in coverage.
4. **DevOps**: `.env.example` contains only active vars.
5. **New contributor**: docs reflect Claude Code agent runtime, not legacy VPS system.

## Risks

| # | Risk | Mitigation |
|---|---|---|
| F-R1 | Hidden consumer of an OpenClaw route/table | Atlas must grep exhaustively + user confirmation that OpenClaw is fully deprecated in production before 4e |
| F-R2 | FK violations on table drop | Migration 007 already removed FK; verify with `\d automations` before writing 4c migration |
| F-R3 | Breaking an undocumented feature | If skills still used, replace API stub with new mechanism *before* Phase F — out-of-scope escalation |
| F-R4 | Test import errors after deletion | Phase 4d removes test files; Phase 4e grep enforces no surviving imports; run lint + typecheck after each phase |
| F-R5 | Compose fails without bridge dependency | Verify with `docker compose config` before merging 4b |
| F-R6 | Alembic multi-head from concurrent migrations | `make db-alembic-heads` check; coordinate branch order |
| F-R7 | Docs link rot | Link validator + manual spot-check in 4d |

## Pre-Start User Confirmation

Before Phase F kickoff, the user must confirm:
1. No OpenClaw instances are actively running in production.
2. No active agents depend on OpenClaw-distributed skills.
3. No critical Bridge Service functionality must be preserved.

Any "yes" → STOP and surface as blocker.

## Open Questions for Atlas

1. Does any OpenClaw feature need to be ported to Claude Code runtime before removal?
2. Safest DB table drop order if hidden FK references exist?
3. Deprecation window (routes return 410 for a sprint) or immediate delete?
4. Any production deployments (VPS, AWS) running OpenClaw instances to decommission first?
5. Archive `openclaw/skills/` to `docs/archive/skills/` or delete outright?
6. Any agents in `agents/` dependent on OpenClaw-specific tooling/config?

## Out of Scope

- Pipeline Engine (Phase A)
- AI Flow (Phase B)
- Backtesting (Phase C)
- Pipeline Dashboard (Phase D)
- Go-Live Hardening (Phase E)
- Skill-system redesign (potential future phase)
- Agent runtime migration
- Performance optimization
- New documentation (only update/delete existing)

## Success Metrics

| Metric | Target | Measurement |
|---|---|---|
| Regression pass rate | 100% after each phase | CI |
| `rg -i openclaw` in active code | 0 | ripgrep |
| Docker services | -1 (phoenix-bridge removed) | `docker compose config` |
| Env vars | -2 (`BRIDGE_TOKEN`, `BRIDGE_URL`) | `.env.example` |
| Makefile targets | -2 (`run-bridge`, `test-bridge`) | `make help` |
| Directories removed | `openclaw/` gone | `ls openclaw/` errors |
| DB tables | `openclaw_instances` dropped | `\dt` |

## Rollback Plan

- 4a–4d: `git revert` (no DB changes yet)
- 4c: `make db-downgrade` recreates table
- 4e: `git checkout main~1 -- openclaw/ services/skill-sync/`
- Full rollback trigger: regression failure, production incident traced to Phase F, or user report of lost feature.

## Timeline (rough)

| Phase | Owner | Estimate |
|---|---|---|
| Inventory + graph | atlas-architect | 2–3h |
| Architecture review | cortex-reviewer | 1h |
| 4a routes/config | build | 1h |
| 4b bridge service | build | 0.5h |
| 4c DB migration | build | 1h |
| 4d tests/docs/scripts | build | 2h |
| 4e directory deletion | build | 1h |
| Final regression | quill-qa | 1h |
| Sign-off | Nova-PM | 0.25h |

**Total: ~8–10h engineering work across 5 phases.**

## Handoff to Atlas

Atlas delivers: full inventory (every TBD cell filled), dependency graph (Mermaid/DOT), architecture doc with detailed removal sequence, FK analysis, risk assessment, and migration file skeleton.
