# Project Phoenix v2 — Implementation Plan

**Version:** 1.1.0
**Date:** March 3, 2026
**Status:** Draft
**Reference:** [PRD v2.1.0](PRD.md) · [Architecture Plan](ArchitecturePlan.md) · [Milestones](Milestones.md)

---

## Table of Contents

1. [Development Philosophy & Standards](#1-development-philosophy--standards)
2. [Monorepo Folder Structure](#2-monorepo-folder-structure)
3. [TDD Workflow per Service Type](#3-tdd-workflow-per-service-type)
4. [Regression Suite Architecture](#4-regression-suite-architecture)
5. [Phase 1 Implementation Details (M1.1–M1.13)](#5-phase-1-implementation-details-m11m113)
6. [Phase 2 Implementation Details (M2.1–M2.15)](#6-phase-2-implementation-details-m21m215)
7. [Phase 3 Implementation Details (M3.1–M3.14)](#7-phase-3-implementation-details-m31m314)
8. [Configuration Guide](#8-configuration-guide)
9. [Project README Specification](#9-project-readme-specification)
10. [Code Documentation Standards](#10-code-documentation-standards)
11. [Milestone Completion Protocol](#11-milestone-completion-protocol)
12. [Existing Code Reuse & Migration Plan](#12-existing-code-reuse--migration-plan)
13. [Hybrid Local + VPS Node Architecture](#13-hybrid-local--vps-node-architecture)

---

## 1. Development Philosophy & Standards

### 1.1 TDD Red-Green-Refactor

Every piece of production code in Phoenix v2 follows the TDD cycle:

```
1. RED    — Write a failing test that describes the desired behavior
2. GREEN  — Write the minimum code to make the test pass
3. REFACTOR — Clean up the code while keeping all tests green
```

**Non-negotiable rules:**
- No production code is written without a corresponding test that was written first.
- Tests must fail before the production code exists (verify the RED step).
- Each commit either adds a test (RED) or makes a test pass (GREEN). Refactor commits are separate.
- Pull requests must include test evidence: screenshot of test output or CI link showing green.

### 1.2 Testing Pyramid

```
         ┌───────┐
         │  E2E  │  10% — Playwright browser tests (critical user flows)
         │  (10) │
        ┌┴───────┴┐
        │Integration│  20% — Service-to-service, API contract, DB tests
        │   (20)    │
       ┌┴───────────┴┐
       │    Unit      │  70% — Pure function, handler, component tests
       │    (70)      │
       └──────────────┘
```

| Layer | Tool (Python) | Tool (TypeScript) | Target |
|---|---|---|---|
| Unit | pytest + pytest-asyncio + pytest-mock | vitest + React Testing Library | 70% of total tests |
| Integration | pytest + httpx.AsyncClient + testcontainers | vitest + MSW (Mock Service Worker) | 20% of total tests |
| E2E | N/A | Playwright | 10% of total tests |
| Load | Locust | k6 (optional) | Per milestone where applicable |

### 1.3 Coverage Gates

| Scope | Minimum Coverage | Tool |
|---|---|---|
| Python backend (new code) | 90% line coverage | pytest-cov + Codecov |
| TypeScript frontend (new code) | 85% branch coverage | vitest + Istanbul (v8) |
| Overall project | 85% | Codecov aggregate |
| Per-PR diff | 90% of changed lines | Codecov PR check |

Coverage is enforced in CI. A PR cannot merge if new code drops below the gate.

### 1.4 Design Patterns by Layer

| Layer | Pattern | Usage |
|---|---|---|
| Data Access | **Repository** | Every database table gets a repository class that encapsulates all queries. Services never write raw SQL or call `session.execute()` directly. |
| Business Logic | **Service** | Each domain (agents, trades, positions, skills) has a service class that orchestrates repository calls, validation, and event publishing. |
| Connectors / Brokers | **Factory + Strategy** | `ConnectorFactory.create("discord", config)` returns a `BaseConnector` implementation. Broker selection uses the same pattern. |
| Risk Checks | **Chain of Responsibility** | Three risk check layers (agent → execution → global) are chained. Each layer can pass or reject. |
| Agent Lifecycle | **State Machine** | Agent status transitions enforced by a state machine class. Invalid transitions raise exceptions. Tests cover every edge. |
| Event Bus | **Observer / Pub-Sub** | Services register as consumers for specific stream topics. New consumers can be added without modifying publishers. |
| API Routes | **Controller → Service → Repository** | Routes validate input (Pydantic), call service, return response model. No business logic in routes. |
| Frontend Components | **Compound Component** | Complex UI (DataTable, FormBuilder) built as compound components with context. |
| Frontend State | **React Query + Context** | Server state managed by TanStack React Query. Client state by React Context. No Redux. |
| Config / Secrets | **Centralized Config** | Single `Settings` class per service using pydantic-settings. All config from env vars. |

### 1.5 Code Quality Tooling

**Python:**

| Tool | Purpose | Config |
|---|---|---|
| ruff | Linter + formatter (replaces flake8 + isort + black) | `pyproject.toml [tool.ruff]` |
| mypy | Static type checking (strict mode) | `pyproject.toml [tool.mypy]` |
| pytest | Test runner | `pyproject.toml [tool.pytest]` |
| pytest-cov | Coverage reporting | `--cov=shared --cov=services --cov-report=xml` |
| pre-commit | Git hooks for lint + format on commit | `.pre-commit-config.yaml` |
| bandit | Security linter (optional, run in CI) | `.bandit.yml` |

**TypeScript:**

| Tool | Purpose | Config |
|---|---|---|
| eslint | Linter (strict TypeScript rules) | `eslint.config.js` |
| prettier | Formatter | `.prettierrc` |
| tsc --noEmit | Type checking | `tsconfig.json (strict: true)` |
| vitest | Unit + integration tests | `vitest.config.ts` |
| Playwright | E2E browser tests | `playwright.config.ts` |
| husky + lint-staged | Pre-commit hooks | `package.json` |

### 1.6 Commit Conventions

All commits follow Conventional Commits:

```
<type>(<scope>): <short description>

Types: feat, fix, test, refactor, docs, chore, ci, perf
Scopes: api, dashboard, auth, execution, bridge, orchestrator, connectors,
        backtest, skills, automation, agent-comm, global-monitor, ws-gateway,
        shared, infra, ci, docs
```

Examples:
- `test(api): add agent CRUD endpoint contract tests`
- `feat(api): implement agent creation with Bridge Service call`
- `fix(execution): prevent duplicate trade intent processing`
- `docs(readme): add Quick Start section for Phase 1`

### 1.7 Branch Strategy

```
main ─────────────────────────────────────── production
  │
  ├── milestone/m1.1-repo-scaffolding
  ├── milestone/m1.2-infrastructure
  ├── milestone/m1.3-auth-service
  ...
```

One branch per milestone. PRs merge into `main` when all acceptance criteria and regression tests pass. Feature branches within milestones are optional for parallelism.

---

## 2. Monorepo Folder Structure

The folder structure directly mirrors the Architecture Plan service registry and PRD Section 17.1.

```
phoenix-v2/
│
├── apps/
│   ├── dashboard/                          # React 18 + Vite 5 + TypeScript
│   │   ├── public/
│   │   │   ├── manifest.json              # PWA manifest (M3.10)
│   │   │   ├── sw.js                      # Service Worker (M3.10)
│   │   │   └── icons/
│   │   ├── src/
│   │   │   ├── components/
│   │   │   │   ├── ui/                    # 19 Radix UI primitives (carried from v1)
│   │   │   │   │   ├── button.tsx
│   │   │   │   │   ├── card.tsx
│   │   │   │   │   ├── dialog.tsx
│   │   │   │   │   ├── dropdown-menu.tsx
│   │   │   │   │   ├── input.tsx
│   │   │   │   │   ├── label.tsx
│   │   │   │   │   ├── popover.tsx
│   │   │   │   │   ├── scroll-area.tsx
│   │   │   │   │   ├── select.tsx
│   │   │   │   │   ├── separator.tsx
│   │   │   │   │   ├── sheet.tsx
│   │   │   │   │   ├── skeleton.tsx
│   │   │   │   │   ├── switch.tsx
│   │   │   │   │   ├── table.tsx
│   │   │   │   │   ├── tabs.tsx
│   │   │   │   │   ├── textarea.tsx
│   │   │   │   │   ├── tooltip.tsx
│   │   │   │   │   ├── badge.tsx
│   │   │   │   │   └── avatar.tsx
│   │   │   │   ├── composite/             # Higher-order components
│   │   │   │   │   ├── data-table.tsx     # Sortable, filterable, paginated
│   │   │   │   │   ├── flex-card.tsx      # Agent/strategy summary card
│   │   │   │   │   ├── metric-card.tsx    # Single metric with sparkline
│   │   │   │   │   ├── status-badge.tsx   # Green/yellow/red with pulse
│   │   │   │   │   ├── side-panel.tsx     # Slide-out detail panel
│   │   │   │   │   ├── form-builder.tsx   # Dynamic forms from JSON schema
│   │   │   │   │   ├── confirm-dialog.tsx
│   │   │   │   │   ├── empty-state.tsx
│   │   │   │   │   └── toast.tsx          # Sonner notifications
│   │   │   │   ├── agents/                # Agent-specific components
│   │   │   │   ├── charts/                # Recharts, TradingView wrappers
│   │   │   │   ├── connectors/            # Connector config forms
│   │   │   │   ├── layout/                # AppShell, Sidebar, BottomNav
│   │   │   │   └── shared/                # ThemeProvider, ErrorBoundary
│   │   │   ├── pages/                     # One file per dashboard tab
│   │   │   │   ├── trades.tsx
│   │   │   │   ├── positions.tsx
│   │   │   │   ├── performance.tsx
│   │   │   │   ├── agents.tsx
│   │   │   │   ├── strategies.tsx
│   │   │   │   ├── connectors.tsx
│   │   │   │   ├── skills.tsx
│   │   │   │   ├── market-command-center.tsx
│   │   │   │   ├── admin.tsx
│   │   │   │   ├── agent-network.tsx
│   │   │   │   ├── task-board.tsx
│   │   │   │   ├── settings.tsx
│   │   │   │   └── login.tsx
│   │   │   ├── hooks/                     # Custom React hooks
│   │   │   │   ├── use-agents.ts
│   │   │   │   ├── use-trades.ts
│   │   │   │   ├── use-positions.ts
│   │   │   │   ├── use-websocket.ts
│   │   │   │   └── use-auth.ts
│   │   │   ├── context/                   # React Context providers
│   │   │   │   ├── auth-context.tsx
│   │   │   │   ├── theme-context.tsx
│   │   │   │   └── websocket-context.tsx
│   │   │   ├── api/                       # Centralized API client
│   │   │   │   ├── client.ts              # Axios instance with interceptors
│   │   │   │   ├── agents.ts
│   │   │   │   ├── trades.ts
│   │   │   │   ├── positions.ts
│   │   │   │   ├── connectors.ts
│   │   │   │   ├── skills.ts
│   │   │   │   ├── performance.ts
│   │   │   │   └── admin.ts
│   │   │   ├── types/                     # TypeScript interfaces
│   │   │   │   ├── agent.ts
│   │   │   │   ├── trade.ts
│   │   │   │   ├── position.ts
│   │   │   │   ├── connector.ts
│   │   │   │   └── common.ts
│   │   │   ├── lib/
│   │   │   │   └── utils.ts               # cn() utility (carried from v1)
│   │   │   ├── App.tsx
│   │   │   └── main.tsx
│   │   ├── tests/
│   │   │   ├── unit/                      # Vitest component tests
│   │   │   │   ├── components/
│   │   │   │   │   ├── ui/
│   │   │   │   │   └── composite/
│   │   │   │   ├── hooks/
│   │   │   │   └── pages/
│   │   │   ├── integration/               # MSW API integration tests
│   │   │   └── e2e/                       # Playwright browser tests
│   │   │       ├── auth.spec.ts
│   │   │       ├── trades.spec.ts
│   │   │       ├── agents.spec.ts
│   │   │       └── ...
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   ├── vitest.config.ts
│   │   ├── playwright.config.ts
│   │   ├── tailwind.config.ts
│   │   ├── tsconfig.json
│   │   ├── eslint.config.js
│   │   ├── postcss.config.js
│   │   ├── Dockerfile
│   │   ├── nginx.conf
│   │   └── README.md
│   │
│   └── api/                               # FastAPI Backend API
│       ├── src/
│       │   ├── main.py                    # FastAPI app, lifespan, CORS
│       │   ├── config.py                  # pydantic-settings Settings class
│       │   ├── deps.py                    # Dependency injection (get_db, get_redis, get_current_user)
│       │   ├── routes/
│       │   │   ├── __init__.py
│       │   │   ├── auth.py
│       │   │   ├── agents.py
│       │   │   ├── strategies.py
│       │   │   ├── trades.py
│       │   │   ├── positions.py
│       │   │   ├── connectors.py
│       │   │   ├── skills.py
│       │   │   ├── instances.py
│       │   │   ├── backtests.py
│       │   │   ├── performance.py
│       │   │   ├── tasks.py
│       │   │   ├── automations.py
│       │   │   ├── admin.py
│       │   │   ├── dev.py
│       │   │   ├── network.py
│       │   │   └── ws.py                  # WebSocket endpoints
│       │   ├── services/                  # Business logic (Service pattern)
│       │   │   ├── agent_service.py
│       │   │   ├── trade_service.py
│       │   │   ├── position_service.py
│       │   │   ├── connector_service.py
│       │   │   ├── skill_service.py
│       │   │   ├── backtest_service.py
│       │   │   ├── performance_service.py
│       │   │   ├── task_service.py
│       │   │   ├── automation_service.py
│       │   │   └── instance_service.py
│       │   ├── repositories/              # Data access (Repository pattern)
│       │   │   ├── agent_repo.py
│       │   │   ├── trade_repo.py
│       │   │   ├── position_repo.py
│       │   │   ├── connector_repo.py
│       │   │   ├── skill_repo.py
│       │   │   ├── backtest_repo.py
│       │   │   ├── task_repo.py
│       │   │   ├── automation_repo.py
│       │   │   ├── user_repo.py
│       │   │   └── audit_repo.py
│       │   ├── schemas/                   # Pydantic request/response models
│       │   │   ├── agent.py
│       │   │   ├── trade.py
│       │   │   ├── position.py
│       │   │   ├── connector.py
│       │   │   ├── skill.py
│       │   │   ├── backtest.py
│       │   │   ├── task.py
│       │   │   ├── user.py
│       │   │   └── common.py
│       │   └── middleware/
│       │       ├── auth.py                # JWT validation middleware
│       │       ├── rate_limit.py
│       │       └── logging.py
│       ├── tests/
│       │   ├── unit/
│       │   │   ├── test_agent_service.py
│       │   │   ├── test_trade_service.py
│       │   │   ├── test_risk_checks.py
│       │   │   └── ...
│       │   ├── integration/
│       │   │   ├── test_agent_routes.py
│       │   │   ├── test_trade_routes.py
│       │   │   └── ...
│       │   └── conftest.py                # Fixtures: test DB, test Redis, test client
│       ├── Dockerfile
│       ├── requirements.txt
│       └── README.md
│
├── services/
│   ├── orchestrator/                      # BullMQ job queue worker
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── workers/
│   │   │   │   ├── agent_lifecycle.py     # State machine transitions
│   │   │   │   ├── backtest_dispatch.py
│   │   │   │   ├── skill_sync_dispatch.py
│   │   │   │   └── heartbeat_collector.py
│   │   │   └── state_machine.py           # AgentStateMachine class
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   │   ├── test_state_machine.py
│   │   │   │   └── test_workers.py
│   │   │   └── integration/
│   │   ├── Dockerfile
│   │   └── README.md
│   │
│   ├── execution/                         # Trade execution + risk checks
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── consumer.py                # Redis Streams consumer
│   │   │   ├── risk/
│   │   │   │   ├── agent_risk.py          # Agent-level risk checks
│   │   │   │   ├── execution_risk.py      # Execution-level validation
│   │   │   │   ├── global_risk.py         # Account-level circuit breaker
│   │   │   │   └── chain.py              # Chain of Responsibility orchestrator
│   │   │   ├── executor.py                # Broker order placement
│   │   │   └── dedup.py                   # Idempotency by trade intent ID
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   │   ├── test_agent_risk.py
│   │   │   │   ├── test_execution_risk.py
│   │   │   │   ├── test_global_risk.py
│   │   │   │   ├── test_chain.py
│   │   │   │   ├── test_dedup.py
│   │   │   │   └── test_executor.py
│   │   │   └── integration/
│   │   │       └── test_execution_pipeline.py
│   │   ├── Dockerfile
│   │   └── README.md
│   │
│   ├── global-monitor/                    # Portfolio-level risk monitor
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── monitor.py                 # Position aggregation, exposure tracking
│   │   │   ├── circuit_breaker.py         # CLOSED / HALF_OPEN / OPEN states
│   │   │   └── kill_switch.py             # Emergency close all positions
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   │   ├── test_circuit_breaker.py
│   │   │   │   └── test_kill_switch.py
│   │   │   └── integration/
│   │   ├── Dockerfile
│   │   └── README.md
│   │
│   ├── connector-manager/                 # Data source + broker connector lifecycle
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── base.py                    # BaseConnector ABC
│   │   │   ├── factory.py                 # ConnectorFactory
│   │   │   ├── router.py                  # Message normalization + routing
│   │   │   ├── connectors/
│   │   │   │   ├── discord.py
│   │   │   │   ├── reddit.py
│   │   │   │   ├── twitter.py
│   │   │   │   ├── unusual_whales.py
│   │   │   │   ├── news_api.py
│   │   │   │   ├── finnhub.py
│   │   │   │   └── webhook.py
│   │   │   └── brokers/
│   │   │       ├── base.py                # BaseBroker ABC
│   │   │       ├── alpaca.py
│   │   │       ├── ibkr.py
│   │   │       ├── robinhood.py
│   │   │       └── tradier.py
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   │   ├── test_discord_connector.py
│   │   │   │   ├── test_alpaca_broker.py
│   │   │   │   ├── test_factory.py
│   │   │   │   └── test_router.py
│   │   │   └── integration/
│   │   ├── Dockerfile
│   │   └── README.md
│   │
│   ├── backtest-runner/                   # Sandboxed backtest execution
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── sandbox.py                 # Docker-in-Docker execution
│   │   │   ├── data_loader.py             # Historical data fetcher + cache
│   │   │   ├── simulation.py              # Signal-driven, heartbeat-driven engines
│   │   │   ├── metrics.py                 # 15 metric calculations
│   │   │   └── report.py                  # JSON + equity curve + trade log generation
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   │   ├── test_metrics.py        # Test every metric formula
│   │   │   │   ├── test_simulation.py
│   │   │   │   └── test_data_loader.py
│   │   │   └── integration/
│   │   │       └── test_backtest_pipeline.py
│   │   ├── Dockerfile
│   │   └── README.md
│   │
│   ├── skill-sync/                        # Central skill repository sync
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── watcher.py                 # MinIO bucket change detection
│   │   │   ├── distributor.py             # Push skills to Bridge Services
│   │   │   └── versioning.py              # Skill version tracking, rollback
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   │   ├── test_versioning.py
│   │   │   │   └── test_distributor.py
│   │   │   └── integration/
│   │   ├── Dockerfile
│   │   └── README.md
│   │
│   ├── automation/                        # Automation scheduler
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── scheduler.py               # Cron expression parser + scheduler
│   │   │   ├── nl_parser.py               # NL to cron conversion (LLM-based)
│   │   │   └── executor.py                # Task creation + channel delivery
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   │   ├── test_scheduler.py
│   │   │   │   └── test_nl_parser.py
│   │   │   └── integration/
│   │   ├── Dockerfile
│   │   └── README.md
│   │
│   ├── agent-comm/                        # Inter-agent communication router
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── router.py                  # Message routing (same/cross instance)
│   │   │   ├── patterns/
│   │   │   │   ├── request_response.py
│   │   │   │   ├── broadcast.py
│   │   │   │   ├── pubsub.py
│   │   │   │   ├── chain.py
│   │   │   │   └── consensus.py           # Quorum voting
│   │   │   └── protocol.py               # Message schema + validation
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   │   ├── test_router.py
│   │   │   │   ├── test_consensus.py
│   │   │   │   └── test_protocol.py
│   │   │   └── integration/
│   │   ├── Dockerfile
│   │   └── README.md
│   │
│   └── ws-gateway/                        # WebSocket gateway
│       ├── src/
│       │   ├── main.py
│       │   ├── channels.py                # Channel management (trades, positions, heartbeats)
│       │   └── broadcaster.py             # Redis pub/sub to WebSocket push
│       ├── tests/
│       │   ├── unit/
│       │   └── integration/
│       ├── Dockerfile
│       └── README.md
│
├── openclaw/
│   ├── bridge/                            # Bridge Service sidecar
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── agent_manager.py           # CRUD operations on agent workspaces
│   │   │   ├── heartbeat.py               # Collect heartbeat data
│   │   │   ├── skill_sync.py              # Pull skills from MinIO
│   │   │   └── auth.py                    # X-Bridge-Token validation
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   │   ├── test_agent_manager.py
│   │   │   │   ├── test_heartbeat.py
│   │   │   │   └── test_auth.py
│   │   │   └── integration/
│   │   ├── Dockerfile
│   │   └── README.md
│   │
│   ├── configs/                           # Base agent configuration templates
│   │   ├── strategy-lab/
│   │   │   ├── AGENTS.md
│   │   │   ├── TOOLS.md
│   │   │   └── SOUL.md
│   │   ├── data-research/
│   │   ├── promotion-risk/
│   │   └── live-trading/
│   │
│   └── skills/                            # Central skill repository (synced to MinIO)
│       ├── data/
│       │   ├── market-data-fetch/SKILL.md
│       │   ├── news-aggregator/SKILL.md
│       │   ├── options-chain-lookup/SKILL.md
│       │   └── ...                        # 15 data skills total
│       ├── analysis/
│       │   ├── technical-indicator-suite/SKILL.md
│       │   ├── support-resistance-finder/SKILL.md
│       │   └── ...                        # 15 analysis skills total
│       ├── strategy/
│       │   ├── momentum-scalp/SKILL.md
│       │   └── ...                        # 20 strategy skills total
│       ├── execution/
│       │   ├── order-builder-stock/SKILL.md
│       │   └── ...                        # 13 execution skills total
│       ├── risk/
│       │   ├── stop-loss-calculator/SKILL.md
│       │   └── ...                        # 12 risk skills total
│       ├── utility/
│       │   ├── portfolio-report-gen/SKILL.md
│       │   └── ...                        # 15 utility skills total
│       └── advanced/
│           ├── ml-feature-engineer/SKILL.md
│           └── ...                        # 15 advanced skills total
│
├── shared/                                # Shared Python libraries
│   ├── db/
│   │   ├── __init__.py
│   │   ├── engine.py                      # Async engine + session factory
│   │   ├── models/                        # SQLAlchemy 2 ORM models
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── trading_account.py
│   │   │   ├── openclaw_instance.py
│   │   │   ├── agent.py
│   │   │   ├── agent_backtest.py
│   │   │   ├── skill.py
│   │   │   ├── trade_intent.py
│   │   │   ├── position.py
│   │   │   ├── connector.py
│   │   │   ├── api_key_entry.py
│   │   │   ├── task.py
│   │   │   ├── automation.py
│   │   │   ├── dev_incident.py
│   │   │   ├── agent_message.py
│   │   │   ├── agent_log.py
│   │   │   └── audit_log.py
│   │   └── migrations/                    # Alembic
│   │       ├── alembic.ini
│   │       ├── env.py
│   │       └── versions/
│   ├── events/
│   │   ├── __init__.py
│   │   ├── bus.py                         # Redis Streams publisher + consumer
│   │   ├── schemas.py                     # Event envelope schema
│   │   └── topics.py                      # Stream topic constants
│   ├── crypto/
│   │   ├── __init__.py
│   │   └── credentials.py                # Fernet encrypt/decrypt (from v1)
│   ├── broker/
│   │   ├── __init__.py
│   │   ├── protocol.py                   # BaseBroker protocol (from v1)
│   │   ├── alpaca.py                     # Alpaca adapter (from v1)
│   │   ├── circuit_breaker.py            # Per-account breaker (from v1)
│   │   └── factory.py                    # BrokerFactory
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── retry.py                      # Exponential backoff (from v1)
│   │   ├── dedup.py                      # Deduplication (from v1)
│   │   ├── rate_limiter.py               # Rate limiting (from v1)
│   │   ├── feature_flags.py              # Feature flags (from v1)
│   │   ├── graceful_shutdown.py          # Signal handlers (from v1)
│   │   └── market_calendar.py            # Market hours + holidays (from v1)
│   ├── nlp/                              # Kept from v1, also converted to skills
│   │   ├── sentiment.py
│   │   └── ticker_extractor.py
│   ├── whatsapp/
│   │   └── sender.py                     # Meta Cloud API (from v1)
│   └── discord_utils/
│       └── channel_discovery.py          # Channel discovery (from v1)
│
├── infra/
│   ├── docker/
│   │   ├── docker-compose.yml            # Full local development stack
│   │   ├── docker-compose.dev.yml        # Infrastructure only (Postgres, Redis, MinIO)
│   │   └── docker-compose.coolify.yml    # Production deployment
│   ├── wireguard/
│   │   ├── server.conf.template          # Coolify server WireGuard config
│   │   └── client.conf.template          # OpenClaw VPS WireGuard config
│   ├── nginx/
│   │   └── nginx.conf                    # Reverse proxy config
│   ├── prometheus/
│   │   └── prometheus.yml                # Scrape configs
│   ├── grafana/
│   │   └── dashboards/                   # 7 pre-built dashboard JSON files
│   ├── scripts/
│   │   ├── deploy-openclaw.sh            # OpenClaw VPS provisioning
│   │   ├── sync-skills.sh                # Cron skill sync script
│   │   ├── health-check.sh               # Instance health verification
│   │   ├── db-backup.sh                  # PostgreSQL backup
│   │   └── seed-db.sh                    # Seed default data
│   └── k8s/                              # Kubernetes manifests (optional)
│       └── ...
│
├── tests/
│   ├── regression/                        # Cross-service regression suites
│   │   ├── conftest.py                    # Shared fixtures for regression
│   │   ├── test_auth_regression.py
│   │   ├── test_agent_lifecycle_regression.py
│   │   ├── test_trade_execution_regression.py
│   │   ├── test_connector_regression.py
│   │   ├── test_event_bus_regression.py
│   │   └── test_heartbeat_regression.py
│   ├── e2e/
│   │   ├── playwright.config.ts
│   │   ├── auth.spec.ts
│   │   ├── trades-tab.spec.ts
│   │   ├── agents-tab.spec.ts
│   │   ├── performance-tab.spec.ts
│   │   └── ...                            # One spec per tab
│   └── load/
│       ├── locustfile.py                  # API load tests
│       └── ws_load.py                     # WebSocket load tests
│
├── docs/
│   ├── user-guide.md                      # Dashboard walkthrough
│   ├── api-reference.md                   # Generated from OpenAPI
│   ├── operations-guide.md                # Deployment, monitoring, incident response
│   ├── skill-development-guide.md         # How to create skills
│   └── adrs/                              # Architecture Decision Records
│       ├── 001-redis-streams-over-nats.md
│       ├── 002-queue-based-execution.md
│       └── ...
│
├── .github/
│   └── workflows/
│       ├── ci.yml                         # Lint → Test → Build
│       ├── cd.yml                         # Deploy on tag
│       └── nightly.yml                    # Full regression suite
│
├── .pre-commit-config.yaml
├── .env.example
├── pyproject.toml
├── Makefile
└── README.md
```

### 2.1 Naming Conventions

| Context | Convention | Example |
|---|---|---|
| Python files | snake_case | `agent_service.py` |
| Python classes | PascalCase | `AgentService`, `TradeIntentSchema` |
| Python functions | snake_case | `create_agent()`, `get_open_positions()` |
| TypeScript files | kebab-case | `data-table.tsx`, `use-agents.ts` |
| TypeScript components | PascalCase | `DataTable`, `FlexCard` |
| TypeScript hooks | camelCase with `use` prefix | `useAgents()`, `useWebSocket()` |
| API routes | kebab-case plural nouns | `/api/v2/trade-intents`, `/api/v2/agents` |
| Database tables | snake_case plural | `trade_intents`, `agent_backtests` |
| Redis keys | colon-separated | `cache:agents:list`, `stream:trade-intents` |
| Environment variables | SCREAMING_SNAKE_CASE | `DATABASE_URL`, `REDIS_URL` |
| Docker images | kebab-case | `phoenixv2/api`, `phoenixv2/execution` |
| Git branches | kebab-case | `milestone/m1.3-auth-service` |

---

## 3. TDD Workflow per Service Type

### 3.1 Backend Service (Python / FastAPI)

**Layers tested:**

```
Route (API contract) → Service (business logic) → Repository (data access)
```

**Step-by-step TDD flow for a new endpoint:**

```python
# STEP 1: RED — Write the test FIRST

# File: apps/api/tests/integration/test_agent_routes.py

import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_agent_returns_201(
    client: AsyncClient,
    auth_headers: dict,
    sample_agent_payload: dict,
):
    """Creating an agent with valid data returns 201 and the agent object."""
    response = await client.post(
        "/api/v2/agents",
        json=sample_agent_payload,
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == sample_agent_payload["name"]
    assert data["status"] == "CREATED"
    assert "id" in data

@pytest.mark.asyncio
async def test_create_agent_without_auth_returns_401(
    client: AsyncClient,
    sample_agent_payload: dict,
):
    """Creating an agent without auth token returns 401."""
    response = await client.post("/api/v2/agents", json=sample_agent_payload)
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_create_agent_invalid_payload_returns_422(
    client: AsyncClient,
    auth_headers: dict,
):
    """Creating an agent with missing required fields returns 422."""
    response = await client.post(
        "/api/v2/agents",
        json={"name": ""},  # Missing required fields
        headers=auth_headers,
    )
    assert response.status_code == 422
```

```python
# STEP 2: RED — Run tests, confirm failure
# $ pytest apps/api/tests/integration/test_agent_routes.py -v
# FAILED — endpoint does not exist yet

# STEP 3: GREEN — Implement minimum code

# File: apps/api/src/schemas/agent.py
from pydantic import BaseModel, Field

class AgentCreate(BaseModel):
    """Schema for creating a new agent."""
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern="^(trading|strategy|monitoring|task)$")
    instance_id: str
    # ... other required fields

class AgentResponse(BaseModel):
    """Schema for agent API responses."""
    id: str
    name: str
    type: str
    status: str
    # ... other fields

# File: apps/api/src/routes/agents.py
from fastapi import APIRouter, Depends, status
from ..schemas.agent import AgentCreate, AgentResponse
from ..services.agent_service import AgentService
from ..deps import get_agent_service, get_current_user

router = APIRouter(prefix="/api/v2/agents", tags=["agents"])

@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new agent",
    description="Creates a new agent and registers it on the target OpenClaw instance.",
)
async def create_agent(
    payload: AgentCreate,
    service: AgentService = Depends(get_agent_service),
    user = Depends(get_current_user),
) -> AgentResponse:
    return await service.create_agent(payload, user)

# STEP 4: GREEN — Run tests, confirm pass
# STEP 5: REFACTOR — Extract common patterns, add docstrings
```

**Test fixtures (conftest.py):**

```python
# File: apps/api/tests/conftest.py

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from apps.api.src.main import app

@pytest.fixture
async def engine():
    """Create a test database engine using aiosqlite."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()

@pytest.fixture
async def session(engine) -> AsyncSession:
    """Provide a transactional test database session."""
    async with AsyncSession(engine) as session:
        yield session
        await session.rollback()

@pytest.fixture
async def client(engine) -> AsyncClient:
    """Provide an async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

@pytest.fixture
def auth_headers() -> dict:
    """Provide valid JWT auth headers for test user."""
    token = create_test_token(user_id="test-user", role="admin")
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def sample_agent_payload() -> dict:
    """Provide a valid agent creation payload."""
    return {
        "name": "Test Trading Agent",
        "type": "trading",
        "instance_id": "oc-live-trading-01",
        "data_source_config": {"connector_id": "discord-1", "channels": ["options-flow"]},
        "skills": ["market-data-fetch", "technical-indicator-suite", "order-builder-stock"],
        "risk_config": {"stop_loss_pct": 20, "max_position_pct": 10, "daily_loss_limit_pct": 3},
    }
```

### 3.2 Frontend Component (TypeScript / React)

**Step-by-step TDD flow for a new component:**

```typescript
// STEP 1: RED — Write the test FIRST

// File: apps/dashboard/tests/unit/components/composite/data-table.test.tsx

import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DataTable } from "@/components/composite/data-table";

const columns = [
  { key: "name", header: "Name", sortable: true },
  { key: "status", header: "Status", sortable: true },
];

const data = [
  { id: "1", name: "Agent Alpha", status: "RUNNING" },
  { id: "2", name: "Agent Beta", status: "PAUSED" },
  { id: "3", name: "Agent Gamma", status: "ERROR" },
];

describe("DataTable", () => {
  it("renders all rows from data prop", () => {
    render(<DataTable columns={columns} data={data} />);
    expect(screen.getByText("Agent Alpha")).toBeInTheDocument();
    expect(screen.getByText("Agent Beta")).toBeInTheDocument();
    expect(screen.getByText("Agent Gamma")).toBeInTheDocument();
  });

  it("sorts by column when header is clicked", async () => {
    render(<DataTable columns={columns} data={data} />);
    fireEvent.click(screen.getByText("Name"));
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Agent Alpha");
    expect(rows[3]).toHaveTextContent("Agent Gamma");
  });

  it("shows empty state when data is empty", () => {
    render(<DataTable columns={columns} data={[]} emptyMessage="No agents found" />);
    expect(screen.getByText("No agents found")).toBeInTheDocument();
  });

  it("paginates when rows exceed page size", () => {
    const largeData = Array.from({ length: 25 }, (_, i) => ({
      id: String(i),
      name: `Agent ${i}`,
      status: "RUNNING",
    }));
    render(<DataTable columns={columns} data={largeData} pageSize={10} />);
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
  });
});
```

```typescript
// STEP 2: RED — Run tests, confirm failure
// $ npx vitest run tests/unit/components/composite/data-table.test.tsx

// STEP 3: GREEN — Implement the component
// STEP 4: REFACTOR — Extract sub-components (TableHeader, TableRow, Pagination)
```

### 3.3 API Endpoint Contract Tests

For every API endpoint, write a contract test that validates the request/response schema independently of business logic.

```python
# File: apps/api/tests/unit/test_schemas.py

import pytest
from pydantic import ValidationError
from apps.api.src.schemas.agent import AgentCreate

def test_agent_create_valid():
    """Valid payload passes validation."""
    payload = AgentCreate(
        name="Test Agent",
        type="trading",
        instance_id="oc-01",
        data_source_config={"connector_id": "c1"},
        skills=["market-data-fetch"],
        risk_config={"stop_loss_pct": 20},
    )
    assert payload.name == "Test Agent"

def test_agent_create_empty_name_rejected():
    """Empty name raises validation error."""
    with pytest.raises(ValidationError):
        AgentCreate(name="", type="trading", instance_id="oc-01")

def test_agent_create_invalid_type_rejected():
    """Invalid agent type raises validation error."""
    with pytest.raises(ValidationError):
        AgentCreate(name="Test", type="invalid_type", instance_id="oc-01")
```

### 3.4 OpenClaw Skill TDD

Skills are SKILL.md files, not code. Testing validates their structure and expected behavior.

```python
# File: openclaw/skills/tests/test_skill_validation.py

import pytest
import yaml
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent

def get_all_skill_paths():
    """Discover all SKILL.md files in the skill repository."""
    return list(SKILL_DIR.glob("**/SKILL.md"))

@pytest.mark.parametrize("skill_path", get_all_skill_paths())
def test_skill_has_valid_frontmatter(skill_path: Path):
    """Every SKILL.md must have valid YAML frontmatter."""
    content = skill_path.read_text()
    assert content.startswith("---"), f"{skill_path} missing frontmatter"
    end = content.index("---", 3)
    frontmatter = yaml.safe_load(content[3:end])
    assert "name" in frontmatter
    assert "version" in frontmatter
    assert "description" in frontmatter
    assert "category" in frontmatter
    assert frontmatter["category"] in [
        "data", "analysis", "strategy", "execution", "risk", "utility", "advanced"
    ]

@pytest.mark.parametrize("skill_path", get_all_skill_paths())
def test_skill_has_required_sections(skill_path: Path):
    """Every SKILL.md must have Purpose, Inputs, Workflow, Output Format sections."""
    content = skill_path.read_text()
    for section in ["## Purpose", "## Inputs", "## Workflow", "## Output Format"]:
        assert section in content, f"{skill_path} missing {section}"
```

### 3.5 Infrastructure Tests

```python
# File: tests/regression/test_infra_health.py

import pytest
import httpx
import redis.asyncio as redis

@pytest.mark.asyncio
async def test_api_health():
    """Backend API responds to health check."""
    async with httpx.AsyncClient() as client:
        r = await client.get("http://localhost:8011/health")
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_redis_connection():
    """Redis is reachable and responds to PING."""
    r = redis.from_url("redis://localhost:6379")
    assert await r.ping()
    await r.close()

@pytest.mark.asyncio
async def test_postgres_connection():
    """PostgreSQL is reachable and accepts queries."""
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine("postgresql+asyncpg://phoenix:password@localhost:5432/phoenix_v2")
    async with engine.connect() as conn:
        result = await conn.execute("SELECT 1")
        assert result.scalar() == 1
    await engine.dispose()
```

---

## 4. Regression Suite Architecture

### 4.1 Suite Organization

```
tests/regression/
├── conftest.py                             # Shared fixtures
├── test_auth_regression.py                 # 15+ tests
├── test_agent_lifecycle_regression.py      # 20+ tests
├── test_trade_execution_regression.py      # 15+ tests
├── test_connector_regression.py            # 10+ tests
├── test_event_bus_regression.py            # 10+ tests
├── test_heartbeat_regression.py            # 8+ tests
├── test_skill_sync_regression.py           # 8+ tests
├── test_backtest_regression.py             # 10+ tests
├── test_performance_regression.py          # 10+ tests
└── test_admin_regression.py                # 10+ tests

tests/e2e/
├── playwright.config.ts
├── auth.spec.ts                            # Login, logout, MFA, role switching
├── trades-tab.spec.ts                      # View trades, filter, sort, click detail
├── positions-tab.spec.ts                   # View positions, real-time PnL
├── agents-tab.spec.ts                      # Create agent wizard, agent detail
├── strategies-tab.spec.ts                  # Strategy templates, create strategy agent
├── connectors-tab.spec.ts                  # Add/edit/test connectors
├── skills-tab.spec.ts                      # Skill catalog, editor
├── market-command-center.spec.ts           # Widget layout, drag and drop
├── admin-tab.spec.ts                       # User management, API keys, audit
├── agent-network.spec.ts                   # Graph rendering, node click
├── task-board.spec.ts                      # Kanban, task creation, drag
└── mobile.spec.ts                          # Bottom nav, responsive layout
```

### 4.2 Regression Test Design

Each regression test file covers a complete domain flow end-to-end:

```python
# File: tests/regression/test_agent_lifecycle_regression.py

"""
Regression suite for the agent lifecycle state machine.
Covers: create → backtest → review → paper → live → pause → retire
Every milestone that touches agent lifecycle MUST keep these tests green.
"""

import pytest

class TestAgentCreation:
    """Tests for agent creation flow."""

    async def test_create_trading_agent_via_api(self, client, auth_headers):
        """POST /api/v2/agents creates agent in CREATED state."""

    async def test_agent_appears_on_openclaw_instance(self, client, auth_headers, bridge_mock):
        """After creation, Bridge Service confirms agent exists on instance."""

    async def test_monitoring_agent_auto_created(self, client, auth_headers):
        """Creating a trading agent also creates a paired monitoring agent."""

    async def test_create_agent_on_full_instance_rejected(self, client, auth_headers):
        """Cannot create agent on an instance at capacity."""

class TestBacktestFlow:
    """Tests for automatic backtesting on agent creation."""

    async def test_backtest_starts_automatically(self, client, auth_headers):
        """Agent transitions to BACKTESTING after creation."""

    async def test_backtest_progress_streams_to_client(self, ws_client):
        """WebSocket receives backtest progress updates."""

    async def test_backtest_completion_changes_status(self, client, auth_headers):
        """Agent transitions to BACKTEST_COMPLETE when backtest finishes."""

    async def test_backtest_failure_sets_error_state(self, client, auth_headers):
        """Failed backtest moves agent to ERROR state."""

class TestReviewGate:
    """Tests for human review of backtest results."""

    async def test_approve_agent_with_good_metrics(self, client, auth_headers):
        """Agent with win_rate > 50% and Sharpe > 1.0 can be approved."""

    async def test_reject_agent_with_bad_metrics(self, client, auth_headers):
        """Agent with negative PnL can be rejected with reason."""

    async def test_cannot_promote_below_minimum_criteria(self, client, auth_headers):
        """API rejects promotion if metrics below threshold."""

class TestPaperTrading:
    """Tests for paper trading state."""

    async def test_approved_agent_enters_paper_trading(self, client, auth_headers):
        """Approved agent transitions to PAPER_TRADING."""

    async def test_paper_trades_not_real_money(self, client, auth_headers, broker_mock):
        """Paper trades hit paper trading endpoint, not live."""

class TestLiveTrading:
    """Tests for live trading promotion."""

    async def test_promote_to_live_requires_admin(self, client, trader_headers):
        """Non-admin cannot promote to live (403)."""

    async def test_promote_to_live_with_admin(self, client, admin_headers):
        """Admin can promote agent to LIVE_TRADING."""

class TestPauseAndRetire:
    """Tests for pausing and retiring agents."""

    async def test_pause_running_agent(self, client, auth_headers):
        """Pausing agent sends pause to Bridge and updates status."""

    async def test_retire_agent_cleanup(self, client, auth_headers):
        """Retiring agent removes workspace on instance."""
```

### 4.3 CI Integration

```yaml
# .github/workflows/ci.yml (relevant section)

regression:
  runs-on: ubuntu-latest
  needs: [test]
  services:
    postgres:
      image: timescale/timescaledb:latest-pg16
      env:
        POSTGRES_PASSWORD: test
        POSTGRES_DB: phoenix_test
      ports: ["5432:5432"]
    redis:
      image: redis:7-alpine
      ports: ["6379:6379"]
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"
    - run: pip install -e ".[dev]"
    - run: alembic upgrade head
      env:
        DATABASE_URL: postgresql+asyncpg://postgres:test@localhost:5432/phoenix_test
    - run: python -m pytest tests/regression/ -v --tb=short
      env:
        DATABASE_URL: postgresql+asyncpg://postgres:test@localhost:5432/phoenix_test
        REDIS_URL: redis://localhost:6379/0
```

### 4.4 Nightly Full Suite

```yaml
# .github/workflows/nightly.yml

name: Nightly Regression
on:
  schedule:
    - cron: "0 3 * * *"  # 3 AM UTC daily
  workflow_dispatch: {}

jobs:
  full-regression:
    # Runs unit + integration + regression + e2e + load tests
    # Uses docker-compose to spin up full stack
```

### 4.5 Regression Growth by Phase

| Phase | Regression Tests Added | Cumulative Total |
|---|---|---|
| Phase 1 (M1.1–M1.13) | ~80 | 80 |
| Phase 2 (M2.1–M2.15) | ~120 | 200 |
| Phase 3 (M3.1–M3.14) | ~100 | 300 |
| **Total** | | **~300 regression tests** |

---

## 5. Phase 1 Implementation Details (M1.1–M1.13)

### M1.1: Repository Scaffolding & CI/CD Pipeline

**Research Items:**
- Review existing Phoenix v1 `pyproject.toml` for dependency baseline
- Evaluate Turborepo vs simple Makefile for monorepo task orchestration
- Review existing CI workflow in `.github/workflows/ci.yml` for patterns to carry forward

**TDD Test List (write these first):**

| Test File | Test Functions |
|---|---|
| `tests/regression/conftest.py` | `engine`, `session`, `client`, `auth_headers` fixtures |
| `apps/api/tests/unit/test_health.py` | `test_health_endpoint_returns_200` |
| `apps/dashboard/tests/unit/app.test.tsx` | `test_app_renders_without_crash` |
| `infra/scripts/test_docker_health.sh` | Health check for Postgres, Redis, MinIO |

**Build Items (ordered):**
1. Create repository with folder structure from Section 2
2. `pyproject.toml` with project metadata, dependencies (see v1 `pyproject.toml` as baseline, upgrade to Python 3.12)
3. `apps/dashboard/package.json` with React 18, Vite 5, Tailwind, Radix UI, TanStack Query
4. `.pre-commit-config.yaml` (ruff, eslint, prettier)
5. `Makefile` with targets: `dev-install`, `lint`, `test`, `test-cov`, `infra-up`, `infra-down`, `docker-build`, `docker-up`
6. `.github/workflows/ci.yml` (lint → test → regression → build, matrix for 12 services)
7. `.github/workflows/cd.yml` (build + push to ghcr.io + Coolify webhook on tag)
8. `.github/workflows/nightly.yml` (full regression + e2e)
9. `.env.example` with all environment variables grouped by service
10. Base `conftest.py` files with shared fixtures
11. Docker Compose files (`dev`, `full`, `coolify`)
12. Initial `README.md` (overview, prerequisites, quick start)

**Patterns Used:** N/A (scaffolding milestone)

**Regression Additions:**
- `test_health.py` — API health endpoint
- `test_docker_health.sh` — infrastructure health

**Definition of Done:**
- [ ] `git clone && make dev-install` completes without errors
- [ ] `make lint` passes (ruff + eslint)
- [ ] `make test` runs and passes (initial tests)
- [ ] `make infra-up` starts Postgres, Redis, MinIO
- [ ] CI pipeline green on first push to `main`
- [ ] README covers prerequisites and quick start

---

### M1.2: Infrastructure Provisioning

**Research Items:**
- Hetzner Cloud API for automated VPS provisioning
- WireGuard configuration for hub-spoke topology
- TimescaleDB extension installation on PostgreSQL 16
- MinIO bucket creation and access policies
- Coolify installation and Docker Compose deployment

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `tests/regression/test_infra_health.py` | `test_postgres_connection`, `test_redis_connection`, `test_minio_connection` |
| `tests/regression/test_infra_health.py` | `test_timescaledb_extension_enabled` |
| `infra/scripts/test_wireguard.sh` | `test_ping_all_nodes` |

**Build Items:**
1. WireGuard config templates (`infra/wireguard/server.conf.template`, `client.conf.template`)
2. Provisioning script for Coolify server (`infra/scripts/provision-coolify.sh`)
3. Provisioning script for OpenClaw VPS (`infra/scripts/deploy-openclaw.sh`)
4. Docker Compose `infra-only` with PostgreSQL 16 + TimescaleDB, Redis 7, MinIO
5. MinIO bucket initialization script (`infra/scripts/init-minio.sh`)
6. Firewall configuration script (`infra/scripts/setup-firewall.sh`)
7. DNS configuration documentation
8. Update `.env.example` with infrastructure endpoints

**Patterns Used:** Infrastructure as Code (scripts)

**Regression Additions:**
- `test_infra_health.py` — database, cache, storage connectivity

**Definition of Done:**
- [ ] All nodes pingable via WireGuard
- [ ] PostgreSQL accepts connections with TimescaleDB enabled
- [ ] Redis responds to PING
- [ ] MinIO console accessible, all 5 buckets created
- [ ] Coolify dashboard accessible
- [ ] Infrastructure health tests pass

---

### M1.3: Auth Service Migration & API Gateway

**Research Items:**
- Review existing `services/auth-service/` for JWT implementation, MFA flow
- Review existing `services/api-gateway/` for route patterns
- Audit RBAC permission model: 5 roles × 20 permissions matrix
- Review `python-jose` JWT handling and token refresh patterns

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `apps/api/tests/unit/test_auth_middleware.py` | `test_valid_jwt_passes`, `test_expired_jwt_rejected`, `test_missing_jwt_returns_401`, `test_invalid_signature_rejected` |
| `apps/api/tests/unit/test_rbac.py` | `test_admin_has_all_permissions`, `test_viewer_has_read_only`, `test_trader_cannot_manage_users`, `test_custom_role_respects_permissions` |
| `apps/api/tests/integration/test_auth_routes.py` | `test_register_new_user`, `test_login_returns_tokens`, `test_refresh_token_flow`, `test_mfa_setup_and_verify`, `test_password_reset_flow` |
| `apps/api/tests/unit/test_rate_limit.py` | `test_rate_limit_blocks_after_threshold`, `test_rate_limit_resets_after_window` |
| `tests/regression/test_auth_regression.py` | Full auth flow regression (15 tests) |

**Build Items:**
1. Pydantic schemas: `UserCreate`, `UserLogin`, `TokenResponse`, `MFASetup`, `MFAVerify`, `PasswordReset`
2. Auth middleware (`apps/api/src/middleware/auth.py`): JWT validation, user extraction
3. RBAC middleware: permission checking decorator (`@require_permission("agents:write")`)
4. User repository (`apps/api/src/repositories/user_repo.py`)
5. Auth service (`apps/api/src/services/auth_service.py`): register, login, refresh, MFA
6. Auth routes (`apps/api/src/routes/auth.py`)
7. Rate limiting middleware (`apps/api/src/middleware/rate_limit.py`)
8. nginx configuration (`infra/nginx/nginx.conf`): `/api/` → 8011, `/auth/` → 8001, `/ws/` → 8031
9. RBAC seed data: roles and permissions in `infra/scripts/seed-db.sh`

**Patterns Used:** Middleware, Repository, Service

**Regression Additions:**
- `test_auth_regression.py` — 15 tests covering all auth flows

**Definition of Done:**
- [ ] Register, login, MFA enroll/verify all pass tests
- [ ] JWT expiry and refresh work correctly
- [ ] RBAC enforced: viewer gets 403 on admin endpoints
- [ ] Rate limiting blocks after 100 req/min on auth endpoints
- [ ] nginx routes correctly to API and Auth services
- [ ] 90%+ coverage on new auth code

---

### M1.4: Dashboard Shell & Navigation

**Research Items:**
- Review existing `services/dashboard-ui/src/` for AppShell, ThemeProvider, routing
- Evaluate React Router v6 patterns for protected routes
- Tailwind CSS v4 configuration for dark mode and custom palette
- Bottom navigation patterns for mobile (Material Design 3 specs)

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `apps/dashboard/tests/unit/components/layout/app-shell.test.tsx` | `test_renders_sidebar_on_desktop`, `test_renders_bottom_nav_on_mobile`, `test_active_tab_highlighted` |
| `apps/dashboard/tests/unit/context/auth-context.test.tsx` | `test_redirects_unauthenticated_to_login`, `test_stores_token_on_login`, `test_clears_token_on_logout` |
| `apps/dashboard/tests/unit/context/theme-context.test.tsx` | `test_dark_mode_toggle`, `test_persists_theme_to_localstorage` |
| `apps/dashboard/tests/unit/pages/login.test.tsx` | `test_login_form_submits`, `test_error_shown_on_invalid_credentials` |
| `tests/e2e/auth.spec.ts` | `test_login_flow`, `test_logout_flow`, `test_protected_route_redirect` |

**Build Items:**
1. Vite 5 + React 18 + TypeScript project initialization
2. Tailwind CSS v4 config with dark mode class strategy and Phoenix palette
3. `lib/utils.ts` — `cn()` utility (carry from v1)
4. ThemeProvider context (carry from v1, adapt to new theme)
5. AuthContext with React Query integration
6. AppShell component: sidebar (desktop) + bottom nav (mobile)
7. React Router v6 setup with all 12 routes and placeholder pages
8. Login page with form validation
9. Protected route wrapper component
10. Error boundary component for catch-all error handling

**Patterns Used:** Compound Component (AppShell), Context Provider (Auth, Theme)

**Regression Additions:**
- `auth.spec.ts` — Playwright login/logout flow

**Definition of Done:**
- [ ] Dashboard loads with login screen
- [ ] All 12 navigation items visible after login
- [ ] Dark/light toggle works and persists
- [ ] Mobile bottom nav appears below 768px
- [ ] Unauthenticated requests redirect to login
- [ ] 85%+ coverage on new frontend code

---

### M1.5: UI Component Library

**Research Items:**
- Inventory existing 19 Radix wrappers from `services/dashboard-ui/src/components/ui/`
- Evaluate TanStack Table v8 for DataTable component
- Evaluate Sonner for toast notifications
- Review `@xyflow/react` API for future Agent Network page

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `apps/dashboard/tests/unit/components/ui/*.test.tsx` | Snapshot tests for all 19 Radix wrappers (19 test files) |
| `apps/dashboard/tests/unit/components/composite/data-table.test.tsx` | `test_renders_rows`, `test_sorts_by_column`, `test_filters_rows`, `test_paginates`, `test_empty_state` |
| `apps/dashboard/tests/unit/components/composite/flex-card.test.tsx` | `test_renders_title_and_status`, `test_click_navigates` |
| `apps/dashboard/tests/unit/components/composite/metric-card.test.tsx` | `test_renders_value_and_label`, `test_sparkline_renders` |
| `apps/dashboard/tests/unit/components/composite/status-badge.test.tsx` | `test_green_for_running`, `test_red_for_error`, `test_pulse_animation` |
| `apps/dashboard/tests/unit/components/composite/side-panel.test.tsx` | `test_opens_on_trigger`, `test_closes_on_escape` |
| `apps/dashboard/tests/unit/components/composite/form-builder.test.tsx` | `test_renders_fields_from_schema`, `test_validates_required_fields` |
| `apps/dashboard/tests/unit/components/composite/confirm-dialog.test.tsx` | `test_shows_message`, `test_calls_onconfirm`, `test_calls_oncancel` |

**Build Items:**
1. Copy 19 Radix wrappers from v1 (`ui/button.tsx` through `ui/avatar.tsx`)
2. Write snapshot tests for all 19 wrappers
3. DataTable using TanStack Table v8 (sort, filter, paginate, virtual scroll)
4. FlexCard (status indicator, click handler)
5. MetricCard (value, label, trend, sparkline via Recharts)
6. StatusBadge (color mapping, pulse animation CSS)
7. SidePanel (slide-in from right, overlay on mobile)
8. FormBuilder (JSON schema → form fields with validation)
9. ConfirmDialog (destructive action confirmation)
10. Toast via Sonner library
11. EmptyState (illustration + CTA)

**Patterns Used:** Compound Component (DataTable), Strategy (FormBuilder field rendering)

**Regression Additions:**
- Snapshot tests for all components (run on every PR)

**Definition of Done:**
- [ ] All 19 Radix wrappers render correctly
- [ ] DataTable handles 1000+ rows without lag
- [ ] All composite components have passing tests
- [ ] Dark and light themes apply to every component
- [ ] All components responsive on mobile
- [ ] 85%+ coverage

---

### M1.6: Database Schema & Migrations

**Research Items:**
- Review PRD Section 16 for all 17+ entities and relationships
- Review Architecture Plan Section 4 for complete SQL schema
- SQLAlchemy 2 async patterns and best practices
- Alembic autogeneration with async engines
- TimescaleDB hypertable creation and continuous aggregates

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `shared/db/tests/test_models.py` | `test_user_model_fields`, `test_agent_model_fields`, `test_trade_intent_model_fields` (one per model) |
| `shared/db/tests/test_migrations.py` | `test_upgrade_head_succeeds`, `test_downgrade_one_succeeds`, `test_upgrade_then_downgrade_idempotent` |
| `shared/db/tests/test_relationships.py` | `test_user_has_many_agents`, `test_agent_belongs_to_instance`, `test_agent_has_many_backtests` |
| `shared/db/tests/test_hypertables.py` | `test_market_bars_is_hypertable`, `test_performance_metrics_is_hypertable`, `test_agent_heartbeats_is_hypertable` |

**Build Items:**
1. SQLAlchemy Base class and engine factory (`shared/db/engine.py`)
2. ORM models for all 17 entities (one file per model in `shared/db/models/`)
3. Join tables: `agent_skills`, `connector_agents`
4. Alembic configuration (`shared/db/migrations/alembic.ini`, `env.py`)
5. Initial migration: all application tables
6. Second migration: TimescaleDB extension + hypertables
7. Third migration: indexes on foreign keys and query columns
8. Seed script: default admin user, roles, permissions (`infra/scripts/seed-db.sh`)
9. Retention policy SQL for hypertables

**Patterns Used:** Repository (data access pattern for each table)

**Regression Additions:**
- `test_migrations.py` — upgrade and downgrade test (runs in regression suite)

**Definition of Done:**
- [ ] `alembic upgrade head` creates all tables
- [ ] `alembic downgrade -1` reverts cleanly
- [ ] All FK relationships enforced
- [ ] TimescaleDB hypertables created
- [ ] Seed script creates admin user
- [ ] 90%+ coverage on models

---

### M1.7: OpenClaw Bridge Service

**Research Items:**
- OpenClaw CLI API: how to create agents, manage workspaces, send messages
- OpenClaw `openclaw.json` multi-agent configuration format
- FastAPI streaming responses for log tailing
- Prometheus client library for custom metrics

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `openclaw/bridge/tests/unit/test_agent_manager.py` | `test_create_agent_writes_config_files`, `test_delete_agent_removes_workspace`, `test_pause_agent`, `test_resume_agent`, `test_list_agents`, `test_get_agent_detail` |
| `openclaw/bridge/tests/unit/test_heartbeat.py` | `test_collect_heartbeat_returns_all_agents`, `test_heartbeat_includes_status_and_pnl` |
| `openclaw/bridge/tests/unit/test_auth.py` | `test_valid_token_passes`, `test_invalid_token_returns_401`, `test_missing_token_returns_401` |
| `openclaw/bridge/tests/unit/test_skill_sync.py` | `test_sync_pulls_from_minio`, `test_sync_detects_changes` |
| `openclaw/bridge/tests/integration/test_bridge_api.py` | Contract tests for all 12 endpoints |

**Build Items:**
1. FastAPI app with X-Bridge-Token authentication
2. Agent manager: create/delete/pause/resume/update agent workspaces
3. AGENTS.md, TOOLS.md, SOUL.md, HEARTBEAT.md template writer
4. Heartbeat collector: gather agent statuses from OpenClaw process
5. Skill sync: pull from MinIO using boto3-compatible S3 client
6. Log streamer: tail agent session JSONL files
7. Prometheus metrics: agent count, heartbeat latency, error count
8. Dockerfile and systemd service file
9. `sync-skills.sh` cron script

**Patterns Used:** Service (agent manager), Observer (heartbeat)

**Regression Additions:**
- Bridge API contract tests added to regression suite

**Definition of Done:**
- [ ] Bridge starts and responds on WireGuard IP
- [ ] Agent CRUD works (create workspace, delete workspace)
- [ ] Heartbeat returns all agents within 1 second
- [ ] Skill sync pulls from MinIO successfully
- [ ] Invalid token returns 401
- [ ] Prometheus `/metrics` exposes correct counters

---

### M1.8: First OpenClaw Instance Setup

**Research Items:**
- OpenClaw onboarding: `openclaw onboard --skip-channel`
- OpenClaw multi-agent mode configuration
- AGENTS.md authoring best practices
- TOOLS.md: available built-in tools, custom tool registration

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `openclaw/configs/tests/test_agent_configs.py` | `test_trading_agent_config_valid`, `test_monitoring_agent_config_valid` |
| `tests/regression/test_heartbeat_regression.py` | `test_instance_heartbeat_received`, `test_agent_status_in_heartbeat` |

**Build Items:**
1. OpenClaw installation on Node 4
2. `openclaw.json` for Instance D (Live Trading) with 2 agents
3. Agent configs: `live-trader-test/AGENTS.md`, `TOOLS.md`, `SOUL.md`, `HEARTBEAT.md`
4. Agent configs: `trade-monitor-test/AGENTS.md`, `TOOLS.md`, `SOUL.md`
5. Bridge Service deployed and registered
6. End-to-end signal test: API → Bridge → Agent → Trade Intent
7. Systemd service files for auto-restart

**Patterns Used:** Template (agent configuration templates)

**Regression Additions:**
- `test_heartbeat_regression.py` — heartbeat from live instance

**Definition of Done:**
- [ ] OpenClaw running with 2 agents
- [ ] Bridge API returns agent list
- [ ] Heartbeat flows to Control Plane every 60s
- [ ] Test signal processed by agent
- [ ] Auto-restart after VPS reboot

---

### M1.9: Connector Framework Core

**Research Items:**
- Discord.py: bot setup, guild/channel message events, reconnection
- `alpaca-py` (v0.21+): REST API, WebSocket streaming, paper vs live
- Abstract Base Class patterns for plugin architectures
- Message normalization: common schema across Discord, Reddit, webhooks

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `services/connector-manager/tests/unit/test_base_connector.py` | `test_base_connector_interface`, `test_mock_connector_lifecycle` |
| `services/connector-manager/tests/unit/test_factory.py` | `test_create_discord_connector`, `test_create_alpaca_broker`, `test_unknown_type_raises` |
| `services/connector-manager/tests/unit/test_discord_connector.py` | `test_normalizes_discord_message`, `test_handles_reconnection` |
| `services/connector-manager/tests/unit/test_alpaca_broker.py` | `test_place_order`, `test_get_positions`, `test_get_account_balance` |
| `services/connector-manager/tests/unit/test_router.py` | `test_routes_message_to_assigned_agent`, `test_ignores_unassigned_channels` |
| `apps/api/tests/integration/test_connector_routes.py` | `test_create_connector`, `test_list_connectors`, `test_test_connection`, `test_delete_connector` |
| `tests/regression/test_connector_regression.py` | Full connector flow (10 tests) |

**Build Items:**
1. `BaseConnector` ABC in `services/connector-manager/src/base.py`
2. `ConnectorFactory` in `services/connector-manager/src/factory.py`
3. `ConnectorMessage` schema (normalized message format)
4. Discord connector implementation
5. Alpaca broker connector implementation
6. Message router: normalize + publish to `stream:connector-events`
7. Connector CRUD API routes
8. Credential encryption integration (Fernet)

**Patterns Used:** Factory, Strategy, Observer (message routing)

**Regression Additions:**
- `test_connector_regression.py` — connect, normalize, route, disconnect

**Definition of Done:**
- [ ] Discord connector receives messages from test server
- [ ] Alpaca connector places paper trade
- [ ] Messages normalized and published to event bus
- [ ] Credentials encrypted in database
- [ ] Test connection endpoint returns success/failure
- [ ] 90%+ coverage

---

### M1.10: Trades Tab & Positions Tab

**Research Items:**
- WebSocket implementation in React (native or via library)
- TanStack Table virtual scrolling for 10K+ rows
- Recharts sparkline component for position cards
- CSV export library (papaparse or native)

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `apps/api/tests/integration/test_trade_routes.py` | `test_list_trades_paginated`, `test_filter_trades_by_agent`, `test_filter_trades_by_status`, `test_get_trade_detail` |
| `apps/api/tests/integration/test_position_routes.py` | `test_list_open_positions`, `test_list_closed_positions`, `test_portfolio_summary` |
| `apps/dashboard/tests/unit/pages/trades.test.tsx` | `test_renders_trade_table`, `test_filters_applied`, `test_click_opens_side_panel` |
| `apps/dashboard/tests/unit/pages/positions.test.tsx` | `test_renders_position_cards`, `test_shows_realtime_pnl` |
| `apps/dashboard/tests/unit/hooks/use-websocket.test.ts` | `test_connects_and_receives_messages`, `test_reconnects_on_drop` |
| `tests/e2e/trades-tab.spec.ts` | Full tab interaction flow |
| `tests/e2e/positions-tab.spec.ts` | Full tab interaction flow |

**Build Items:**
1. Trade repository and service
2. Position repository and service
3. Trade routes (`/api/v2/trades`, `/api/v2/trades/:id`)
4. Position routes (`/api/v2/positions`, `/api/v2/positions/closed`, `/api/v2/positions/summary`)
5. WebSocket Gateway channels: `trades`, `positions`
6. `useWebSocket` hook with reconnection
7. Trades page: DataTable + filters + SidePanel
8. Positions page: FlexCards + DataTable + portfolio summary

**Patterns Used:** Repository, Service, Observer (WebSocket)

**Regression Additions:**
- `test_trade_execution_regression.py` — first trade flow tests added
- Playwright specs for both tabs

**Definition of Done:**
- [ ] Trades table loads with pagination
- [ ] New trades appear via WebSocket within 2 seconds
- [ ] Positions show real-time PnL
- [ ] Filters work on all columns
- [ ] Mobile layout scrolls correctly
- [ ] CSV export works

---

### M1.11: Basic Agent CRUD

**Research Items:**
- Multi-step form wizard patterns in React (controlled stepper)
- OpenClaw agent workspace structure requirements
- Bridge Service API contract for agent CRUD

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `apps/api/tests/integration/test_agent_routes.py` | `test_create_agent`, `test_list_agents`, `test_get_agent_detail`, `test_update_agent`, `test_delete_agent`, `test_pause_agent`, `test_resume_agent` |
| `apps/api/tests/unit/test_agent_service.py` | `test_create_calls_bridge`, `test_delete_calls_bridge`, `test_validates_instance_capacity` |
| `apps/dashboard/tests/unit/pages/agents.test.tsx` | `test_renders_agent_cards`, `test_new_agent_wizard_steps`, `test_wizard_validation` |
| `tests/e2e/agents-tab.spec.ts` | Create agent wizard flow |

**Build Items:**
1. Agent Pydantic schemas (Create, Update, Response, Detail)
2. Agent repository
3. Agent service (with Bridge Service HTTP calls)
4. Agent routes
5. Agents page: FlexCard list + "New Agent" button
6. Agent creation wizard (5 steps: Basic → Instance → Data → Skills → Risk → Review)
7. Agent detail page (status, config, recent activity)

**Patterns Used:** Service, Repository, State Machine (initial states)

**Regression Additions:**
- Agent CRUD tests added to `test_agent_lifecycle_regression.py`

**Definition of Done:**
- [ ] Create agent → appears on instance
- [ ] Agent list shows real-time status
- [ ] Pause/resume works
- [ ] Delete cleans up workspace
- [ ] Wizard validates all steps
- [ ] 90%+ coverage

---

### M1.12: Execution Service & Risk Checks

**Research Items:**
- Redis Streams consumer group API for reliable message processing
- Chain of Responsibility pattern for composable risk checks
- Idempotency patterns for financial transactions
- Circuit breaker state machine (CLOSED → HALF_OPEN → OPEN)

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `services/execution/tests/unit/test_agent_risk.py` | `test_allows_within_limit`, `test_rejects_oversized_position`, `test_rejects_unapproved_instrument`, `test_rejects_exceeds_daily_limit` |
| `services/execution/tests/unit/test_execution_risk.py` | `test_validates_order_quantity`, `test_validates_market_hours`, `test_dedup_rejects_duplicate` |
| `services/execution/tests/unit/test_global_risk.py` | `test_allows_under_daily_loss`, `test_rejects_over_daily_loss`, `test_circuit_breaker_states` |
| `services/execution/tests/unit/test_chain.py` | `test_all_pass_executes`, `test_first_fail_stops_chain`, `test_returns_rejection_reason` |
| `services/execution/tests/unit/test_executor.py` | `test_places_alpaca_order`, `test_tracks_order_status` |
| `services/global-monitor/tests/unit/test_circuit_breaker.py` | `test_closed_to_half_open`, `test_half_open_to_open`, `test_auto_reset_at_midnight`, `test_manual_reset` |
| `services/global-monitor/tests/unit/test_kill_switch.py` | `test_closes_all_positions`, `test_pauses_all_agents` |
| `tests/regression/test_trade_execution_regression.py` | Full pipeline (15 tests) |

**Build Items:**
1. Redis Streams consumer for `stream:trade-intents`
2. Agent-level risk check class
3. Execution-level risk check class
4. Global-level risk check class
5. Chain of Responsibility orchestrator
6. Idempotency check (trade intent ID dedup in Redis)
7. Broker executor (Alpaca order placement)
8. Global Position Monitor service
9. Circuit breaker state machine
10. Kill switch implementation
11. API endpoints: `/api/v2/trade-intents`, `/api/v2/execution/status`, `/api/v2/execution/kill-switch`

**Patterns Used:** Chain of Responsibility, State Machine (circuit breaker), Strategy (broker selection)

**Regression Additions:**
- `test_trade_execution_regression.py` — full pipeline regression

**Definition of Done:**
- [ ] Trade intent processed within 500ms
- [ ] Oversized orders rejected with reason
- [ ] Duplicate intents not executed twice
- [ ] Alpaca paper trade placed and confirmed
- [ ] Circuit breaker opens at 3% daily loss
- [ ] Kill switch closes all positions within 30s
- [ ] 90%+ coverage

---

### M1.13: Mobile Responsive Foundation

**Research Items:**
- Tailwind responsive utilities and breakpoint system
- Bottom navigation UX patterns (Material Design 3)
- CSS `position: sticky` for table columns
- Touch gesture libraries for React (swipe)

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `apps/dashboard/tests/unit/components/layout/bottom-nav.test.tsx` | `test_renders_5_primary_tabs`, `test_more_button_shows_remaining`, `test_active_indicator` |
| `tests/e2e/mobile.spec.ts` | `test_bottom_nav_on_mobile_viewport`, `test_sidebar_on_desktop`, `test_table_horizontal_scroll`, `test_wizard_fullscreen_on_mobile` |

**Build Items:**
1. Tailwind responsive audit of all existing components
2. Bottom navigation component (5 primary + "More")
3. Responsive DataTable (sticky first column, horizontal scroll)
4. Responsive FlexCards (1-col mobile, 2-col tablet, 3+ desktop)
5. Responsive SidePanel (full-screen overlay on mobile)
6. Responsive wizard (full-screen steps on mobile)
7. Touch-friendly targets (minimum 44px)

**Patterns Used:** Responsive Design, Compound Component

**Regression Additions:**
- `mobile.spec.ts` — Playwright mobile viewport tests

**Definition of Done:**
- [ ] Usable on iPhone SE (375px)
- [ ] Bottom nav on mobile, sidebar on desktop
- [ ] Tables scroll horizontally without page overflow
- [ ] Agent wizard works on mobile
- [ ] No horizontal page overflow on any screen

---

## 6. Phase 2 Implementation Details (M2.1–M2.15)

### M2.1: Core Skill Catalog (30 Skills)

**Research Items:**
- OpenClaw SKILL.md specification and parsing behavior
- Market data APIs: Alpaca Data API, Yahoo Finance (`yfinance`), Polygon.io
- Technical indicators: `ta-lib` or `pandas-ta` for formula reference
- Options chain data: Unusual Whales API, Alpaca options data

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `openclaw/skills/tests/test_skill_validation.py` | `test_all_skills_have_valid_frontmatter` (parametrized across 30 skills), `test_all_skills_have_required_sections` |
| `openclaw/skills/tests/test_skill_categories.py` | `test_data_skills_count_is_8`, `test_analysis_skills_count_is_8`, `test_execution_skills_count_is_7`, `test_risk_skills_count_is_7` |

**Build Items:**
1. SKILL.md template in `docs/skill-development-guide.md`
2. 8 Data skills: `market-data-fetch`, `news-aggregator`, `options-chain-lookup`, `social-sentiment-reader`, `economic-calendar-check`, `sector-heatmap`, `unusual-options-flow`, `insider-transaction-scan`
3. 8 Analysis skills: `technical-indicator-suite`, `support-resistance-finder`, `pattern-recognition`, `volume-profile-analysis`, `correlation-analysis`, `sentiment-scoring`, `implied-volatility-calc`, `earnings-impact-predictor`
4. 7 Execution skills: `order-builder-stock`, `order-builder-option`, `position-sizer`, `entry-timing-optimizer`, `slippage-estimator`, `multi-leg-option-builder`, `order-type-selector`
5. 7 Risk skills: `stop-loss-calculator`, `portfolio-exposure-check`, `correlation-risk-checker`, `max-drawdown-estimator`, `daily-loss-tracker`, `position-limit-enforcer`, `sector-concentration-check`
6. Upload all to MinIO `phoenix-skills` bucket

**Patterns Used:** Template (SKILL.md format)

**Regression Additions:**
- Skill validation tests run in regression suite

**Definition of Done:**
- [ ] 30 skills authored and validated
- [ ] All synced to OpenClaw instances
- [ ] Agent can invoke `market-data-fetch` successfully
- [ ] Agent can chain analysis → execution skills

---

### M2.2: Skill Sync Service

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `services/skill-sync/tests/unit/test_versioning.py` | `test_version_increment`, `test_rollback_to_previous`, `test_conflict_detection` |
| `services/skill-sync/tests/unit/test_distributor.py` | `test_push_to_all_instances`, `test_partial_failure_retries`, `test_sync_status_tracking` |
| `apps/api/tests/integration/test_skill_routes.py` | `test_list_skills`, `test_create_skill`, `test_update_skill`, `test_force_sync` |
| `tests/regression/test_skill_sync_regression.py` | End-to-end sync flow |

**Build Items:**
1. MinIO watcher (S3 event notifications or polling)
2. Skill version tracking in PostgreSQL
3. Distributor: push skills to all Bridge Services via `POST /skills/sync`
4. Rollback: restore previous version from MinIO versioning
5. API routes: skill CRUD + sync status + force sync
6. Dashboard skill management (Monaco editor, sync indicators)

**Patterns Used:** Observer (MinIO watcher), Service

**Definition of Done:**
- [ ] New skill appears on all instances within 5 minutes
- [ ] Version tracked and incremented
- [ ] Rollback restores previous content
- [ ] Dashboard shows sync status per instance

---

### M2.3: Backtesting Engine

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `services/backtest-runner/tests/unit/test_metrics.py` | One test per metric (15 tests): `test_sharpe_ratio_calculation`, `test_max_drawdown_calculation`, `test_win_rate_calculation`, etc. Each with a known dataset and expected output. |
| `services/backtest-runner/tests/unit/test_simulation.py` | `test_signal_driven_replay`, `test_heartbeat_driven_replay`, `test_slippage_applied` |
| `services/backtest-runner/tests/unit/test_data_loader.py` | `test_load_ohlcv_from_timescaledb`, `test_load_messages_from_connector` |
| `services/backtest-runner/tests/integration/test_backtest_pipeline.py` | `test_full_signal_driven_backtest`, `test_results_stored_in_minio` |
| `tests/regression/test_backtest_regression.py` | Full backtest flow (10 tests) |

**Build Items:**
1. Data loader: fetch OHLCV from TimescaleDB, messages from connector history
2. Signal-driven simulation engine
3. Heartbeat-driven simulation engine
4. Metric calculator (15 metrics from PRD Section 14.3)
5. Report generator (JSON summary, equity curve, trade log)
6. Artifact storage to MinIO
7. Docker-in-Docker sandbox execution
8. Progress streaming to WebSocket
9. API routes: start backtest, get status, get results

**Patterns Used:** Strategy (simulation type), Factory (engine creation)

**Definition of Done:**
- [ ] Signal-driven backtest replays 2 years of data
- [ ] All 15 metrics calculated correctly
- [ ] Results stored in MinIO
- [ ] Progress streams to dashboard

---

### M2.4: Agent Lifecycle State Machine

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `services/orchestrator/tests/unit/test_state_machine.py` | `test_created_to_backtesting`, `test_backtesting_to_complete`, `test_complete_to_review`, `test_review_to_paper`, `test_paper_to_live`, `test_any_to_paused`, `test_any_to_error`, `test_invalid_transition_raises`, `test_cannot_skip_states` |

**Build Items:**
1. `AgentStateMachine` class with all valid transitions
2. Orchestrator workers for each transition
3. Review gate with configurable promotion criteria
4. Audit logging for every state transition
5. Dashboard status indicators and transition buttons

**Patterns Used:** State Machine, Observer (audit events)

---

### M2.5: Trading Agent Architecture

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `openclaw/configs/tests/test_trading_agent.py` | `test_signal_evaluation_produces_trade_intent`, `test_no_trade_on_weak_signal`, `test_monitoring_agent_receives_positions` |
| `tests/regression/test_agent_lifecycle_regression.py` | `test_trading_agent_full_cycle` (signal → evaluation → trade → monitor → close) |

**Build Items:**
1. Trading agent AGENTS.md template with signal evaluation instructions
2. Monitoring agent AGENTS.md template with position tracking instructions
3. Auto-pairing logic: create monitor alongside trader
4. Signal evaluation flow integration with skills
5. Trade intent formatting via `order-builder-stock` skill

**Patterns Used:** Template, Observer (monitoring)

---

### M2.6: Strategy Agent Architecture

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `openclaw/configs/tests/test_strategy_agent.py` | `test_heartbeat_triggers_analysis`, `test_strategy_generates_signal` |
| `openclaw/configs/tests/test_strategy_templates.py` | `test_all_15_templates_valid_config` |

**Build Items:**
1. Strategy agent AGENTS.md + HEARTBEAT.md templates
2. 15 strategy templates (Moving Average Crossover through Gap Fill)
3. Strategies Tab: template library, creation wizard
4. Heartbeat configuration UI

---

### M2.7: Performance Tab

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `apps/api/tests/integration/test_performance_routes.py` | `test_portfolio_overview`, `test_account_performance`, `test_agent_rankings`, `test_source_analysis`, `test_instrument_analytics`, `test_risk_metrics` |
| `apps/api/tests/unit/test_performance_service.py` | `test_calculate_sharpe`, `test_calculate_drawdown_timeline`, `test_correlation_matrix` |
| `apps/dashboard/tests/unit/pages/performance.test.tsx` | `test_renders_6_sections`, `test_time_range_filter`, `test_csv_export` |
| `tests/e2e/performance-tab.spec.ts` | Full tab interaction |

**Build Items:**
1. Performance service with TimescaleDB continuous aggregates
2. 6 API endpoints (one per section)
3. Performance page with 6 sections, Recharts charts, time range filter
4. CSV/PDF export

---

### M2.8: Remaining Connectors

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `services/connector-manager/tests/unit/test_reddit_connector.py` | `test_connects_to_subreddit`, `test_normalizes_post` |
| `services/connector-manager/tests/unit/test_twitter_connector.py` | `test_filtered_stream`, `test_normalizes_tweet` |
| `services/connector-manager/tests/unit/test_unusual_whales.py` | `test_websocket_connection`, `test_normalizes_flow_data` |
| `services/connector-manager/tests/unit/test_news_api.py` | `test_polls_headlines`, `test_normalizes_article` |
| `services/connector-manager/tests/unit/test_webhook.py` | `test_accepts_post_with_valid_key`, `test_rejects_invalid_key` |

**Build Items:**
1. Reddit connector (PRAW)
2. Twitter/X connector (filtered stream API v2)
3. Unusual Whales connector (WebSocket + REST)
4. News API connectors (Finnhub, NewsAPI)
5. Custom Webhook connector (HTTP endpoint)
6. Connectors Tab UI with type-specific config forms

---

### M2.9: Skills & Agent Config Tab

**Build Items:**
1. Skill catalog view (search, category filter)
2. Monaco editor integration for SKILL.md editing
3. Skill builder wizard
4. Agent configuration editor (edit config files on instance)
5. Bulk operations UI

---

### M2.10: Agent-to-Agent Communication

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `services/agent-comm/tests/unit/test_router.py` | `test_route_same_instance`, `test_route_cross_instance` |
| `services/agent-comm/tests/unit/test_consensus.py` | `test_quorum_met_executes`, `test_quorum_not_met_rejects`, `test_timeout_handling`, `test_tie_breaking` |
| `services/agent-comm/tests/unit/test_protocol.py` | `test_valid_message_schema`, `test_invalid_message_rejected` |

**Build Items:**
1. Agent Communication Router service
2. 5 communication patterns (request-response, broadcast, pub-sub, chain, consensus)
3. Message protocol and validation
4. Cross-instance routing via Bridge API

---

### M2.11–M2.15: Additional Brokers, Market Center, Monitoring, Skills

Each follows the same TDD pattern:
- Research the specific API/library
- Write contract/unit tests first
- Implement to make tests pass
- Add to regression suite
- Update README with new capabilities

---

## 7. Phase 3 Implementation Details (M3.1–M3.14)

### M3.1: Dev Agent

**Research Items:**
- OpenClaw agent monitoring capabilities and tool access
- Error detection patterns in distributed systems
- Auto-remediation strategies (restart, config revert, skill disable)

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `openclaw/configs/tests/test_dev_agent.py` | `test_detects_agent_crash`, `test_detects_connector_failure`, `test_detects_performance_degradation` |
| `apps/api/tests/integration/test_dev_routes.py` | `test_list_incidents`, `test_get_incident_detail`, `test_manual_diagnose` |
| `apps/api/tests/unit/test_dev_incident_service.py` | `test_classify_incident_type`, `test_determine_severity` |

**Build Items:**
1. Dev Agent AGENTS.md and HEARTBEAT.md (60-second monitoring cycle)
2. Issue detection: error rate monitoring, heartbeat gaps, performance checks
3. Issue classification: 6 types (CONNECTION_ERROR through RESOURCE_EXHAUSTION)
4. Auto-repair actions: restart, reconnect, revert config, disable skill, escalate
5. DevIncident repository and service
6. Dev API routes

---

### M3.2: Reinforcement Learning Loop

**Research Items:**
- Q-learning implementation for discrete state-action spaces
- PPO (Proximal Policy Optimization) for future upgrade
- Reward shaping for system administration tasks
- Model persistence (pickle for Q-table, PyTorch for PPO)

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `services/orchestrator/tests/unit/test_rl_agent.py` | `test_q_table_update`, `test_action_selection_epsilon_greedy`, `test_reward_calculation_positive`, `test_reward_calculation_negative`, `test_model_save_and_load` |

**Build Items:**
1. State representation encoder
2. Action space definition (7 actions)
3. Reward function (per outcome type)
4. Q-learning table with epsilon-greedy exploration
5. Episode runner: incident → action → outcome → reward → update
6. Model persistence to MinIO
7. Daily retraining job

---

### M3.3: Dev Dashboard

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `apps/dashboard/tests/unit/pages/dev-dashboard.test.tsx` | `test_renders_incident_feed`, `test_renders_rl_metrics`, `test_admin_only_access` |
| `tests/e2e/dev-dashboard.spec.ts` | `test_non_admin_cannot_access`, `test_incident_detail_view` |

**Build Items:**
1. Incident feed component (real-time via WebSocket)
2. RL metrics panel (reward trend, action distribution, success rate charts)
3. Agent health grid
4. Code changes log with diff display
5. Admin-only route guard

---

### M3.4: Task Board & Agent Roles

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `apps/api/tests/integration/test_task_routes.py` | `test_create_task`, `test_update_task_status`, `test_list_tasks_by_column`, `test_assign_task_to_agent` |
| `apps/dashboard/tests/unit/pages/task-board.test.tsx` | `test_renders_kanban_columns`, `test_drag_and_drop_moves_card`, `test_create_task_form` |
| `tests/e2e/task-board.spec.ts` | Full kanban interaction |

**Build Items:**
1. Task repository, service, routes
2. 8 agent role templates (Day Trader through Report Generator)
3. Task Board page with `@dnd-kit` kanban
4. Task creation form
5. Agent-created tasks API endpoint

---

### M3.5: Automations

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `services/automation/tests/unit/test_scheduler.py` | `test_parse_cron_expression`, `test_next_run_calculation`, `test_trigger_at_scheduled_time` |
| `services/automation/tests/unit/test_nl_parser.py` | `test_morning_at_8am`, `test_every_friday_before_close`, `test_every_hour_market_hours` |

**Build Items:**
1. Cron expression parser and scheduler
2. NL-to-cron conversion (LLM-based)
3. 6 pre-built automation templates
4. Delivery channel integration
5. Automations panel UI

---

### M3.6: Bidirectional Communication Channels

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `services/connector-manager/tests/unit/test_telegram_bot.py` | `test_status_command`, `test_portfolio_command`, `test_inline_keyboard` |
| `services/connector-manager/tests/unit/test_message_router.py` | `test_formats_for_telegram`, `test_formats_for_discord`, `test_rate_limiting` |

**Build Items:**
1. Telegram bot (python-telegram-bot library)
2. Discord slash commands enhancement
3. WhatsApp bidirectional messaging
4. Unified message router with per-channel formatting

---

### M3.7: Admin & User Management Tab

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `apps/api/tests/integration/test_admin_routes.py` | `test_create_user`, `test_assign_role`, `test_create_custom_role`, `test_api_key_vault_crud`, `test_audit_log_query` |
| `apps/api/tests/unit/test_api_key_vault.py` | `test_encrypt_key`, `test_decrypt_key`, `test_masked_display`, `test_key_test_endpoint` |
| `tests/regression/test_admin_regression.py` | Full admin flow (10 tests) |

**Build Items:**
1. User management CRUD
2. Custom role builder (permission matrix)
3. API Key Vault with Fernet encryption
4. Audit log with search and export
5. Admin Tab UI

---

### M3.8: Agent Network Visualization

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `apps/api/tests/integration/test_network_routes.py` | `test_get_graph_data`, `test_get_recent_messages` |
| `apps/dashboard/tests/unit/pages/agent-network.test.tsx` | `test_renders_graph_nodes`, `test_click_node_shows_detail`, `test_status_colors` |

**Build Items:**
1. Graph data API (nodes + edges from instances, agents, messages)
2. `@xyflow/react` graph component
3. Node coloring by status
4. Edge animation for communication
5. Detail panel on node click

---

### M3.9: Agent Code Generation & Predictive Models

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `services/backtest-runner/tests/unit/test_sandbox.py` | `test_python_execution_in_container`, `test_timeout_enforcement`, `test_memory_limit`, `test_no_network_access` |
| `services/backtest-runner/tests/unit/test_model_storage.py` | `test_save_model_to_minio`, `test_load_model_from_minio` |

**Build Items:**
1. Docker sandbox for Python code execution
2. Agent code generation skill integration
3. Model training pipeline (data → train → serialize → store)
4. Model inference endpoint
5. Model registry UI

---

### M3.10: PWA

**Build Items:**
1. `manifest.json` with app metadata and icons
2. Service Worker with cache-first for static, network-first for API
3. Push notification setup (Web Push API)
4. Offline indicator and cached data display
5. Install prompt handling

---

### M3.11: Walk-Forward Backtesting & Strategy Optimizer

**TDD Test List:**

| Test File | Test Functions |
|---|---|
| `services/backtest-runner/tests/unit/test_walk_forward.py` | `test_rolling_window_split`, `test_in_sample_out_sample_separate`, `test_overfitting_detection` |
| `services/backtest-runner/tests/unit/test_optimizer.py` | `test_grid_search`, `test_bayesian_optimization_converges` |

**Build Items:**
1. Walk-forward engine (rolling train/test windows)
2. Grid search optimizer
3. Bayesian optimizer (Optuna integration)
4. Overfitting detection (in-sample vs out-of-sample comparison)
5. Dashboard optimization UI

---

### M3.12: Observability Stack

**Build Items:**
1. Prometheus scrape configs for all services
2. Node Exporter, PostgreSQL Exporter, Redis Exporter
3. 7 Grafana dashboards (JSON provisioning)
4. Loki + Promtail log collection
5. 8 alerting rules with Discord/email routing

---

### M3.13: Load Testing, Security Hardening & Documentation

**Build Items:**
1. Locust load test: 50 agents, 100 WebSocket connections
2. Dependency vulnerability scan (Snyk)
3. SQL injection and XSS testing
4. RBAC audit (every endpoint verified)
5. All documentation: User Guide, API Reference, Operations Guide, Skill Development Guide, ADRs

---

### M3.14: Production Deployment & Go-Live

**Build Items:**
1. Execute pre-go-live checklist (from Milestones M3.14)
2. Data migration from v1 (if applicable)
3. DNS cutover
4. First agent deployment (paper trading)
5. 24-hour monitoring period

---

## 8. Configuration Guide

### 8.1 Environment Variables

All environment variables are defined in `.env.example` and grouped by service:

```env
# ===========================================================================
# DATABASE
# ===========================================================================
DATABASE_URL=postgresql+asyncpg://phoenix:your_password@localhost:5432/phoenix_v2
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10

# ===========================================================================
# REDIS
# ===========================================================================
REDIS_URL=redis://localhost:6379/0
REDIS_PASSWORD=

# ===========================================================================
# EVENT BUS
# ===========================================================================
EVENT_BUS_TYPE=redis_streams
# Alternative: NATS
# NATS_URL=nats://localhost:4222

# ===========================================================================
# JWT AUTHENTICATION
# ===========================================================================
JWT_SECRET=your-secret-key-min-32-chars
JWT_ALGORITHM=HS256
JWT_ACCESS_EXPIRY_MINUTES=60
JWT_REFRESH_EXPIRY_DAYS=7

# ===========================================================================
# CREDENTIAL ENCRYPTION
# ===========================================================================
CREDENTIAL_ENCRYPTION_KEY=your-fernet-key-base64

# ===========================================================================
# OPENCLAW INSTANCES
# ===========================================================================
OC_INSTANCES='[
  {"id":"oc-strategy-lab","host":"10.0.1.10","port":18800,"token":"bridge-secret-a"},
  {"id":"oc-data-research","host":"10.0.1.11","port":18800,"token":"bridge-secret-b"},
  {"id":"oc-promotion-risk","host":"10.0.1.12","port":18800,"token":"bridge-secret-c"},
  {"id":"oc-live-trading","host":"10.0.1.12","port":18801,"token":"bridge-secret-d"}
]'

# ===========================================================================
# BROKER - ALPACA
# ===========================================================================
ALPACA_API_KEY=your-api-key
ALPACA_API_SECRET=your-api-secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
# For live: https://api.alpaca.markets

# ===========================================================================
# BROKER - INTERACTIVE BROKERS
# ===========================================================================
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1

# ===========================================================================
# BROKER - TRADIER
# ===========================================================================
TRADIER_ACCESS_TOKEN=your-access-token
TRADIER_BASE_URL=https://sandbox.tradier.com

# ===========================================================================
# LLM PROVIDERS
# ===========================================================================
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-api-key
OPENAI_API_KEY=your-api-key
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL_FAST=claude-3-5-haiku-20241022
LLM_MODEL_SMART=claude-sonnet-4-20250514

# ===========================================================================
# CONNECTORS - DISCORD
# ===========================================================================
DISCORD_BOT_TOKEN=your-bot-token

# ===========================================================================
# CONNECTORS - REDDIT
# ===========================================================================
REDDIT_CLIENT_ID=your-client-id
REDDIT_CLIENT_SECRET=your-client-secret
REDDIT_USER_AGENT=phoenix-v2:1.0

# ===========================================================================
# CONNECTORS - TWITTER/X
# ===========================================================================
TWITTER_BEARER_TOKEN=your-bearer-token

# ===========================================================================
# CONNECTORS - UNUSUAL WHALES
# ===========================================================================
UW_API_KEY=your-api-key

# ===========================================================================
# CONNECTORS - NEWS
# ===========================================================================
FINNHUB_API_KEY=your-api-key
NEWSAPI_KEY=your-api-key

# ===========================================================================
# CONNECTORS - TELEGRAM
# ===========================================================================
TELEGRAM_BOT_TOKEN=your-bot-token

# ===========================================================================
# CONNECTORS - WHATSAPP
# ===========================================================================
WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id
WHATSAPP_ACCESS_TOKEN=your-access-token

# ===========================================================================
# ARTIFACT STORE (MinIO)
# ===========================================================================
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_USE_SSL=false

# ===========================================================================
# OBSERVABILITY
# ===========================================================================
PROMETHEUS_ENABLED=true
LOG_LEVEL=INFO
LOG_FORMAT=json

# ===========================================================================
# SKILL REPOSITORY
# ===========================================================================
SKILL_REPO_BUCKET=phoenix-skills
SKILL_SYNC_INTERVAL_SECONDS=300

# ===========================================================================
# BACKTEST
# ===========================================================================
BACKTEST_MAX_CONCURRENT=3
BACKTEST_TIMEOUT_SECONDS=3600
BACKTEST_MEMORY_LIMIT_MB=2048

# ===========================================================================
# RISK MANAGEMENT
# ===========================================================================
DEFAULT_STOP_LOSS_PCT=20
DEFAULT_TAKE_PROFIT_PCT=30
DAILY_LOSS_LIMIT_PCT=3
EMERGENCY_LOSS_LIMIT_PCT=10
CIRCUIT_BREAKER_RESET_HOUR=0  # Midnight Eastern

# ===========================================================================
# DASHBOARD
# ===========================================================================
VITE_API_BASE_URL=http://localhost:8011
VITE_WS_URL=ws://localhost:8031
VITE_APP_TITLE=Phoenix Trading
```

### 8.2 Docker Compose (Development)

```yaml
# infra/docker/docker-compose.dev.yml
services:
  postgres:
    image: timescale/timescaledb:latest-pg16
    ports: ["5432:5432"]
    environment:
      POSTGRES_USER: phoenix
      POSTGRES_PASSWORD: phoenix_dev
      POSTGRES_DB: phoenix_v2
    volumes:
      - pg-data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    command: redis-server --requirepass ""

  minio:
    image: minio/minio
    ports: ["9000:9000", "9001:9001"]
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    command: server /data --console-address ":9001"
    volumes:
      - minio-data:/data

volumes:
  pg-data:
  minio-data:
```

### 8.3 WireGuard VPN Setup

**On Coolify Server (Node 1):**

```bash
# 1. Install WireGuard
apt install wireguard

# 2. Generate keys
wg genkey | tee /etc/wireguard/private.key | wg pubkey > /etc/wireguard/public.key

# 3. Create config from template
cp infra/wireguard/server.conf.template /etc/wireguard/wg0.conf
# Edit: set PrivateKey, add Peer entries for each OpenClaw node

# 4. Enable and start
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0
```

**On OpenClaw VPS (Nodes 2-4):**

```bash
# 1. Install WireGuard
apt install wireguard

# 2. Generate keys
wg genkey | tee /etc/wireguard/private.key | wg pubkey > /etc/wireguard/public.key

# 3. Create config from template
cp infra/wireguard/client.conf.template /etc/wireguard/wg0.conf
# Edit: set PrivateKey, set server Endpoint and PublicKey

# 4. Enable and start
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0

# 5. Verify connectivity
ping 10.0.1.1  # Should reach Coolify server
```

### 8.4 OpenClaw Instance Setup

```bash
# On each OpenClaw VPS:

# 1. Install Node.js 20+ and OpenClaw
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
npm install -g @openclaw/cli

# 2. Initialize OpenClaw
openclaw onboard --skip-channel

# 3. Deploy Bridge Service
cd /opt/phoenix/bridge
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit: set BRIDGE_TOKEN, MINIO_ENDPOINT, MINIO_ACCESS_KEY, etc.

# 5. Set up systemd services
cp systemd/openclaw.service /etc/systemd/system/
cp systemd/bridge.service /etc/systemd/system/
systemctl enable openclaw bridge
systemctl start openclaw bridge

# 6. Set up skill sync cron
echo "*/5 * * * * /opt/phoenix/scripts/sync-skills.sh" | crontab -
```

### 8.5 Coolify Deployment

1. Access Coolify dashboard at `https://your-coolify-server:8000`
2. Create a new project "Phoenix v2"
3. Add a Docker Compose resource using `infra/docker/docker-compose.coolify.yml`
4. Configure environment variables via Coolify UI (paste from `.env.example`)
5. Set up custom domain: `phoenix.yourdomain.com`
6. Enable HTTPS (Let's Encrypt auto-provisioned by Coolify)
7. Deploy

---

## 9. Project README Specification

### 9.1 README Template

The `README.md` file grows with each milestone. Initial template:

```markdown
# Phoenix v2 — Autonomous Multi-Agent Trading Platform

> A dashboard-driven platform for managing AI trading agents across distributed
> OpenClaw instances. Agents are backtested, reviewed, and promoted through a
> lifecycle before trading live capital.

## Architecture

[Control Plane] Dashboard + API + DB + Redis + Event Bus
        ↕
[Execution Plane] OpenClaw Instance A, B, C, D (via WireGuard VPN)
        ↕
[Shared Services] MinIO, TimescaleDB, Execution Service, Observability

## Quick Start

### Prerequisites
- Docker + Docker Compose
- Python 3.12+
- Node.js 20+
- Make

### Development Setup
\```bash
git clone https://github.com/your-org/phoenix-v2.git
cd phoenix-v2
make dev-install    # Install Python + Node dependencies
make env-file       # Copy .env.example to .env
make infra-up       # Start Postgres, Redis, MinIO
make db-init        # Run migrations + seed data
make dev            # Start API + Dashboard in dev mode
\```

### Running Tests
\```bash
make test           # Unit tests
make test-cov       # Unit tests with coverage
make test-regression # Regression suite
make test-e2e       # Playwright browser tests
make test-all       # Everything
\```

## Configuration

See [Configuration Guide](docs/configuration-guide.md) for all environment
variables, Docker Compose setup, WireGuard VPN, and OpenClaw instance
configuration.

## API Reference

API documentation auto-generated at `http://localhost:8011/docs` (Swagger UI)
and `http://localhost:8011/redoc` (ReDoc).

## Documentation

- [User Guide](docs/user-guide.md)
- [Operations Guide](docs/operations-guide.md)
- [Skill Development Guide](docs/skill-development-guide.md)
- [Architecture Decision Records](docs/adrs/)

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite 5, Tailwind CSS, Radix UI |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Uvicorn |
| Database | PostgreSQL 16 + TimescaleDB |
| Cache/Queue | Redis 7 (BullMQ, Streams) |
| AI Runtime | OpenClaw (Node.js) |
| Storage | MinIO (S3-compatible) |
| Observability | Prometheus, Grafana, Loki |
| Deployment | Docker, Coolify, WireGuard VPN |
```

### 9.2 README Updates per Milestone

| Milestone | README Section to Add/Update |
|---|---|
| M1.1 | Initial README created (Quick Start, Prerequisites) |
| M1.2 | Add Infrastructure section |
| M1.3 | Add Authentication section |
| M1.4 | Add Dashboard section |
| M1.9 | Add Connectors section |
| M1.12 | Add Trade Execution section |
| M2.1 | Add Skills section |
| M2.3 | Add Backtesting section |
| M2.5 | Add Trading Agents section |
| M2.6 | Add Strategy Agents section |
| M3.1 | Add Dev Agent section |
| M3.4 | Add Task Board section |
| M3.5 | Add Automations section |
| M3.13 | Finalize all documentation |

---

## 10. Code Documentation Standards

### 10.1 Python Docstring Standard

Use **Google-style docstrings**:

```python
"""Module for agent lifecycle management.

This module implements the AgentService class which orchestrates
agent creation, configuration, and state transitions across
OpenClaw instances via the Bridge Service API.
"""

from typing import Optional

class AgentService:
    """Orchestrates agent lifecycle operations.

    Handles creation, configuration updates, state transitions,
    and deletion of agents across OpenClaw instances. All operations
    are transactional — database writes and Bridge Service calls
    are rolled back on failure.

    Attributes:
        repo: AgentRepository for database operations.
        bridge_client: HTTP client for Bridge Service API calls.
        event_bus: Event bus for publishing agent events.
    """

    async def create_agent(
        self,
        payload: AgentCreate,
        user: User,
    ) -> Agent:
        """Create a new agent and register it on an OpenClaw instance.

        Args:
            payload: Agent configuration including name, type, instance,
                     skills, and risk parameters.
            user: The authenticated user creating the agent.

        Returns:
            The created Agent object with status CREATED.

        Raises:
            InstanceFullError: If the target instance is at capacity.
            BridgeConnectionError: If the Bridge Service is unreachable.
            ValidationError: If the payload fails validation.
        """
```

### 10.2 TypeScript Documentation Standard

Use **TSDoc** for exported functions and components:

```typescript
/**
 * Sortable, filterable, paginated data table built on TanStack Table.
 *
 * @example
 * ```tsx
 * <DataTable
 *   columns={[{ key: "name", header: "Name", sortable: true }]}
 *   data={agents}
 *   pageSize={20}
 *   onRowClick={(row) => navigate(`/agents/${row.id}`)}
 * />
 * ```
 */
export function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  pageSize = 20,
  emptyMessage = "No data found",
  onRowClick,
}: DataTableProps<T>) {
  // ...
}

/** Props for the DataTable component. */
interface DataTableProps<T> {
  /** Column definitions with key, header text, and sort/filter options. */
  columns: ColumnDef<T>[];
  /** Array of data objects to display in the table. */
  data: T[];
  /** Number of rows per page. Defaults to 20. */
  pageSize?: number;
  /** Message shown when data array is empty. */
  emptyMessage?: string;
  /** Callback fired when a row is clicked. */
  onRowClick?: (row: T) => void;
}
```

### 10.3 API Endpoint Documentation

FastAPI auto-generates OpenAPI documentation. Every endpoint must have:

```python
@router.get(
    "/{agent_id}",
    response_model=AgentDetailResponse,
    summary="Get agent details",
    description=(
        "Returns full agent details including current status, configuration, "
        "recent trades, backtest history, and performance metrics. "
        "Requires 'agents:read' permission."
    ),
    responses={
        404: {"description": "Agent not found"},
        403: {"description": "Insufficient permissions"},
    },
)
async def get_agent(
    agent_id: str = Path(..., description="UUID of the agent"),
    service: AgentService = Depends(get_agent_service),
    user: User = Depends(get_current_user),
) -> AgentDetailResponse:
    """Retrieve detailed information about a specific agent."""
```

### 10.4 Inline Comments — When to Use

**DO comment:**
- Non-obvious business rules: `# Circuit breaker resets at midnight Eastern, not UTC`
- Performance trade-offs: `# Using raw SQL here instead of ORM for 10x query speed on this aggregation`
- Security constraints: `# Never log raw credentials — only masked values`
- Algorithm explanations: `# Sharpe ratio uses 252 trading days for annualization`
- Workarounds: `# Alpaca API returns quantity as string, not int (their bug)`

**DO NOT comment:**
- What the code literally does: ~~`# Create a new agent`~~
- Variable assignments: ~~`# Set the status to CREATED`~~
- Import statements: ~~`# Import the FastAPI router`~~
- Function calls: ~~`# Call the bridge service`~~

---

## 11. Milestone Completion Protocol

### 11.1 Checklist (Execute for Every Milestone)

```
╔════════════════════════════════════════════════════════════════════╗
║  MILESTONE COMPLETION CHECKLIST                                   ║
╠════════════════════════════════════════════════════════════════════╣
║                                                                    ║
║  1. TESTS WRITTEN FIRST (TDD)                                    ║
║     □ Unit tests written and failing (RED phase documented)       ║
║     □ Integration tests written and failing                       ║
║     □ E2E tests written (if applicable)                          ║
║                                                                    ║
║  2. IMPLEMENTATION COMPLETE                                       ║
║     □ All tests passing (GREEN)                                   ║
║     □ Code refactored and clean (REFACTOR)                       ║
║     □ Design patterns applied correctly                           ║
║     □ Type hints on all functions (Python + TypeScript)           ║
║     □ Docstrings on all public APIs                              ║
║                                                                    ║
║  3. QUALITY GATES                                                 ║
║     □ Ruff lint: 0 errors                                        ║
║     □ Mypy: 0 errors (strict mode)                               ║
║     □ ESLint: 0 errors (strict mode)                             ║
║     □ Coverage: >= 90% on new Python code                        ║
║     □ Coverage: >= 85% on new TypeScript code                    ║
║                                                                    ║
║  4. REGRESSION SUITE                                              ║
║     □ New regression tests added for this milestone               ║
║     □ All existing regression tests still pass                    ║
║     □ E2E tests pass (if applicable)                             ║
║     □ No regressions introduced                                  ║
║                                                                    ║
║  5. DOCUMENTATION                                                 ║
║     □ README.md updated (new feature section)                    ║
║     □ Configuration Guide updated (new env vars, setup steps)    ║
║     □ API docs accurate (OpenAPI spec)                           ║
║     □ Code comments follow standards (Section 10)                ║
║                                                                    ║
║  6. REVIEW & MERGE                                                ║
║     □ PR created with description of changes                     ║
║     □ CI pipeline green                                          ║
║     □ Code review completed                                      ║
║     □ Acceptance criteria verified (from Milestones.md)          ║
║     □ Merged to main                                             ║
║                                                                    ║
║  7. TRACKING                                                      ║
║     □ Milestone marked COMPLETE                                   ║
║     □ Blockers/learnings documented                              ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
```

### 11.2 Milestone Status Transitions

```
PLANNED → IN_PROGRESS → TESTING → REVIEW → COMPLETE
                 │                    │
                 └── BLOCKED ─────────┘
```

| Status | Meaning |
|---|---|
| PLANNED | Not started, dependencies met |
| IN_PROGRESS | Tests being written or code being implemented |
| TESTING | Implementation done, running regression suite |
| REVIEW | PR open, awaiting code review |
| COMPLETE | Merged to main, all criteria met |
| BLOCKED | Waiting on dependency or external factor |

### 11.3 Example: Milestone M1.3 Completion

```markdown
## M1.3: Auth Service Migration & API Gateway — COMPLETE

### Test Evidence
- 15 unit tests: all passing (see CI run #42)
- 5 integration tests: all passing
- 15 regression tests added to test_auth_regression.py
- Coverage: 94% on new auth code

### Acceptance Criteria
- [x] Register a new user via POST /auth/register and receive JWT tokens
- [x] Access a protected /api/ endpoint with valid JWT
- [x] Invalid/expired JWT returns 401
- [x] MFA enrollment and verification works end-to-end
- [x] Role-based access: viewer cannot access admin endpoints (403)

### Documentation Updated
- [x] README.md: Added Authentication section
- [x] .env.example: Added JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_MINUTES
- [x] API docs: /auth/* endpoints documented in OpenAPI spec

### PR: #12 (merged to main)
```

---

## 12. Existing Code Reuse & Migration Plan

### 12.1 Services to Deprecate

These services are replaced by OpenClaw skills and are NOT carried into the new repository:

| v1 Service | Replacement in v2 | Deprecation Milestone |
|---|---|---|
| `services/nlp-parser/` | OpenClaw skills: `sentiment_classifier`, `trade_signal_parser` | M1.1 (not copied) |
| `services/sentiment-analyzer/` | OpenClaw skill: `sentiment_classifier` | M1.1 |
| `services/news-aggregator/` | OpenClaw skills: `fetch_news_headlines`, `news_impact_analyzer` | M1.1 |
| `services/ai-trade-recommender/` | OpenClaw trading agents | M1.1 |
| `services/signal-scorer/` | OpenClaw skill: `llm_trade_evaluator` | M1.1 |
| `services/option-chain-analyzer/` | OpenClaw skills: `options_chain_analyzer`, `options_greeks_analyzer` | M1.1 |
| `services/twitter-ingestor/` | Connector Framework: Twitter/X connector | M1.1 |
| `services/source-orchestrator/` | Connector Manager service | M1.1 |
| `services/audit-writer/` | Centralized logging | M1.1 |
| `shared/agents/` | OpenClaw agent framework | M1.1 |
| `shared/llm/client.py` | OpenClaw LLM integration | M1.1 |

### 12.2 Services to Migrate

| v1 Service | v2 Location | Migration Milestone | Changes |
|---|---|---|---|
| `services/auth-service/` | `apps/api/src/routes/auth.py` + `services/auth_service.py` | M1.3 | Merge into main API, add RBAC |
| `services/api-gateway/` | `apps/api/` | M1.3 | Rebuild with v2 routes |
| `services/dashboard-ui/` | `apps/dashboard/` | M1.4 | Rebuild, carry UI primitives |
| `services/discord-ingestor/` | `services/connector-manager/src/connectors/discord.py` | M1.9 | Refactor to BaseConnector |
| `services/reddit-ingestor/` | `services/connector-manager/src/connectors/reddit.py` | M2.8 | Refactor to BaseConnector |
| `services/trade-executor/` | `services/execution/` | M1.12 | Refactor to queue-based execution |
| `services/position-monitor/` | `services/global-monitor/` + OpenClaw Monitoring Agent | M2.13 | Split: backend monitor + AI agent |
| `services/notification-service/` | `services/connector-manager/src/connectors/` + Telegram bot | M3.6 | Expand to bidirectional channels |
| `services/trade-parser/` | OpenClaw skill: `trade_signal_parser` | M2.1 | Convert to SKILL.md |
| `services/strategy-agent/` | OpenClaw Strategy Agents | M2.6 | Replace with OpenClaw config |

### 12.3 Shared Libraries to Carry Forward

| v1 Module | v2 Location | Migration Milestone | Changes |
|---|---|---|---|
| `shared/broker/` | `shared/broker/` | M1.1 | Keep as-is, add new brokers in M2.11 |
| `shared/crypto/credentials.py` | `shared/crypto/credentials.py` | M1.1 | Keep as-is |
| `shared/kafka_utils/` | `shared/events/` | M1.1 | Refactor: Kafka → Redis Streams |
| `shared/market/calendar.py` | `shared/utils/market_calendar.py` | M1.1 | Keep as-is |
| `shared/models/` | `shared/db/models/` | M1.6 | Extend with 5 new entities |
| `shared/nlp/` | `shared/nlp/` | M1.1 | Keep, also convert to skills in M2.1 |
| `shared/discord_utils/` | `shared/discord_utils/` | M1.1 | Keep as-is |
| `shared/unusual_whales/` | Used by connector | M2.8 | Integrate into UW connector |
| `shared/whatsapp/sender.py` | `shared/whatsapp/sender.py` | M1.1 | Keep, enhance in M3.6 |
| `shared/retry.py` | `shared/utils/retry.py` | M1.1 | Keep as-is |
| `shared/dedup.py` | `shared/utils/dedup.py` | M1.1 | Keep as-is |
| `shared/rate_limiter.py` | `shared/utils/rate_limiter.py` | M1.1 | Keep as-is |
| `shared/feature_flags.py` | `shared/utils/feature_flags.py` | M1.1 | Keep as-is |
| `shared/graceful_shutdown.py` | `shared/utils/graceful_shutdown.py` | M1.1 | Keep as-is |
| `shared/config/base_config.py` | `apps/api/src/config.py` (pydantic-settings) | M1.1 | Rewrite with pydantic-settings |

### 12.4 Frontend Components to Carry Forward

| v1 Component | v2 Location | Changes |
|---|---|---|
| 19 Radix UI primitives | `apps/dashboard/src/components/ui/` | None — copy as-is |
| `cn()` utility | `apps/dashboard/src/lib/utils.ts` | None |
| `ThemeProvider` | `apps/dashboard/src/context/theme-context.tsx` | Adapt to new palette |
| `AuthContext` | `apps/dashboard/src/context/auth-context.tsx` | Adapt to new API |
| `TradingViewEmbed` | `apps/dashboard/src/components/charts/` | None |
| `TickerSearch` | `apps/dashboard/src/components/shared/` | None |
| `MarketCommandCenter` | `apps/dashboard/src/pages/market-command-center.tsx` | Add react-grid-layout |

### 12.5 Test Infrastructure to Carry Forward

| v1 Item | v2 Location | Changes |
|---|---|---|
| `tests/conftest.py` | `apps/api/tests/conftest.py` | Extend with new fixtures |
| `tests/unit/` (47 tests) | Selectively migrate applicable tests | Adapt to new module structure |
| `tests/integration/` (4 tests) | `apps/api/tests/integration/` | Adapt to new API routes |
| `tests/load/locustfile.py` | `tests/load/locustfile.py` | Update endpoints |
| `pyproject.toml [tool.pytest]` | `pyproject.toml [tool.pytest]` | Update Python to 3.12, testpaths |
| `.github/workflows/ci.yml` | `.github/workflows/ci.yml` | Expand to 12 services, add regression job |

### 12.6 Migration Sequence

```
M1.1: Copy shared libraries, UI primitives, test infra
  ↓
M1.3: Migrate auth-service into apps/api
  ↓
M1.4: Rebuild dashboard with carried-over components
  ↓
M1.6: Extend shared/models with new entities
  ↓
M1.9: Refactor discord-ingestor into Connector Framework
  ↓
M1.12: Refactor trade-executor into Execution Service
  ↓
M2.1: Convert trade-parser, nlp-parser to OpenClaw skills
  ↓
M2.8: Refactor reddit-ingestor into Connector Framework
  ↓
M2.12: Migrate MarketCommandCenter with react-grid-layout
  ↓
M2.13: Replace position-monitor with Global Monitor + OpenClaw agent
  ↓
M3.6: Expand notification-service into bidirectional channels
```

After M3.6, all v1 code has been migrated, refactored, or deprecated. The v1 repository can be archived.

---

## 13. Hybrid Local + VPS Node Architecture

### 13.1 Overview

The Architecture Plan defines 4 OpenClaw instances running on Hetzner VPS nodes. In practice, you may have multiple laptops at home sitting idle that collectively provide more compute power than cloud VPS nodes — for free. This section describes how to treat local laptops as first-class OpenClaw nodes alongside remote VPS nodes, all unified under a single WireGuard mesh.

**Three problems to solve:**

1. **Networking** — Local laptops sit behind a home router (NAT) with no public IP. VPS nodes have public IPs. They must all communicate as peers on a flat `10.0.1.0/24` network.
2. **Reliability** — Laptops sleep, lose Wi-Fi, or get closed. The system must gracefully handle nodes disappearing and reappearing without data loss or agent corruption.
3. **Unified management** — The dashboard and all backend services must treat local and remote nodes identically through a single node registry, while enforcing safety rules (no live trading on unreliable hardware).

### 13.2 Hybrid Topology

```
                         ┌────────────────────────────────┐
                         │         INTERNET                │
                         └────────────┬───────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────────┐
              │                       │                           │
              ▼                       ▼                           ▼
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│  COOLIFY SERVER       │ │  VPS NODE (OC-D)     │ │  HOME ROUTER         │
│  (WireGuard Hub)      │ │  Live Trading         │ │  NAT: 203.x.x.x     │
│  Public IP            │ │  Public IP            │ │                      │
│  WG: 10.0.1.1         │ │  WG: 10.0.1.12       │ │  ┌──────────────┐   │
│                       │ │                       │ │  │  LAN:        │   │
│  All core services    │ │  OpenClaw + Bridge    │ │  │ 192.168.1.x  │   │
│  (DB, Redis, MinIO,   │ │                       │ │  │              │   │
│   API, Dashboard)     │ │                       │ │  │  ┌────────┐  │   │
└──────────┬────────────┘ └──────────┬────────────┘ │  │  │Laptop 1│  │   │
           │                         │              │  │  │OC-B     │  │   │
           │   WireGuard encrypted tunnels          │  │  │WG:10.0. │  │   │
           │   (all nodes: 10.0.1.0/24)             │  │  │1.20     │  │   │
           │                         │              │  │  └────────┘  │   │
           ├─────────────────────────┤              │  │  ┌────────┐  │   │
           │                         │              │  │  │Laptop 2│  │   │
           │    ┌────────────────────┼──────────────┼──┤  │OC-C     │  │   │
           │    │                    │              │  │  │WG:10.0. │  │   │
           │    │                    │              │  │  │1.21     │  │   │
           │    │    ┌───────────────┼──────────────┼──┤  └────────┘  │   │
           │    │    │               │              │  │  ┌────────┐  │   │
           │    │    │               │              │  │  │Laptop 3│  │   │
           │    │    │               │              │  │  │OC-E     │  │   │
           │    │    │               │              │  │  │WG:10.0. │  │   │
           │    │    │               │              │  │  │1.22     │  │   │
           │    │    │               │              │  │  └────────┘  │   │
           │    │    │               │              │  └──────────────┘   │
           │    │    │               │              └──────────────────────┘
           ▼    ▼    ▼               ▼
    ┌──────────────────────────────────────────┐
    │  WireGuard overlay: 10.0.1.0/24          │
    │                                          │
    │  10.0.1.1   Coolify (hub, always on)     │
    │  10.0.1.12  VPS OC-D (always on)         │
    │  10.0.1.20  Laptop 1 (ephemeral)         │
    │  10.0.1.21  Laptop 2 (ephemeral)         │
    │  10.0.1.22  Laptop 3 (ephemeral)         │
    └──────────────────────────────────────────┘
```

**Key design decisions:**

- The Coolify server is always the WireGuard hub. It has a public IP and is always on. It never runs on a laptop.
- VPS nodes have public IPs and set `Endpoint` in WireGuard. They connect peer-to-peer with the hub.
- Local laptops are behind NAT with no public IP. They initiate outbound WireGuard connections to the hub using `PersistentKeepalive = 25` to maintain the NAT hole-punch. No port forwarding is required on the home router.
- All nodes — regardless of whether they are cloud or local — get a stable `10.0.1.x` WireGuard address that the Control Plane uses for Bridge Service communication.
- Local laptops on the same LAN can also communicate directly via their `192.168.x.x` addresses for ultra-low-latency agent-to-agent messages (optional optimization).

### 13.3 WireGuard Configuration for Local Nodes

The key difference between VPS peers and local peers is the absence of `Endpoint` on the server side for local nodes. Local nodes initiate the connection outward through NAT.

**Server-side config (Coolify `wg0.conf`) — VPS peer vs. Local peer:**

```ini
# ─── VPS PEER (has public IP, bidirectional initiation) ─────────────
[Peer]  # Node 4: OC-D Live Trading (Hetzner VPS)
PublicKey = <vps_node4_public_key>
AllowedIPs = 10.0.1.12/32
Endpoint = 159.69.xx.xx:51820        # <── VPS has a static public IP

# ─── LOCAL PEER (behind NAT, initiates outward) ─────────────────────
[Peer]  # Laptop 1: OC-B Data Research (Home LAN)
PublicKey = <laptop1_public_key>
AllowedIPs = 10.0.1.20/32
# No Endpoint — laptop initiates the connection to the hub

[Peer]  # Laptop 2: OC-C Risk/Promotion (Home LAN)
PublicKey = <laptop2_public_key>
AllowedIPs = 10.0.1.21/32
# No Endpoint

[Peer]  # Laptop 3: OC-E Backtesting (Home LAN)
PublicKey = <laptop3_public_key>
AllowedIPs = 10.0.1.22/32
# No Endpoint
```

**Laptop-side config (`wg0.conf` on each laptop):**

```ini
[Interface]
Address = 10.0.1.20/32               # Unique per laptop
PrivateKey = <laptop_private_key>
DNS = 1.1.1.1

[Peer]  # Coolify Server (WireGuard hub)
PublicKey = <server_public_key>
Endpoint = <coolify_public_ip>:51820  # The only endpoint laptops need
AllowedIPs = 10.0.1.0/24             # Route all WG traffic through hub
PersistentKeepalive = 25             # Keep NAT hole punched every 25 seconds
```

**Why this works behind NAT without port forwarding:**

1. The laptop sends an outbound UDP packet to the Coolify server's public IP on port 51820.
2. The home router creates a NAT mapping for this outbound connection.
3. `PersistentKeepalive = 25` sends a keepalive packet every 25 seconds, preventing the NAT mapping from expiring (most routers expire UDP mappings after 30–120 seconds).
4. The Coolify server can now send packets back through the same NAT mapping.
5. As long as the laptop is awake and has network, the tunnel stays alive.

**Adding a new laptop takes 3 steps:**

1. Generate keys on the laptop: `wg genkey | tee privatekey | wg pubkey > publickey`
2. Add a `[Peer]` block to the Coolify server's `wg0.conf` (no `Endpoint`, just `PublicKey` and `AllowedIPs`)
3. Create the laptop's `wg0.conf` pointing to the Coolify server

### 13.4 Node Registry & Classification

#### 13.4.1 Database Schema Addition

Add a `node_type` column to the existing `openclaw_instances` table:

```sql
ALTER TABLE openclaw_instances ADD COLUMN node_type VARCHAR(10) NOT NULL DEFAULT 'vps';
-- Values: 'vps' (cloud, always-on) or 'local' (home laptop, ephemeral)

ALTER TABLE openclaw_instances ADD COLUMN auto_registered BOOLEAN NOT NULL DEFAULT false;
-- True if the node registered itself via Bridge auto-registration

ALTER TABLE openclaw_instances ADD COLUMN last_offline_at TIMESTAMPTZ;
-- Tracks when the node last went offline (for local reliability metrics)

ALTER TABLE openclaw_instances ADD COLUMN capabilities JSONB DEFAULT '{}';
-- Hardware capabilities reported by the node: {"cpu_cores": 8, "ram_gb": 16, "gpu": false, "os": "darwin"}
```

#### 13.4.2 Agent Placement Rules

The Orchestrator enforces placement rules based on `node_type`:

| Agent Type | Allowed on `vps` | Allowed on `local` | Rationale |
|---|---|---|---|
| Trading Agent (live account) | Yes | **No** | Cannot risk laptop sleeping during open position |
| Trading Agent (paper account) | Yes | Yes | Paper trading is risk-free |
| Strategy Agent (live) | Yes | **No** | Heartbeat-driven agent must be always-on for live |
| Strategy Agent (paper/backtest) | Yes | Yes | Safe for non-critical workloads |
| Monitoring Agent | Yes | **No** | Must be online to close positions |
| Data/Research Agent | Yes | Yes | Non-critical, can pause |
| Backtesting Agent | Yes | Yes | Ideal for local — heavy compute, no market risk |
| Dev Agent | Yes | **No** | Must continuously monitor all agents |
| Task Board Agent | Yes | Yes | Tasks can queue while node is offline |

Enforcement point:

```python
# services/orchestrator/src/workers/agent_lifecycle.py

async def validate_agent_placement(agent: AgentCreate, instance: OpenClawInstance) -> None:
    """Reject agent placement that violates node_type safety rules."""
    if instance.node_type == "local":
        if agent.type == "trading" and agent.account_mode == "live":
            raise PlacementError(
                f"Live trading agents cannot run on local node '{instance.name}'. "
                f"Use a VPS node for live trading."
            )
        if agent.type == "monitoring":
            raise PlacementError(
                f"Monitoring agents cannot run on local node '{instance.name}'. "
                f"Monitoring agents must be always-on."
            )
        if agent.type in ("trading", "strategy") and agent.account_mode == "live":
            raise PlacementError(
                f"Live agents cannot run on local node '{instance.name}'."
            )
```

#### 13.4.3 Dashboard Display

The Instances panel in the Connectors tab and the Agent Network graph display node type:

- `vps` nodes: cloud icon + "Cloud" badge (always green when healthy)
- `local` nodes: laptop icon + "Local" badge (green when online, gray when offline)
- Tooltip shows: OS, CPU cores, RAM, uptime since last boot, offline history

The agent creation wizard, in the Instance Selection step, shows:
- Node name, type badge, current agent count, CPU/RAM usage
- Warning icon on `local` nodes: "This is a local node. It may go offline. Live trading agents are not allowed."
- Smart sort: VPS nodes first, then local nodes sorted by available capacity

### 13.5 Graceful Offline Handling for Local Nodes

#### 13.5.1 Offline Detection

The existing heartbeat mechanism (Section 9.5 of ArchitecturePlan.md) already handles this:

```
Heartbeat every 60 seconds:
    Backend API → GET http://10.0.1.20:18800/heartbeat → Bridge Service

Miss 1 (60s):  Node status → DEGRADED (warning in dashboard)
Miss 2 (120s): Node status → DEGRADED (alert published)
Miss 3 (180s): Node status → OFFLINE
                 │
                 ├── All agents on this node → PAUSED_OFFLINE
                 ├── Alert sent to configured channels (Discord, Telegram)
                 ├── last_offline_at updated in database
                 └── Dashboard shows node as gray with "Offline since HH:MM"
```

#### 13.5.2 New Agent State: PAUSED_OFFLINE

Add `PAUSED_OFFLINE` to the agent state machine:

```
                ┌─── (node goes offline) ───┐
                │                           ▼
RUNNING ────────┼────────────────► PAUSED_OFFLINE
BACKTESTING ────┘                       │
                                        │ (node comes back online)
                                        ▼
                                   RUNNING / BACKTESTING
                                   (resumes previous state)
```

- `PAUSED_OFFLINE` is distinct from user-initiated `PAUSED`. The user did not choose to pause; the node disappeared.
- When a node comes back, the Bridge Service sends a re-registration heartbeat. The Orchestrator detects the node is back and automatically transitions agents from `PAUSED_OFFLINE` back to their previous state.
- If a `PAUSED_OFFLINE` agent has been offline for more than 24 hours, it stays paused and requires manual intervention (to prevent stale agents from auto-resuming on old data).

#### 13.5.3 Agent Migration (Local → VPS)

For critical agents that need to keep running when a laptop goes offline, the dashboard provides a "Migrate to VPS" action:

```
Dashboard: Agent Detail → "Migrate to VPS" button
    │
    ▼
1. Select target VPS instance (dropdown, filtered to vps nodes with capacity)
    │
    ▼
2. Backend fetches agent config from source Bridge:
   GET http://10.0.1.20:18800/agents/<id>/export
   Response: { agents_md, tools_md, soul_md, memory_md, heartbeat_md, skills[], sessions[] }
    │
    ▼
3. Backend creates agent on target VPS Bridge:
   POST http://10.0.1.12:18800/agents
   Body: { ...exported config }
    │
    ▼
4. Backend updates database: agent.instance_id = new_instance
   Old agent workspace marked for cleanup
    │
    ▼
5. Agent resumes on VPS within 60 seconds (next heartbeat)
```

Migration can also be triggered automatically by the Dev Agent if a local node has been offline for more than 30 minutes and the agent has pending work.

### 13.6 Local Node Provisioning Script

**`infra/scripts/provision-local-node.sh`** — turns any macOS or Linux laptop into a Phoenix OpenClaw node:

```bash
#!/bin/bash
set -euo pipefail

# ─── Usage ──────────────────────────────────────────────────────────
# ./provision-local-node.sh \
#   --name laptop-studio \
#   --ip 10.0.1.20 \
#   --server-pubkey "SERVER_PUBLIC_KEY_BASE64" \
#   --server-endpoint "203.0.113.10:51820" \
#   --bridge-token "your-bridge-secret-token" \
#   --control-plane "http://10.0.1.1:8011"

# ─── Parse arguments ───────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --name) NODE_NAME="$2"; shift 2 ;;
    --ip) NODE_IP="$2"; shift 2 ;;
    --server-pubkey) SERVER_PUBKEY="$2"; shift 2 ;;
    --server-endpoint) SERVER_ENDPOINT="$2"; shift 2 ;;
    --bridge-token) BRIDGE_TOKEN="$2"; shift 2 ;;
    --control-plane) CONTROL_PLANE="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

OS=$(uname -s)
echo "=== Provisioning Phoenix node '$NODE_NAME' on $OS ==="

# ─── Step 1: Install dependencies ──────────────────────────────────
echo "[1/7] Installing dependencies..."
if [[ "$OS" == "Darwin" ]]; then
  brew install wireguard-tools node python@3.12
elif [[ "$OS" == "Linux" ]]; then
  sudo apt update && sudo apt install -y wireguard nodejs npm python3.12 python3.12-venv
fi

# ─── Step 2: Configure WireGuard ───────────────────────────────────
echo "[2/7] Configuring WireGuard tunnel..."
PRIVATE_KEY=$(wg genkey)
PUBLIC_KEY=$(echo "$PRIVATE_KEY" | wg pubkey)

if [[ "$OS" == "Darwin" ]]; then
  WG_CONF_DIR="/usr/local/etc/wireguard"
  mkdir -p "$WG_CONF_DIR"
else
  WG_CONF_DIR="/etc/wireguard"
fi

cat > "$WG_CONF_DIR/wg0.conf" << EOF
[Interface]
Address = ${NODE_IP}/32
PrivateKey = ${PRIVATE_KEY}
DNS = 1.1.1.1

[Peer]
PublicKey = ${SERVER_PUBKEY}
Endpoint = ${SERVER_ENDPOINT}
AllowedIPs = 10.0.1.0/24
PersistentKeepalive = 25
EOF

if [[ "$OS" == "Darwin" ]]; then
  sudo wg-quick up wg0
else
  sudo systemctl enable wg-quick@wg0
  sudo systemctl start wg-quick@wg0
fi

echo "  WireGuard tunnel active. Public key: $PUBLIC_KEY"
echo "  >>> ADD THIS PEER BLOCK TO YOUR COOLIFY SERVER wg0.conf: <<<"
echo ""
echo "  [Peer]  # ${NODE_NAME} (local)"
echo "  PublicKey = ${PUBLIC_KEY}"
echo "  AllowedIPs = ${NODE_IP}/32"
echo ""

# ─── Step 3: Install OpenClaw ──────────────────────────────────────
echo "[3/7] Installing OpenClaw..."
npm install -g @openclaw/cli
mkdir -p /opt/phoenix/openclaw/agents
openclaw onboard --skip-channel 2>/dev/null || true

# ─── Step 4: Deploy Bridge Service ─────────────────────────────────
echo "[4/7] Deploying Bridge Service..."
mkdir -p /opt/phoenix/bridge
cd /opt/phoenix/bridge

python3.12 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn httpx boto3 prometheus-client

cat > .env << EOF
BRIDGE_TOKEN=${BRIDGE_TOKEN}
NODE_TYPE=local
NODE_NAME=${NODE_NAME}
CONTROL_PLANE_URL=${CONTROL_PLANE}
AUTO_REGISTER_ON_STARTUP=true
MINIO_ENDPOINT=10.0.1.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
INHIBIT_SLEEP=true
EOF

# ─── Step 5: Set up systemd / launchd ──────────────────────────────
echo "[5/7] Configuring auto-start services..."
if [[ "$OS" == "Linux" ]]; then
  sudo cat > /etc/systemd/system/phoenix-bridge.service << SVCEOF
[Unit]
Description=Phoenix Bridge Service
After=network.target wg-quick@wg0.service

[Service]
Type=simple
WorkingDirectory=/opt/phoenix/bridge
ExecStart=/opt/phoenix/bridge/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 18800
Restart=always
RestartSec=5
EnvironmentFile=/opt/phoenix/bridge/.env

[Install]
WantedBy=multi-user.target
SVCEOF
  sudo systemctl enable phoenix-bridge
  sudo systemctl start phoenix-bridge
elif [[ "$OS" == "Darwin" ]]; then
  # macOS: use launchd plist
  cat > ~/Library/LaunchAgents/com.phoenix.bridge.plist << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.phoenix.bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/phoenix/bridge/.venv/bin/uvicorn</string>
    <string>main:app</string>
    <string>--host</string><string>0.0.0.0</string>
    <string>--port</string><string>18800</string>
  </array>
  <key>WorkingDirectory</key><string>/opt/phoenix/bridge</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
PLISTEOF
  launchctl load ~/Library/LaunchAgents/com.phoenix.bridge.plist
fi

# ─── Step 6: Set up skill sync ─────────────────────────────────────
echo "[6/7] Configuring skill sync..."
mkdir -p /opt/phoenix/skills/phoenix
cat > /opt/phoenix/scripts/sync-skills.sh << 'SYNCEOF'
#!/bin/bash
AWS_ACCESS_KEY_ID=minioadmin \
AWS_SECRET_ACCESS_KEY=minioadmin \
aws s3 sync s3://phoenix-skills/ /opt/phoenix/skills/phoenix/ \
  --endpoint-url http://10.0.1.1:9000 --quiet
SYNCEOF
chmod +x /opt/phoenix/scripts/sync-skills.sh

# Run every 5 minutes
(crontab -l 2>/dev/null; echo "*/5 * * * * /opt/phoenix/scripts/sync-skills.sh") | crontab -

# ─── Step 7: Sleep inhibitor (optional) ────────────────────────────
echo "[7/7] Configuring sleep inhibitor..."
if [[ "$OS" == "Darwin" ]]; then
  # macOS: caffeinate prevents sleep while process runs
  cat > ~/Library/LaunchAgents/com.phoenix.caffeinate.plist << CAFEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.phoenix.caffeinate</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-di</string>
    <string>-w</string><string>0</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
CAFEOF
  launchctl load ~/Library/LaunchAgents/com.phoenix.caffeinate.plist
  echo "  Sleep inhibitor: caffeinate running (display sleep still allowed, system sleep blocked)"
elif [[ "$OS" == "Linux" ]]; then
  echo "  Sleep inhibitor: use 'systemd-inhibit --what=sleep --who=phoenix' when running agents"
fi

echo ""
echo "=== Node '$NODE_NAME' provisioned successfully ==="
echo ""
echo "Next steps:"
echo "  1. Add the peer block above to your Coolify server's /etc/wireguard/wg0.conf"
echo "  2. Restart WireGuard on the server: sudo wg-quick down wg0 && sudo wg-quick up wg0"
echo "  3. Verify tunnel: ping 10.0.1.1 (from this machine)"
echo "  4. The Bridge Service will auto-register with the Control Plane"
echo "  5. Check the dashboard — your new node should appear in the Instances list"
```

**Deprovisioning:** Run `infra/scripts/deprovision-local-node.sh` to remove WireGuard config, stop services, and clean up the workspace.

### 13.7 Bridge Service Auto-Registration

When `AUTO_REGISTER_ON_STARTUP=true`, the Bridge Service on a local node automatically registers itself with the Control Plane on startup:

```python
# openclaw/bridge/src/auto_register.py

async def auto_register(settings: BridgeSettings) -> None:
    """Register this node with the Control Plane on startup.

    Called during Bridge Service lifespan. If the instance already exists
    in the database (by name), updates its status to ONLINE. If it does
    not exist, creates a new instance record.
    """
    payload = {
        "name": settings.NODE_NAME,
        "host": get_wireguard_ip(),       # 10.0.1.x from wg0 interface
        "port": 18800,
        "role": "general",                # Assigned later via dashboard
        "node_type": settings.NODE_TYPE,  # "local" or "vps"
        "capabilities": {
            "cpu_cores": psutil.cpu_count(),
            "ram_gb": round(psutil.virtual_memory().total / (1024**3)),
            "os": platform.system().lower(),
            "gpu": has_nvidia_gpu(),
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.CONTROL_PLANE_URL}/api/v2/instances/register",
            json=payload,
            headers={"X-Bridge-Token": settings.BRIDGE_TOKEN},
            timeout=10,
        )

    if response.status_code in (200, 201):
        logger.info(f"Registered with Control Plane as '{settings.NODE_NAME}'")
    else:
        logger.warning(f"Registration failed: {response.status_code} {response.text}")
```

The backend API endpoint:

```python
# apps/api/src/routes/instances.py

@router.post(
    "/register",
    summary="Register or re-register an OpenClaw instance",
    description="Called by Bridge Service on startup. Creates or updates instance record.",
)
async def register_instance(
    payload: InstanceRegister,
    bridge_token: str = Header(..., alias="X-Bridge-Token"),
    service: InstanceService = Depends(get_instance_service),
) -> InstanceResponse:
    validate_bridge_token(bridge_token)
    return await service.register_or_update(payload)
```

### 13.8 Local-to-Local Agent Communication (LAN Optimization)

When two agents are on laptops on the same LAN, inter-agent messages can bypass the WireGuard tunnel entirely for lower latency:

```
Agent on Laptop 1 (10.0.1.20 / 192.168.1.101)
    │
    │ message to Agent on Laptop 2
    │
    ▼
Bridge Service checks peer registry:
    │
    ├── Is target on same LAN? (same 192.168.x.0/24 subnet?)
    │   │
    │   ├── YES → Send directly to 192.168.1.102:18800 (~0.5ms)
    │   │
    │   └── NO → Send via WireGuard to 10.0.1.21:18800 (~5-15ms)
    │             (routes through Coolify hub)
```

**LAN peer discovery** uses mDNS (Avahi on Linux, Bonjour on macOS):

```python
# openclaw/bridge/src/lan_discovery.py

import asyncio
from zeroconf import ServiceBrowser, Zeroconf

SERVICE_TYPE = "_phoenix-bridge._tcp.local."

class LANPeerDiscovery:
    """Discovers other Phoenix Bridge Services on the local network.

    Uses mDNS/DNS-SD to find peers without configuration. Each Bridge
    Service advertises itself as a _phoenix-bridge._tcp service with
    its WireGuard IP as a TXT record for identity correlation.
    """

    def __init__(self):
        self.lan_peers: dict[str, str] = {}  # wg_ip -> lan_ip

    def on_service_found(self, name: str, info):
        wg_ip = info.properties.get(b"wg_ip", b"").decode()
        lan_ip = info.parsed_addresses()[0]
        self.lan_peers[wg_ip] = lan_ip

    def get_lan_address(self, wg_ip: str) -> str | None:
        """If the target WireGuard IP is on the same LAN, return its LAN IP."""
        return self.lan_peers.get(wg_ip)
```

This is an optional optimization. All communication works correctly over WireGuard; the LAN path just reduces latency for co-located agents.

### 13.9 Updated Node Specifications

**Hybrid deployment: 2 VPS + 3 local laptops**

| Node | Role | Location | Type | CPU | RAM | Disk | Cost |
|---|---|---|---|---|---|---|---|
| Node 1 | Coolify Server (core services) | Hetzner CX42 | `vps` | 8 vCPU | 16 GB | 160 GB | ~$28/mo |
| Node 2 | OC-A: Strategy Lab | Home Laptop 1 (MacBook Pro) | `local` | 10 core (M2) | 16 GB | 512 GB | $0 |
| Node 3 | OC-B: Data & Research | Home Laptop 2 (ThinkPad) | `local` | 8 core (i7) | 16 GB | 256 GB | $0 |
| Node 4 | OC-D: Live Trading + Risk | Hetzner CX42 | `vps` | 8 vCPU | 16 GB | 160 GB | ~$28/mo |
| Node 5 | OC-E: Backtesting + ML | Home Laptop 3 (workstation) | `local` | 12 core | 32 GB | 1 TB | $0 |
| **Total** | | | | **46 cores** | **96 GB** | **2 TB+** | **~$56/mo** |

**Comparison with VPS-only deployment:**

| Metric | VPS-only (4 nodes) | Hybrid (2 VPS + 3 local) | Improvement |
|---|---|---|---|
| Monthly cost | ~$84 | ~$56 | 33% cheaper |
| Total CPU | 24 vCPU | 46 cores | ~2x more |
| Total RAM | 48 GB | 96 GB | 2x more |
| Total disk | 480 GB | 2+ TB | 4x more |
| Backtest capacity | Limited by VPS | Laptop 3 runs heavy backtests | Much faster |
| Reliability for live trading | High (all VPS) | High (live on VPS only) | Same |

**Alternative configurations:**

- **All-local (development):** 1 VPS (Coolify) + all OpenClaw on local laptops = ~$28/mo. Only for paper trading / development.
- **Mostly-VPS (production):** 3 VPS nodes + 1 local laptop for overflow backtesting = ~$70/mo.
- **Maximum hybrid:** 1 VPS (Coolify) + 1 VPS (live trading) + N local laptops for everything else. Scales compute by plugging in more laptops.

### 13.10 TDD Tests for Hybrid Node Support

| Test File | Test Function | Description |
|---|---|---|
| `apps/api/tests/integration/test_instance_routes.py` | `test_register_local_node` | Local node auto-registers via Bridge startup |
| `apps/api/tests/integration/test_instance_routes.py` | `test_register_vps_node` | VPS node registers with `node_type=vps` |
| `apps/api/tests/unit/test_instance_service.py` | `test_reregister_updates_existing` | Re-registration after offline updates status, not duplicates |
| `services/orchestrator/tests/unit/test_agent_placement.py` | `test_live_trading_rejected_on_local` | Agent creation with `account.mode=live` on `local` node returns error |
| `services/orchestrator/tests/unit/test_agent_placement.py` | `test_paper_trading_allowed_on_local` | Paper trading agent accepted on local node |
| `services/orchestrator/tests/unit/test_agent_placement.py` | `test_monitoring_agent_rejected_on_local` | Monitoring agent rejected on local node |
| `services/orchestrator/tests/unit/test_agent_placement.py` | `test_backtesting_allowed_on_local` | Backtesting agent accepted on local node |
| `services/orchestrator/tests/unit/test_state_machine.py` | `test_running_to_paused_offline` | Agent transitions to PAUSED_OFFLINE when node goes offline |
| `services/orchestrator/tests/unit/test_state_machine.py` | `test_paused_offline_to_running_on_reconnect` | Agent resumes when node comes back within 24h |
| `services/orchestrator/tests/unit/test_state_machine.py` | `test_paused_offline_stays_paused_after_24h` | Agent stays paused if offline > 24 hours |
| `apps/api/tests/integration/test_agent_migration.py` | `test_migrate_agent_local_to_vps` | Agent config exported from local, imported to VPS, database updated |
| `apps/api/tests/integration/test_agent_migration.py` | `test_migrate_preserves_memory` | MEMORY.md and session data transferred correctly |
| `openclaw/bridge/tests/unit/test_auto_register.py` | `test_auto_register_on_startup` | Bridge sends registration POST on startup |
| `openclaw/bridge/tests/unit/test_auto_register.py` | `test_auto_register_retries_on_failure` | Registration retries with backoff if Control Plane unavailable |
| `openclaw/bridge/tests/unit/test_lan_discovery.py` | `test_discovers_lan_peer` | mDNS discovers other Bridge on same subnet |
| `openclaw/bridge/tests/unit/test_lan_discovery.py` | `test_routes_via_lan_when_available` | Message sent to LAN IP instead of WG IP for co-located agents |
| `openclaw/bridge/tests/unit/test_lan_discovery.py` | `test_falls_back_to_wireguard` | Message sent via WG when LAN peer not found |
| `tests/regression/test_heartbeat_regression.py` | `test_local_node_offline_detection` | 3 missed heartbeats marks node OFFLINE |
| `tests/regression/test_heartbeat_regression.py` | `test_local_node_reconnect_resumes_agents` | Agents resume after node reconnects |

### 13.11 Configuration Guide Additions

Add the following to `.env.example` and the Configuration Guide (Section 8):

```env
# ===========================================================================
# HYBRID NODE CONFIGURATION (local nodes only)
# ===========================================================================

# Node classification: "vps" for always-on cloud nodes, "local" for home laptops
NODE_TYPE=local

# Human-readable name for this node (shown in dashboard)
NODE_NAME=laptop-studio

# Auto-registration: Bridge registers with Control Plane on startup
AUTO_REGISTER_ON_STARTUP=true
CONTROL_PLANE_URL=http://10.0.1.1:8011

# Sleep inhibitor: prevent laptop from sleeping while agents run
# macOS: caffeinate -di (blocks idle sleep and display sleep)
# Linux: systemd-inhibit --what=sleep --who=phoenix
INHIBIT_SLEEP=true
INHIBIT_SLEEP_COMMAND=caffeinate -di

# LAN optimization: enable mDNS peer discovery for same-subnet communication
LAN_DISCOVERY_ENABLED=true

# Offline threshold: seconds without heartbeat before marking node OFFLINE
# (Control Plane setting, not per-node)
# HEARTBEAT_OFFLINE_THRESHOLD_SECONDS=180

# Auto-resume timeout: hours after which PAUSED_OFFLINE agents will NOT
# auto-resume (require manual intervention)
# AUTO_RESUME_TIMEOUT_HOURS=24
```

### 13.12 Implementation Milestone Mapping

Hybrid node support integrates into the existing milestones:

| Milestone | Hybrid Work Added |
|---|---|
| M1.2 (Infrastructure) | Add local node WireGuard templates, `provision-local-node.sh`, `deprovision-local-node.sh` |
| M1.6 (Database Schema) | Add `node_type`, `auto_registered`, `last_offline_at`, `capabilities` columns to `openclaw_instances` |
| M1.7 (Bridge Service) | Add auto-registration endpoint, `NODE_TYPE` config, hardware capability reporting |
| M1.8 (First Instance) | Test with one local laptop as first instance (validates NAT traversal) |
| M1.11 (Agent CRUD) | Add agent placement validation rules based on `node_type` |
| M2.4 (Agent Lifecycle) | Add `PAUSED_OFFLINE` state to state machine, offline detection logic |
| M2.10 (Agent Comms) | Add LAN peer discovery for same-subnet optimization |
| M3.1 (Dev Agent) | Dev Agent monitors local node reliability metrics, triggers auto-migration |
| M3.8 (Network Viz) | Local/Cloud badges on nodes, offline visualization |
