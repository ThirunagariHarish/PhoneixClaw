# Project Phoenix v2 — Milestones & Delivery Plan

**Version:** 1.0.0
**Date:** March 3, 2026
**Status:** Draft
**Reference:** [PRD v2.1.0](PRD.md) · [Architecture Plan](ArchitecturePlan.md)

---

## Table of Contents

- [Overview](#overview)
- [Phase 1 — Foundation (Weeks 1–8)](#phase-1--foundation-weeks-18)
- [Phase 2 — Intelligence (Weeks 9–18)](#phase-2--intelligence-weeks-918)
- [Phase 3 — Advanced (Weeks 19–26)](#phase-3--advanced-weeks-1926)
- [Dependency Graph](#dependency-graph)
- [Concurrent Build Matrix](#concurrent-build-matrix)
- [Risk Register](#risk-register)

---

## Overview

| Phase | Weeks | Focus | Milestones |
|---|---|---|---|
| Phase 1 — Foundation | 1–8 | Infrastructure, core dashboard, auth, first OpenClaw integration | M1.1 – M1.13 |
| Phase 2 — Intelligence | 9–18 | Full agent lifecycle, backtesting, skills, strategies, performance | M2.1 – M2.15 |
| Phase 3 — Advanced | 19–26 | Dev Agent, RL, Task Board, automations, admin, PWA, production hardening | M3.1 – M3.14 |

**Total Milestones:** 42
**Total Duration:** 26 weeks (~6 months)

### Repository & delivery

- **Official source:** PhoenixClaw organization repository (e.g. `PhoenixClaw/phoenix`). All development and deployment use this repo as the source of truth.
- **Do not push to the earlier/original repository.** All pushes go to the PhoenixClaw org repo only.

---

## Phase 1 — Foundation (Weeks 1–8)

Phase 1 establishes the core platform: new repository, infrastructure, authentication, dashboard shell with all tab placeholders, database schema, first OpenClaw instance, and the execution pipeline for placing trades. By the end of Phase 1, you can create a basic agent via the dashboard, see it on an OpenClaw instance, and place a paper trade through the execution queue. See [Architecture Plan §3 Service Registry](ArchitecturePlan.md#3-service-architecture) and [§4 Database Architecture](ArchitecturePlan.md#4-database-architecture).

---

### M1.1: Repository Scaffolding & CI/CD Pipeline

**Duration:** Week 1 (5 days)
**Dependencies:** None
**Owner:** DevOps / Lead Engineer

**Description:**
Create a new monorepo for Phoenix v2 with a well-defined directory structure, linting, formatting, and a GitHub Actions CI/CD pipeline that builds, tests, and pushes Docker images.

**Deliverables:**
- New GitHub repository under **PhoenixClaw** organization (e.g. `PhoenixClaw/phoenix`) initialized with monorepo structure:
  ```
  phoenix/
  ├── apps/
  │   ├── api/                # FastAPI backend (auth + API)
  │   └── dashboard/          # React + Vite frontend
  ├── openclaw/
  │   ├── configs/            # Base agent configs
  │   ├── skills/             # Central skill repository
  │   └── bridge/             # Bridge Service
  ├── services/               # Additional/legacy services
  │   ├── orchestrator/       # BullMQ worker
  │   ├── execution/          # Trade execution
  │   ├── global-monitor/     # Position monitor
  │   ├── connector-manager/  # Data source connectors
  │   ├── backtest-runner/    # Sandboxed backtesting
  │   ├── skill-sync/         # Skill distribution
  │   ├── automation/         # Automation scheduler
  │   ├── agent-comm/         # Inter-agent communication router
  │   └── ws-gateway/         # WebSocket gateway
  ├── shared/
  │   ├── db/                 # SQLAlchemy models, migrations
  │   ├── events/             # Event bus client library
  │   ├── crypto/             # Fernet credential encryption
  │   └── utils/              # Shared utilities
  ├── infra/
  │   ├── docker-compose.yml
  │   ├── docker-compose.coolify.yml
  │   ├── wireguard/
  │   └── scripts/
  ├── .github/workflows/
  │   ├── ci.yml
  │   └── deploy.yml
  ├── pyproject.toml
  ├── package.json
  └── README.md
  ```
- GitHub Actions CI: lint (ruff + eslint), type-check (mypy + tsc), unit tests (pytest + vitest)
- GitHub Actions Deploy: build Docker images, push to ghcr.io, trigger Coolify webhook
- Pre-commit hooks: ruff, eslint, prettier
- `.env.example` with all required environment variables documented

**Acceptance Criteria:**
- [ ] `git clone` and `make dev` starts all services locally via Docker Compose
- [ ] Pushing to `main` triggers CI pipeline and produces green status
- [ ] Docker images published to ghcr.io on successful CI

---

### M1.2: Infrastructure Provisioning

**Duration:** Week 1–2 (7 days)
**Dependencies:** M1.1
**Owner:** DevOps

**Description:**
Provision all VPS nodes, install Coolify, configure WireGuard VPN, and deploy core infrastructure services (PostgreSQL, Redis, MinIO).

**Deliverables:**
- Coolify server provisioned (Hetzner CX42)
- 1–3 OpenClaw VPS nodes provisioned (Hetzner CX32/CX42)
- WireGuard VPN mesh configured (hub-spoke topology from Coolify server)
- Firewall rules applied (only ports 22, 80, 443, 51820 on public interfaces)
- DNS records configured (`phoenix.yourdomain.com`)
- PostgreSQL 16 + TimescaleDB deployed on Coolify
- Redis 7 deployed on Coolify
- MinIO deployed on Coolify with buckets: `phoenix-backtests`, `phoenix-skills`, `phoenix-models`, `phoenix-code`, `phoenix-reports`
- Infrastructure-as-code scripts in `infra/scripts/`

**Acceptance Criteria:**
- [ ] All nodes pingable via WireGuard (e.g., `ping 10.0.1.10` from Coolify server)
- [ ] `psql` connects to PostgreSQL from any node via WireGuard
- [ ] `redis-cli ping` returns PONG from any node via WireGuard
- [ ] MinIO console accessible at `https://minio.phoenix.yourdomain.com`
- [ ] `https://phoenix.yourdomain.com` serves a placeholder page with valid SSL

---

### M1.3: Auth Service Migration & API Gateway

**Duration:** Week 2–3 (7 days)
**Dependencies:** M1.1, M1.2
**Owner:** Backend Engineer

**Note:** Auth is implemented **inside the Backend API** (`apps/api`) at `/auth/*` (single FastAPI app on port 8011). A separate Auth Service on port 8001 is optional for future split.

**Description:**
Migrate the authentication service from Phoenix v1, update it for the new schema, and configure nginx as the API gateway with routing for all endpoints.

**Deliverables:**
- Auth Service migrated from existing `services/auth-service/`:
  - JWT token issuance (access: 60min, refresh: 7 days)
  - User registration and login
  - MFA (TOTP) support
  - Password reset flow
  - RBAC with 5 roles: admin, manager, trader, viewer, custom
  - 20 granular permissions (see PRD Section 3.9)
- User model in new PostgreSQL schema
- `/auth/login`, `/auth/register`, `/auth/refresh`, `/auth/mfa/setup`, `/auth/mfa/verify` endpoints
- nginx reverse proxy configuration (auth consolidated in Backend API):
  - `/api/` → Backend API (:8011)
  - `/auth/` → Backend API (:8011)
  - `/ws/` → WebSocket Gateway (:8031)
  - `/` → Dashboard static files
- CORS configuration for dashboard origin
- Rate limiting middleware (100 req/min for auth endpoints)

**Acceptance Criteria:**
- [ ] Register a new user via `POST /auth/register` and receive JWT tokens
- [ ] Access a protected `/api/` endpoint with valid JWT
- [ ] Invalid/expired JWT returns 401
- [ ] MFA enrollment and verification works end-to-end
- [ ] Role-based access: viewer cannot access admin endpoints (403)

---

### M1.4: Dashboard Shell & Navigation

**Duration:** Week 2–3 (7 days)
**Dependencies:** M1.1
**Owner:** Frontend Engineer

**Description:**
Build the dashboard application shell: React + Vite + Tailwind CSS + Radix UI. Implement the main layout, sidebar/bottom navigation, routing for all 10 tabs, and authentication flow (login, logout, session management).

**Deliverables:**
- Vite 5 + React 18 + TypeScript project in `services/dashboard/`
- Tailwind CSS v4 configuration with dark mode, custom Phoenix color palette
- AppShell component (sidebar for desktop, bottom nav for mobile)
- ThemeProvider (dark/light toggle, persisted in localStorage)
- React Router v6 with routes for all 12 tabs:
  1. `/trades` — Trades
  2. `/positions` — Positions
  3. `/performance` — Performance
  4. `/agents` — Agents
  5. `/strategies` — Strategies
  6. `/connectors` — Connectors
  7. `/skills` — Skills & Agent Config
  8. `/market` — Market Command Center
  9. `/admin` — Admin & User Management
  10. `/network` — Agent Network
  11. `/tasks` — Task Board & Automations
  12. `/settings` — Settings
- AuthContext (login, logout, token refresh, protected route wrapper)
- Placeholder pages for each route (tab name + "Coming soon" message)
- Loading states and error boundaries
- Responsive: sidebar collapses to bottom nav below 768px

**Acceptance Criteria:**
- [ ] Dashboard loads at `https://phoenix.yourdomain.com` with login screen
- [ ] After login, sidebar shows all 12 tabs with icons
- [ ] Clicking each tab navigates to its placeholder page
- [ ] On mobile (< 768px), navigation switches to bottom bar
- [ ] Dark/light theme toggle works and persists
- [ ] Unauthenticated users are redirected to login

---

### M1.5: UI Component Library

**Duration:** Week 3 (5 days)
**Dependencies:** M1.4
**Owner:** Frontend Engineer

**Description:**
Build the reusable component library from Radix UI primitives and Phoenix v1 components. Every component follows the `cn()` utility pattern for Tailwind class merging.

**Deliverables:**
- Carry over 19 Radix UI primitive wrappers from v1 (Button, Input, Card, Table, Dialog, Select, Tabs, Badge, Avatar, DropdownMenu, Tooltip, Switch, Checkbox, RadioGroup, Separator, ScrollArea, Sheet, Popover, Command)
- New composite components:
  - DataTable (sortable, filterable, paginated with TanStack Table)
  - FlexCard (agent/strategy summary card with status indicator)
  - MetricCard (single metric with sparkline)
  - StatusBadge (green/yellow/red with pulse animation)
  - SidePanel (slide-out detail panel for agent/trade/position)
  - FormBuilder (dynamic forms from JSON schema for connector/agent config)
  - ConfirmDialog (destructive action confirmation)
  - Toast (success/error/info notifications via Sonner)
  - EmptyState (illustration + CTA for empty tabs)
  - Skeleton (loading placeholder for all card types)
- Storybook setup (optional, if time permits)
- `cn()` utility at `lib/utils.ts` (carried over from v1)
- Lucide icon imports for all tab icons and common actions

**Acceptance Criteria:**
- [ ] Each component renders correctly in isolation
- [ ] DataTable handles 1000+ rows with virtual scrolling
- [ ] All components support dark and light themes
- [ ] Components are responsive (stack on mobile, grid on desktop)
- [ ] TypeScript props are fully typed with JSDoc comments

---

### M1.6: Database Schema & Migrations

**Duration:** Week 3–4 (5 days)
**Dependencies:** M1.2
**Owner:** Backend Engineer

**Description:**
Implement the full database schema using SQLAlchemy 2 async models and Alembic migrations. All 17+ entities from the PRD and Architecture Plan.

**Deliverables:**
- SQLAlchemy 2 async models in `shared/db/models/`:
  - `User`, `TradingAccount`, `OpenClawInstance`
  - `Agent`, `AgentBacktest`, `Skill`, `AgentSkill`
  - `TradeIntent`, `Position`
  - `Connector`, `ConnectorAgent`, `ApiKeyEntry`
  - `Task`, `Automation`
  - `DevIncident`, `AgentMessage`
  - `AgentLog`, `AuditLog`
- Alembic migration scripts:
  - Initial schema creation
  - TimescaleDB extension + hypertables (`market_bars`, `performance_metrics`, `agent_heartbeats`)
  - Indexes on foreign keys and commonly queried columns
- Seed scripts for default admin user, roles, permissions
- Database connection pool configuration (async via `asyncpg`)

**Acceptance Criteria:**
- [ ] `alembic upgrade head` creates all tables without errors
- [ ] `alembic downgrade -1` reverts the latest migration cleanly
- [ ] All foreign key relationships enforced (cascade deletes where appropriate)
- [ ] TimescaleDB hypertables created with correct chunk intervals (1 day for heartbeats, 1 week for metrics)
- [ ] Default admin user seeded with correct role and all permissions

---

### M1.7: OpenClaw Bridge Service

**Duration:** Week 4–5 (7 days)
**Dependencies:** M1.2 (WireGuard)
**Owner:** Backend Engineer

**Description:**
Build the Bridge Service that runs as a sidecar on each OpenClaw VPS. It provides a REST API for the Control Plane to manage agents, collect heartbeats, and proxy commands to OpenClaw.

**Deliverables:**
- FastAPI application in `openclaw/bridge/`:
  - `GET /health` — Instance health (CPU, memory, uptime, agent count)
  - `GET /heartbeat` — All agent statuses, current task, positions, PnL
  - `GET /agents` — List agents with status
  - `POST /agents` — Create agent (write AGENTS.md, TOOLS.md, SOUL.md, HEARTBEAT.md, register in openclaw.json)
  - `GET /agents/:id` — Agent detail
  - `PUT /agents/:id` — Update agent config files
  - `DELETE /agents/:id` — Remove agent and clean workspace
  - `POST /agents/:id/pause` — Pause agent
  - `POST /agents/:id/resume` — Resume agent
  - `GET /agents/:id/logs` — Stream recent agent session logs
  - `POST /skills/sync` — Trigger skill pull from MinIO
  - `POST /agents/:id/message` — Send message to agent (for agent-to-agent communication)
- Authentication via `X-Bridge-Token` shared secret
- Prometheus metrics endpoint (`/metrics`)
- Dockerfile and systemd service file
- Unit tests for all endpoints

**Acceptance Criteria:**
- [ ] Bridge Service starts and responds to health check on WireGuard IP
- [ ] `POST /agents` creates agent workspace with all config files
- [ ] `GET /heartbeat` returns accurate agent statuses within 1 second
- [ ] `POST /skills/sync` pulls latest skills from MinIO
- [ ] Bridge rejects requests without valid `X-Bridge-Token` (401)
- [ ] Prometheus `/metrics` exposes agent count, heartbeat latency, error count

---

### M1.8: First OpenClaw Instance Setup

**Duration:** Week 5 (5 days)
**Dependencies:** M1.2, M1.7
**Owner:** DevOps + AI Engineer

**Description:**
Set up the first OpenClaw instance (Instance D: Live Trading Operations) with 2 starter agents: a basic trade agent and a monitoring agent. Verify end-to-end communication with the Control Plane.

**Deliverables:**
- OpenClaw installed on Node 4 (Hetzner CX42)
- `openclaw.json` configured with:
  - `live-trader-test`: a simple trade agent that evaluates signals
  - `trade-monitor-test`: monitors positions from the trader agent
- Agent config files authored:
  - `AGENTS.md`: role description, goals, instructions
  - `TOOLS.md`: allowed tools (API calls, calculations)
  - `SOUL.md`: communication style (structured JSON output)
  - `HEARTBEAT.md`: periodic check (every 60 seconds, report status)
- Bridge Service deployed and registered with Control Plane
- End-to-end test: send a test signal via API → agent processes it → trade intent appears in the trade-intents stream
- Startup script and systemd service for auto-restart

**Acceptance Criteria:**
- [ ] OpenClaw process running and accepting API connections
- [ ] Two agents visible via `GET /agents` on Bridge Service
- [ ] Heartbeat data flows to Control Plane every 60 seconds
- [ ] Test signal processed by agent and trade intent published to Redis stream
- [ ] Agent resumes after VPS reboot (systemd restart)

---

### M1.9: Connector Framework Core

**Duration:** Week 5–6 (7 days)
**Dependencies:** M1.6, M1.7
**Owner:** Backend Engineer

**Description:**
Build the connector manager service and implement the first two connectors: Discord (data source) and Alpaca (broker). The connector manager normalizes messages from data sources and routes them to assigned agents.

**Deliverables:**
- Connector Manager service in `services/connector-manager/`:
  - Plugin architecture: each connector is a separate module implementing `BaseConnector`
  - `BaseConnector` interface: `connect()`, `disconnect()`, `health()`, `on_message(callback)`
  - Message normalization: all source messages mapped to a common schema (`ConnectorMessage`)
  - Routing: messages routed to assigned agents via Event Bus
- Discord connector:
  - Discord.py bot that joins configured servers/channels
  - Extracts trade signals, sentiment, alerts from channel messages
  - Handles reconnection and rate limiting
- Alpaca broker connector:
  - REST API client for paper/live trading
  - WebSocket stream for order status updates
  - Account balance and position sync
  - Order placement, cancellation, modification
- Connector CRUD API in Backend:
  - `POST /api/v2/connectors` — Create connector (encrypted credentials)
  - `GET /api/v2/connectors` — List connectors with status
  - `PUT /api/v2/connectors/:id` — Update config
  - `DELETE /api/v2/connectors/:id` — Remove connector
  - `POST /api/v2/connectors/:id/test` — Test connection

**Acceptance Criteria:**
- [ ] Discord connector joins a test server and receives messages
- [ ] Messages normalized and published to `stream:connector-events`
- [ ] Alpaca connector places a paper trade order successfully
- [ ] Alpaca connector streams order fills in real-time
- [ ] Connector credentials stored encrypted, not visible in API responses
- [ ] `POST /api/v2/connectors/:id/test` returns success/failure with details

---

### M1.10: Trades Tab & Positions Tab

**Duration:** Week 6–7 (7 days)
**Dependencies:** M1.4, M1.5, M1.6, M1.9
**Owner:** Frontend Engineer

**Description:**
Build the first two production dashboard tabs: Trades (all trade intents from agents) and Positions (live positions across all trading accounts).

**Deliverables:**
- **Trades Tab** (`/trades`):
  - DataTable showing all trade intents: timestamp, agent, ticker, action (buy/sell), instrument type (stock/option), quantity, status (pending/filled/rejected/cancelled), fill price, PnL
  - Filters: agent, status, ticker, date range, instrument type
  - Click on trade → SidePanel with full details (reasoning, source message, execution log)
  - Real-time updates via WebSocket (new trades appear without refresh)
  - Export to CSV
- **Positions Tab** (`/positions`):
  - DataTable showing all open positions: account, agent, ticker, side, quantity, entry price, current price, unrealized PnL, stop loss, take profit
  - Position cards (FlexCard layout) for at-a-glance overview
  - Closed positions subtab with realized PnL
  - Filter by account, agent, ticker
  - Real-time price updates via WebSocket (1-second interval for active positions)
  - Total portfolio summary: total value, daily PnL, number of positions
- Backend API endpoints:
  - `GET /api/v2/trades` — paginated, filterable
  - `GET /api/v2/trades/:id` — single trade detail
  - `GET /api/v2/positions` — open positions with real-time prices
  - `GET /api/v2/positions/closed` — closed positions
  - `GET /api/v2/positions/summary` — portfolio totals
- WebSocket Gateway:
  - Channel: `trades` — new trade intents, status changes
  - Channel: `positions` — price updates, position open/close

**Acceptance Criteria:**
- [ ] Trades table loads and displays all trade intents with pagination
- [ ] New trade appears in table within 2 seconds of creation (WebSocket push)
- [ ] Positions show real-time unrealized PnL
- [ ] Clicking a trade shows full detail in side panel
- [ ] Filters work correctly across all columns
- [ ] Mobile view: table scrolls horizontally, cards stack vertically

---

### M1.11: Basic Agent CRUD

**Duration:** Week 7 (5 days)
**Dependencies:** M1.6, M1.7, M1.8
**Owner:** Full Stack Engineer

**Description:**
Implement the ability to create, list, view, edit, pause/resume, and delete agents via the dashboard. This is the basic version — the full lifecycle (backtest → review → paper → live) comes in Phase 2.

**Deliverables:**
- **Agents Tab** (`/agents`) — basic version:
  - Agent list: FlexCards showing agent name, type, status, instance, data source, PnL
  - "New Agent" button → multi-step creation wizard:
    1. Basic info: name, type (trading/strategy/monitoring), description
    2. Instance selection: dropdown of OpenClaw instances with capacity info
    3. Data source: select connector(s) and channels
    4. Skills: select from available skills
    5. Risk config: stop loss %, max position size, daily loss limit
    6. Review and create
  - Agent detail page: status, config, recent activity, trade history
  - Actions: pause, resume, delete (with confirmation)
- Backend API endpoints:
  - `POST /api/v2/agents` — Create agent (validates config, calls Bridge to create on instance)
  - `GET /api/v2/agents` — List all agents
  - `GET /api/v2/agents/:id` — Agent detail with metrics
  - `PUT /api/v2/agents/:id` — Update config
  - `DELETE /api/v2/agents/:id` — Remove agent
  - `POST /api/v2/agents/:id/pause` — Pause agent
  - `POST /api/v2/agents/:id/resume` — Resume agent
- Orchestrator integration: agent creation enqueued as a job, status tracked through creation pipeline

**Acceptance Criteria:**
- [ ] Create agent via wizard → agent appears on OpenClaw instance
- [ ] Agent list shows real-time status from heartbeat data
- [ ] Pause/resume toggles agent state on the OpenClaw instance
- [ ] Delete removes agent workspace on instance and database record
- [ ] Validation prevents creating agents on full instances

---

### M1.12: Execution Service & Risk Checks

**Duration:** Week 7–8 (7 days)
**Dependencies:** M1.6, M1.9 (Alpaca connector)
**Owner:** Backend Engineer

**Description:**
Build the Execution Service that processes trade intents from the queue, applies 3-layer risk checks, and places orders via broker APIs.

**Deliverables:**
- Execution Service in `services/execution/`:
  - Consumes `stream:trade-intents` (Redis Streams consumer group)
  - 3-layer risk validation:
    1. **Agent-level**: Does this trade match the agent's allowed instruments, position size, and daily limit?
    2. **Execution-level**: Is the order valid (quantity, price, market hours)? Duplicate check (idempotency by intent ID).
    3. **Global-level**: Is the account under its daily loss limit? Is the circuit breaker closed?
  - Order placement via broker connector (Alpaca first)
  - Order status tracking (submitted → partial → filled / rejected)
  - Publishes result to `stream:position-updates`
- Global Position Monitor in `services/global-monitor/`:
  - Tracks total exposure per account
  - Enforces daily loss limits per account
  - Circuit breaker: opens when daily loss > 3%, blocks new orders
  - Emergency kill switch: close all positions when portfolio loss > 10%
- API endpoints:
  - `POST /api/v2/trade-intents` — Submit trade intent (for testing/manual)
  - `GET /api/v2/execution/status` — Service health and queue depth
  - `POST /api/v2/execution/kill-switch` — Emergency: close all positions

**Acceptance Criteria:**
- [ ] Trade intent processed within 500ms of arrival in queue
- [ ] Risk checks reject oversized orders (returns rejection reason)
- [ ] Alpaca paper trade placed and fill confirmed
- [ ] Duplicate trade intent (same ID) is not executed twice
- [ ] Circuit breaker opens when daily loss exceeds 3%
- [ ] Kill switch closes all open positions within 30 seconds

---

### M1.13: Mobile Responsive Foundation

**Duration:** Week 8 (5 days)
**Dependencies:** M1.4, M1.5, M1.10
**Owner:** Frontend Engineer

**Description:**
Ensure the entire dashboard works on mobile devices. Implement responsive patterns, bottom navigation, and touch-friendly interactions.

**Deliverables:**
- Tailwind responsive breakpoints applied throughout:
  - `sm` (640px): tablets, adjusted padding/margins
  - `md` (768px): sidebar → bottom nav transition
  - `lg` (1024px): full desktop layout
- Bottom navigation bar for mobile (< 768px):
  - 5 primary tabs (Trades, Positions, Agents, Market, Settings)
  - "More" button for remaining tabs
  - Active tab indicator
- Responsive adjustments:
  - DataTable: horizontal scroll with sticky first column on mobile
  - FlexCards: single column on mobile, 2-column on tablet, 3+ on desktop
  - SidePanel: full-screen overlay on mobile, slide-in on desktop
  - Wizard: full-screen steps on mobile, inline on desktop
  - Charts: simplified view on mobile (fewer data points, larger touch targets)
- Touch-friendly: minimum 44px tap targets, swipe gestures for cards

**Acceptance Criteria:**
- [ ] Dashboard usable on iPhone SE (375px width)
- [ ] Bottom nav appears on mobile, sidebar on desktop
- [ ] All tables scroll horizontally without breaking layout
- [ ] Agent creation wizard works fully on mobile
- [ ] No horizontal page overflow on any screen size

---

## Phase 2 — Intelligence (Weeks 9–18)

Phase 2 builds the intelligence layer: full agent lifecycle with backtesting gates, 115 skills, strategy agents, performance analytics, inter-agent communication, and all remaining connectors. By the end of Phase 2, the system can autonomously backtest trading strategies, promote successful agents to paper trading, and provide comprehensive performance dashboards. See [Architecture Plan §5 Event Bus & Message Flow](ArchitecturePlan.md#5-event-bus--message-flow) and [§6 OpenClaw Instance Architecture](ArchitecturePlan.md#6-openclaw-instance-architecture).

---

### M2.1: Core Skill Catalog (30 Skills)

**Duration:** Week 9–10 (7 days)
**Dependencies:** M1.7, M1.8
**Owner:** AI Engineer

**Description:**
Author the first 30 skills across the Data, Analysis, Execution, and Risk categories. Each skill follows the SKILL.md template from the PRD. Upload to MinIO and sync to all instances.

**Deliverables:**
- 30 skills in `openclaw/skills/phoenix/`:
  - **Data (8 skills)**: `market-data-fetch`, `news-aggregator`, `options-chain-lookup`, `social-sentiment-reader`, `economic-calendar-check`, `sector-heatmap`, `unusual-options-flow`, `insider-transaction-scan`
  - **Analysis (8 skills)**: `technical-indicator-suite`, `support-resistance-finder`, `pattern-recognition`, `volume-profile-analysis`, `correlation-analysis`, `sentiment-scoring`, `implied-volatility-calc`, `earnings-impact-predictor`
  - **Execution (7 skills)**: `order-builder-stock`, `order-builder-option`, `position-sizer`, `entry-timing-optimizer`, `slippage-estimator`, `multi-leg-option-builder`, `order-type-selector`
  - **Risk (7 skills)**: `stop-loss-calculator`, `portfolio-exposure-check`, `correlation-risk-checker`, `max-drawdown-estimator`, `daily-loss-tracker`, `position-limit-enforcer`, `sector-concentration-check`
- Each skill contains:
  - `SKILL.md`: purpose, trigger conditions, inputs, outputs, step-by-step instructions
  - Referenced tool calls (API endpoints, calculations)
  - Example invocations
- Skills uploaded to MinIO `phoenix-skills` bucket
- Cron-based sync verified on all instances

**Acceptance Criteria:**
- [ ] All 30 skills pass validation (correct SKILL.md structure)
- [ ] Skills synced to all OpenClaw instances within 5 minutes of upload
- [ ] Agent can invoke `market-data-fetch` and return OHLCV data
- [ ] Agent can invoke `order-builder-stock` and produce valid trade intent JSON
- [ ] Agent can chain `sentiment-scoring` → `order-builder-option` in a single evaluation

---

### M2.2: Skill Sync Service

**Duration:** Week 10 (5 days)
**Dependencies:** M1.7, M2.1
**Owner:** Backend Engineer

**Description:**
Build a dedicated service that manages skill distribution from the central repository to all OpenClaw instances. Provides a dashboard interface for skill management.

**Deliverables:**
- Skill Sync Service in `services/skill-sync/`:
  - Watches MinIO `phoenix-skills` bucket for changes
  - Pushes skill updates to all registered OpenClaw instances via Bridge API
  - Version tracking per skill per instance
  - Rollback capability (revert a skill to previous version)
- Backend API endpoints:
  - `GET /api/v2/skills` — List all skills with version and sync status
  - `GET /api/v2/skills/:id` — Skill detail (content, agents using it, sync status per instance)
  - `POST /api/v2/skills` — Upload new skill (writes to MinIO, triggers sync)
  - `PUT /api/v2/skills/:id` — Update skill content
  - `DELETE /api/v2/skills/:id` — Deprecate skill
  - `POST /api/v2/skills/sync` — Force sync to all instances
  - `GET /api/v2/skills/sync/status` — Sync status per instance
- Dashboard skill management (part of Skills tab):
  - Skill list with filter by category
  - Skill editor (Monaco editor for SKILL.md)
  - Sync status indicators per instance
  - Bulk assign skills to agents

**Acceptance Criteria:**
- [ ] New skill uploaded via dashboard appears on all instances within 5 minutes
- [ ] Skill update propagates to all instances, version incremented
- [ ] Dashboard shows sync status per instance (green/yellow/red)
- [ ] Skill rollback restores previous version on all instances
- [ ] Agent can use newly synced skill immediately after sync completes

---

### M2.3: Backtesting Engine

**Duration:** Week 10–12 (10 days)
**Dependencies:** M1.6, M1.7, M1.9 (market data connector)
**Owner:** Backend Engineer + AI Engineer

**Description:**
Build the sandboxed backtesting engine that evaluates agent performance on historical data before allowing promotion to paper/live trading.

**Deliverables:**
- Backtest Runner in `services/backtest-runner/`:
  - Docker-in-Docker execution (sandboxed, no host access)
  - Three backtest types:
    1. **Signal-driven**: replay historical signals from a connector, let agent evaluate each
    2. **Heartbeat-driven**: simulate strategy agent heartbeat on historical data
    3. **Walk-forward**: rolling window train/test with strategy optimization
  - Market data provider: fetch OHLCV bars from Alpaca/Yahoo Finance, cache in TimescaleDB
  - Metric calculation engine: total PnL, win rate, Sharpe ratio, Sortino ratio, max drawdown, profit factor, Calmar ratio, average trade duration, profit per trade
  - Result storage: JSON summary + equity curve + trade log → MinIO
- Backtest API:
  - `POST /api/v2/backtests` — Start backtest (agent_id, type, date range, config)
  - `GET /api/v2/backtests/:id` — Status and progress (% complete, current date)
  - `GET /api/v2/backtests/:id/results` — Full results and metrics
  - `GET /api/v2/backtests/:id/trades` — Paginated trade log
  - `GET /api/v2/backtests/:id/equity-curve` — Equity curve data
- Dashboard integration (Agent detail page → Backtesting sub-tab):
  - Start backtest button with configuration form
  - Progress bar with live log stream
  - Results display: metric cards, equity curve chart (Recharts), trade log table
  - Compare backtests side-by-side

**Acceptance Criteria:**
- [ ] Signal-driven backtest replays 2 years of data for a test agent
- [ ] Backtest runs in isolated Docker container with no host access
- [ ] Metrics calculated correctly (verified against manual calculation)
- [ ] Progress updates stream to dashboard in real-time
- [ ] Results persisted and accessible after backtest completes
- [ ] Two backtests can run concurrently without interference

---

### M2.4: Agent Lifecycle State Machine

**Duration:** Week 12–13 (7 days)
**Dependencies:** M1.11, M2.3
**Owner:** Backend Engineer

**Description:**
Implement the full agent lifecycle: create → backtest → review → paper trade → live trade. Each transition requires explicit user approval. The system prevents promotion of agents with poor backtest results.

**Deliverables:**
- Agent state machine in Orchestrator:
  ```
  CREATED → BACKTESTING → BACKTEST_COMPLETE → REVIEW_PENDING
    → PAPER_APPROVED → PAPER_TRADING → LIVE_APPROVED → LIVE_TRADING
    → PAUSED (from any active state)
    → ERROR (from any state)
    → RETIRED (terminal state)
  ```
- Automatic backtest trigger on agent creation
- Review gate:
  - Dashboard shows backtest results with a "Promote to Paper" or "Reject" button
  - Rejection requires a reason (stored in audit log)
  - Promotion minimum criteria (configurable): win rate > 50%, Sharpe > 1.0, max drawdown < 20%
- Paper trading:
  - Agent connected to paper trading account
  - Real-time tracking but no real money
  - Performance compared against backtest predictions
- Live trading promotion:
  - Requires admin approval if paper results diverge > 20% from backtest
  - Admin review with side-by-side backtest vs. paper metrics
- Status transitions logged in `audit_log` table
- Dashboard indicators: clear status badges, progress bar through lifecycle

**Acceptance Criteria:**
- [ ] New agent automatically starts backtesting
- [ ] Backtest completion triggers notification and review prompt
- [ ] Cannot promote agent that fails minimum criteria
- [ ] Paper trading agent tracks real-time PnL without placing real orders
- [ ] Live promotion requires explicit admin approval
- [ ] All state transitions logged in audit log

---

### M2.5: Trading Agent Architecture

**Duration:** Week 13–14 (7 days)
**Dependencies:** M2.1, M2.4, M1.9
**Owner:** AI Engineer

**Description:**
Implement the full trading agent pattern: signal evaluation, multi-skill analysis, paired monitoring agent, and trade execution flow.

**Deliverables:**
- Trading Agent template configs:
  - `AGENTS.md`: evaluates incoming signals from assigned data sources, uses analysis skills, builds trade intents, respects risk parameters
  - `TOOLS.md`: API calls (market data, options chain, execution), file I/O (session memory), agent-to-agent messaging
  - `SOUL.md`: structured output format (JSON trade intents), risk-aware personality
- Signal evaluation flow:
  - Connector delivers message → Agent receives via Bridge → Agent invokes analysis skills → Agent decides trade/no-trade → If trade: builds trade intent JSON → POSTs to execution API
- Monitoring Agent template:
  - Paired with every trading agent
  - Monitors all open positions from its trading agent
  - Applies stop-loss rules (20% default), trailing stops, take-profit targets (30% default)
  - Can close positions independently
  - Communicates with trading agent about position status
- Auto-pairing: when a trading agent is created, a monitoring agent is automatically created on the same instance
- Monitoring agent receives position updates from Event Bus

**Acceptance Criteria:**
- [ ] Trading agent receives Discord signal, evaluates it, and produces trade intent
- [ ] Trade intent includes reasoning and skill invocations used
- [ ] Monitoring agent detects position at -20% and issues close order
- [ ] Monitoring agent detects position at +30% and trails stop to lock in profit
- [ ] Agent-to-agent communication works between trader and monitor (same instance)
- [ ] Full cycle: signal → evaluation → trade → monitor → close runs end-to-end

---

### M2.6: Strategy Agent Architecture

**Duration:** Week 14–15 (7 days)
**Dependencies:** M2.1, M2.4
**Owner:** AI Engineer

**Description:**
Build the strategy agent pattern: heartbeat-driven agents that run strategies independently on a schedule. Includes 15 initial strategy templates.

**Deliverables:**
- Strategy Agent template configs:
  - `AGENTS.md`: runs assigned strategy on heartbeat, fetches data, evaluates conditions, generates trade intents
  - `HEARTBEAT.md`: configurable interval (1m, 5m, 15m, 1h, 1d), defines periodic analysis tasks
  - `TOOLS.md`: market data APIs, technical indicator calculations, order builders
- 15 strategy templates (authored as OpenClaw configs):
  1. Moving Average Crossover (SMA/EMA)
  2. RSI Divergence
  3. MACD Signal
  4. Bollinger Band Breakout
  5. VWAP Reversion
  6. Opening Range Breakout
  7. Momentum Scalp
  8. Mean Reversion
  9. Pairs Trading
  10. Iron Condor Income
  11. Wheel Strategy (CSP + CC)
  12. Earnings Straddle
  13. Sector Rotation
  14. Dividend Capture
  15. Gap Fill
- Each template includes:
  - Strategy description and rules
  - Required market data
  - Entry and exit conditions
  - Risk parameters
  - Backtesting configuration
- Dashboard: Strategies Tab (`/strategies`):
  - Strategy template library (15 pre-built)
  - "New Strategy Agent" wizard: select template → configure parameters → select instance → starts backtesting
  - Strategy agent list with performance metrics

**Acceptance Criteria:**
- [ ] Strategy agent runs on configured heartbeat interval
- [ ] Moving Average Crossover strategy generates trades on crossover signals
- [ ] Strategy agent backtests successfully with walk-forward method
- [ ] All 15 strategy templates load in the dashboard template library
- [ ] Strategy agent lifecycle follows the same state machine as trading agents

---

### M2.7: Performance Tab

**Duration:** Week 15–16 (7 days)
**Dependencies:** M1.10, M2.4, M2.5
**Owner:** Frontend Engineer

**Description:**
Build the comprehensive performance analytics tab with 6 metric sections, interactive charts, and time-range filters.

**Deliverables:**
- **Performance Tab** (`/performance`):
  - **Section 1: Portfolio Overview**
    - Total portfolio value, daily PnL ($ and %), total return
    - Equity curve chart (line chart, multiple time ranges: 1D, 1W, 1M, 3M, 1Y, ALL)
    - Comparison against S&P 500 benchmark
  - **Section 2: Account Performance**
    - Table of all trading accounts: account name, broker, total PnL, win rate, Sharpe, drawdown
    - Click account → drilldown to trades and positions
  - **Section 3: Agent Rankings**
    - Top 10 best performing agents (sortable by PnL, win rate, Sharpe)
    - Top 10 worst performing agents
    - Agent performance heatmap (grid, color-coded by daily PnL)
  - **Section 4: Data Source Analysis**
    - PnL breakdown by connector/data source
    - Signal quality metrics per source (% of signals that led to profitable trades)
  - **Section 5: Instrument Analytics**
    - PnL by ticker (top winners and losers)
    - PnL by instrument type (stocks vs options)
    - PnL by sector
  - **Section 6: Risk Metrics**
    - Portfolio Sharpe, Sortino, Calmar ratios
    - Maximum drawdown timeline
    - Daily VaR (Value at Risk) estimate
    - Correlation matrix of agent returns
  - Time range selector (1D, 1W, 1M, 3M, 6M, 1Y, YTD, ALL)
  - Export all data to CSV/PDF
- Backend API:
  - `GET /api/v2/performance/portfolio` — aggregate metrics
  - `GET /api/v2/performance/accounts` — per-account metrics
  - `GET /api/v2/performance/agents` — per-agent rankings
  - `GET /api/v2/performance/sources` — per-source analysis
  - `GET /api/v2/performance/instruments` — per-ticker/sector breakdown
  - `GET /api/v2/performance/risk` — risk metrics
  - All endpoints accept `start_date`, `end_date`, `timeframe` params
- TimescaleDB continuous aggregates for efficient rollups

**Acceptance Criteria:**
- [ ] Portfolio equity curve renders with 10,000+ data points without lag
- [ ] Agent rankings update in real-time as trades close
- [ ] All 6 sections populated with data from backtest and live trades
- [ ] Time range filter changes all sections simultaneously
- [ ] Mobile view stacks sections vertically with swipeable cards
- [ ] CSV export includes all visible data

---

### M2.8: Remaining Connectors

**Duration:** Week 16–17 (7 days)
**Dependencies:** M1.9
**Owner:** Backend Engineer

**Description:**
Implement all remaining data source connectors and broker integrations.

**Deliverables:**
- **Data Source Connectors:**
  - Reddit connector (PRAW library): subreddit monitoring, post/comment extraction
  - Twitter/X connector: keyword/cashtag monitoring, sentiment extraction
  - Unusual Whales API connector: unusual options flow, dark pool data
  - News APIs connector: Finnhub, NewsAPI, Benzinga — headline extraction
  - Custom Webhook connector: generic HTTP endpoint that accepts POST signals
- **Broker Connectors:**
  - Interactive Brokers (IBKR): TWS API / Client Portal API for order placement
  - Robinhood (via unofficial API): order placement, portfolio sync
  - Tradier: REST API for options trading
- Connectors Tab (`/connectors`):
  - Connector library showing all available types
  - "Add Connector" → type-specific configuration form
  - Connector status dashboard: connected/disconnected, last message, message count
  - Test connection button for each connector
  - Assign connectors to agents

**Acceptance Criteria:**
- [ ] Each connector successfully connects and receives data
- [ ] Reddit connector extracts posts from r/wallstreetbets
- [ ] Unusual Whales connector streams unusual options activity
- [ ] IBKR connector places paper trade order
- [ ] Custom Webhook receives and processes a test POST
- [ ] All connectors show real-time status in dashboard

---

### M2.9: Skills & Agent Config Tab

**Duration:** Week 17 (5 days)
**Dependencies:** M2.1, M2.2, M1.11
**Owner:** Full Stack Engineer

**Description:**
Build the Skills & Agent Configuration management tab for the dashboard.

**Deliverables:**
- **Skills Tab** (`/skills`):
  - **Section 1: Skill Catalog**
    - List of all skills with search, filter by category (Data, Analysis, Strategy, Execution, Risk, Utility, Advanced)
    - Skill detail view: description, inputs/outputs, agent usage count
    - Skill editor: Monaco editor for SKILL.md content
    - Skill builder wizard: step-by-step form to create a new skill
    - Sync status per instance
    - "Force Sync" button
  - **Section 2: Agent Configurations**
    - List of all agent configs
    - Edit agent: name, description, skills, risk parameters, data sources
    - Bulk operations: assign skill to multiple agents, update risk config
    - Config diff view (compare current vs. previous version)
    - Config export/import (JSON)

**Acceptance Criteria:**
- [ ] All skills listed with correct categories and usage counts
- [ ] Skill editor saves changes and triggers sync
- [ ] New skill created via wizard appears in catalog
- [ ] Agent config changes propagate to OpenClaw instance via Bridge API
- [ ] Bulk skill assignment works for 10+ agents simultaneously

---

### M2.10: Agent-to-Agent Communication

**Duration:** Week 17–18 (7 days)
**Dependencies:** M1.7, M2.5
**Owner:** Backend Engineer + AI Engineer

**Description:**
Implement the inter-agent communication system: same-instance (native OpenClaw), cross-instance (via Agent Communication Router and Event Bus), and communication patterns (request-response, broadcast, pub-sub, chain, consensus).

**Deliverables:**
- Agent Communication Router in `services/agent-comm/`:
  - Routes messages between agents on different OpenClaw instances
  - Message schema: `{ from, to, intent, data, response_to, timestamp }`
  - Patterns:
    - **Request-Response**: agent A asks agent B a question, waits for answer
    - **Broadcast**: agent sends message to all agents of a certain type
    - **Pub-Sub**: agents subscribe to topics (e.g., "sector:tech", "signal:options")
    - **Chain**: message passes through a sequence of agents (analyst → strategist → executor)
    - **Consensus**: multiple agents vote on a trade decision (majority required)
  - Messages stored in `agent_messages` table
  - Delivery via Bridge API (`POST /agents/:id/message`)
- Same-instance communication: leverages OpenClaw native `agentToAgent` function
- Cross-instance communication: Agent Communication Router forwards via WireGuard
- Consensus protocol:
  - Configurable quorum (e.g., 3 out of 5 agents must agree)
  - Timeout handling (10 second default, configurable)
  - Result aggregation and tie-breaking
- Agent Network tab (basic version): list of recent agent-to-agent messages

**Acceptance Criteria:**
- [ ] Agent A on Instance D can send a message to Agent B on Instance B
- [ ] Request-Response pattern: Agent A asks question, Agent B responds within 10 seconds
- [ ] Broadcast: message reaches all trading agents across all instances
- [ ] Consensus: 3 agents vote on a trade, majority decision executed
- [ ] Messages logged in `agent_messages` table with full trail
- [ ] Cross-instance latency < 500ms via WireGuard

---

### M2.11: Additional Broker Connectors

**Duration:** Week 18 (5 days, parallel with M2.10)
**Dependencies:** M1.9
**Owner:** Backend Engineer

**Description:**
Complete all broker connector integrations (IBKR, Robinhood, Tradier) to support live trading across multiple brokers.

**Deliverables:**
- Implement remaining broker connectors (from M2.8 if not completed):
  - IBKR: full order lifecycle, position sync, account balance
  - Robinhood: order placement, position tracking
  - Tradier: options-focused trading, complex order types
- Broker abstraction layer:
  - Unified interface for all brokers: `place_order()`, `cancel_order()`, `get_positions()`, `get_account()`
  - Broker-specific configuration stored in `trading_accounts` table
  - Automatic reconnection and error handling
- Multi-account support:
  - Agent can be assigned to any trading account
  - Different agents can trade on different accounts simultaneously
  - Account-level risk limits (separate from agent-level)

**Acceptance Criteria:**
- [ ] All three brokers place paper/simulated orders successfully
- [ ] Position sync reflects actual broker positions
- [ ] Account balance and buying power accurate to within 1 second
- [ ] Broker reconnects automatically after connection drop
- [ ] Multiple agents trading on different accounts simultaneously

---

### M2.12: Market Command Center Migration

**Duration:** Week 18 (5 days, parallel with M2.10)
**Dependencies:** M1.4, M1.5
**Owner:** Frontend Engineer

**Description:**
Migrate the Market Command Center from Phoenix v1 to the new dashboard. Enhance it with react-grid-layout for customizable widget arrangement.

**Deliverables:**
- **Market Command Center** (`/market`):
  - `react-grid-layout` integration for drag-and-drop widget arrangement
  - Migrated widgets from v1 `MarketCommandCenter.tsx`:
    - TradingView charts (reuse `TradingViewEmbed`)
    - Ticker search (reuse `TickerSearch`)
    - Market indices overview
    - Sector heatmap
    - Top movers (gainers/losers)
    - Options flow feed
    - News feed
    - Economic calendar
    - Watchlists
    - Quick trade panel
  - Layout persistence (save/load layouts per user in localStorage)
  - Default layouts: "Trader" (charts + trade), "Analyst" (news + data), "Overview" (everything)
  - 50+ widget target (including duplicates with different tickers)
- Mobile: single-column layout with collapsible widget cards

**Acceptance Criteria:**
- [ ] All v1 widgets functional in new dashboard
- [ ] Widgets draggable and resizable on desktop
- [ ] Layout saved and restored on page reload
- [ ] Three default layouts selectable
- [ ] TradingView charts load and render correctly
- [ ] Mobile view: widgets stack vertically with collapse toggle

---

### M2.13: Position Monitoring System

**Duration:** Week 16 (5 days, parallel with M2.7)
**Dependencies:** M2.5
**Owner:** AI Engineer + Backend Engineer

**Description:**
Build the monitoring agent system that tracks all open positions and enforces risk management rules.

**Deliverables:**
- Monitoring Agent capabilities:
  - Real-time position tracking via broker WebSocket feeds
  - Stop-loss enforcement: close position at -20% (configurable per agent)
  - Trailing stop: once position is +15%, trail stop at entry + 5%
  - Take-profit: partial close at +30%, full close at +50%
  - End-of-day close: option to close all positions before market close
  - Signal-based close: if data source publishes exit signal, close position
- Position tracking service:
  - Aggregates position data from all broker accounts
  - Calculates real-time unrealized PnL
  - Detects positions hitting risk thresholds
  - Notifies monitoring agents of threshold breaches
- Dashboard integration:
  - Position cards show stop-loss and take-profit levels visually
  - Color-coded PnL indicators (green/yellow/red)
  - Close position button (manual override)

**Acceptance Criteria:**
- [ ] Monitoring agent closes position when -20% stop-loss hit
- [ ] Trailing stop activates and adjusts as position profits increase
- [ ] Take-profit partially closes position at +30%
- [ ] EOD close closes all marked positions 5 minutes before market close
- [ ] Dashboard shows real-time stop/target levels on position cards

---

### M2.14: Global Position Monitor & Circuit Breaker

**Duration:** Week 16–17 (5 days, parallel with M2.8)
**Dependencies:** M1.12, M2.13
**Owner:** Backend Engineer

**Description:**
Enhance the Global Position Monitor with full circuit breaker logic, account-level risk limits, and the emergency kill switch.

**Deliverables:**
- Enhanced Global Monitor:
  - Tracks total exposure per account, per sector, per instrument type
  - Concentration limits: no single ticker > 10% of portfolio, no single sector > 30%
  - Correlation risk: flag when highly correlated positions exceed threshold
  - Margin utilization tracking (for margin accounts)
- Circuit breaker states:
  - `CLOSED` → normal operation
  - `HALF_OPEN` → daily loss 2-3%, new trades require double confirmation
  - `OPEN` → daily loss > 3%, all new trades blocked, notification sent
  - Auto-reset: midnight Eastern or manual override by admin
- Emergency kill switch:
  - Triggered when portfolio loss > 10% or manually by admin
  - Cancels all pending orders across all brokers
  - Closes all open positions at market price
  - Disables all agents (pause state)
  - Sends alerts to all configured channels (Discord, Telegram, email)
- Dashboard: circuit breaker status visible in sidebar (green/yellow/red indicator)

**Acceptance Criteria:**
- [ ] Circuit breaker transitions correctly through CLOSED → HALF_OPEN → OPEN
- [ ] New trades blocked when circuit breaker is OPEN
- [ ] Kill switch closes all positions within 60 seconds
- [ ] Circuit breaker auto-resets at midnight
- [ ] Admin can manually reset circuit breaker from dashboard
- [ ] Concentration limits enforced (rejects trade exceeding 10% allocation)

---

### M2.15: Remaining 85 Skills

**Duration:** Week 15–18 (spread across multiple weeks)
**Dependencies:** M2.1, M2.2
**Owner:** AI Engineer

**Out of scope / future:** Spread over multiple sprints; prioritize by category. Optional to defer some skills to post–Phase 2.

**Description:**
Author the remaining 85 skills to complete the full 115-skill catalog across all 7 categories.

**Deliverables:**
- **Strategy Skills (20)**: momentum-scalp, mean-reversion, pairs-trade, iron-condor, wheel-strategy, earnings-straddle, sector-rotation, dividend-capture, gap-fill, opening-range-breakout, vwap-reversion, fibonacci-retracement, breakout-confirmation, reversal-detector, trend-follower, range-trader, news-catalyst-trade, gamma-squeeze-detect, short-squeeze-detect, calendar-spread
- **Utility Skills (15)**: portfolio-report-gen, trade-journal-entry, daily-summary-builder, alert-composer, backtest-report-gen, performance-attribution, tax-lot-tracker, dividend-tracker, position-reconciler, account-balance-sync, market-hours-check, holiday-calendar, symbol-resolver, data-quality-checker, log-structured-output
- **Advanced / AI Skills (15)**: ml-feature-engineer, regression-predictor, classification-model, clustering-anomaly, time-series-forecast, nlp-headline-score, options-pricing-model, monte-carlo-sim, bayesian-updater, reinforcement-reward-calc, agent-performance-evaluator, code-generator-python, model-trainer-pytorch, model-inference-runner, agent-self-optimizer
- **Additional Data Skills (7)**: crypto-data-fetch, forex-data-fetch, bond-yield-fetch, etf-holdings-fetch, institutional-holdings, short-interest-fetch, dark-pool-volume
- **Additional Analysis Skills (7)**: greeks-calculator, iv-rank-percentile, pcr-analysis, market-breadth, advance-decline, relative-strength, cross-asset-correlation
- **Additional Execution Skills (6)**: bracket-order-builder, oco-order-builder, stop-limit-builder, scale-in-strategy, scale-out-strategy, iceberg-order-sim
- **Additional Risk Skills (5)**: beta-hedging, delta-neutral-rebalance, portfolio-var-calculator, stress-test-runner, liquidity-check
- Each skill: SKILL.md template with full documentation

**Acceptance Criteria:**
- [ ] All 115 skills authored and uploaded to MinIO
- [ ] Skills organized by category in correct directory structure
- [ ] At least 5 skills per category tested end-to-end with an agent
- [ ] Advanced/AI skills (ML, code generation) produce valid outputs
- [ ] Full skill catalog visible and searchable in dashboard Skills tab

---

## Phase 3 — Advanced (Weeks 19–26)

Phase 3 adds the advanced capabilities: the Dev Agent with reinforcement learning, Task Board for ad-hoc agent assignments, automations/scheduling, bidirectional communication channels, admin panel with RBAC, agent network visualization, predictive model training, PWA, and production hardening. By the end of Phase 3, the system is a fully autonomous, self-monitoring trading firm of agents ready for production. See [Architecture Plan §9 Monitoring & Observability](ArchitecturePlan.md#9-monitoring--observability).

---

### M3.1: Dev Agent

**Duration:** Week 19–20 (7 days)
**Dependencies:** M2.5, M2.10
**Owner:** AI Engineer

**Description:**
Build the Dev Agent — an AI agent that continuously monitors all other agents for failures, errors, and performance degradation, then diagnoses and fixes issues automatically.

**Deliverables:**
- Dev Agent deployed on OpenClaw Instance C (Risk & Promotion):
  - `AGENTS.md`: "You are the Dev Agent. Your role is to monitor all agents in the Phoenix network for errors, failures, and performance issues. When you detect a problem, diagnose the root cause and apply a fix."
  - `HEARTBEAT.md`: every 60 seconds, check for:
    - Agent error rates (from Redis `stream:agent-events`)
    - Failed trade intents (from `stream:trade-intents`)
    - Missing heartbeats (agents that haven't reported in > 3 minutes)
    - Performance degradation (win rate dropped > 10% in 24h)
    - Service health issues (from Prometheus metrics)
  - Tools: access to all agent logs, config files, metrics, ability to restart agents, modify configs
- Issue detection and classification:
  - `CONNECTION_ERROR` — connector lost connection
  - `SKILL_FAILURE` — skill invocation failed
  - `PERFORMANCE_DEGRADATION` — metrics declining
  - `AGENT_CRASH` — agent process died
  - `CONFIG_ERROR` — malformed agent configuration
  - `RESOURCE_EXHAUSTION` — memory/CPU limits
- Auto-repair actions:
  - Restart agent
  - Reconnect connector
  - Revert config to last known good
  - Disable problematic skill
  - Scale up instance resources
  - Escalate to admin (if cannot fix)
- All incidents logged in `dev_incidents` table

**Acceptance Criteria:**
- [ ] Dev Agent detects simulated agent crash within 2 minutes
- [ ] Dev Agent restarts crashed agent and verifies recovery
- [ ] Dev Agent detects connector disconnection and triggers reconnect
- [ ] Dev Agent detects performance degradation and notifies admin
- [ ] All incidents logged with diagnosis, action taken, and outcome
- [ ] Dev Agent does NOT modify live trading agents without admin approval for destructive changes

---

### M3.2: Reinforcement Learning Loop

**Duration:** Week 20–21 (7 days)
**Dependencies:** M3.1
**Owner:** AI Engineer + ML Engineer

**Description:**
Add reinforcement learning to the Dev Agent so it improves its diagnosis and repair strategies over time based on reward signals.

**Deliverables:**
- RL State representation:
  - Agent error type and frequency
  - System resource utilization
  - Time since last similar incident
  - Agent trading performance metrics
  - Previous repair action outcomes
- RL Action space:
  - Restart agent
  - Modify agent config
  - Disable/enable skill
  - Adjust risk parameters
  - Reconnect connector
  - Escalate to admin
  - Do nothing (observe)
- RL Reward signal:
  - +10: incident resolved, agent back to normal within 5 minutes
  - +5: incident resolved with minor performance impact
  - -5: fix failed, had to escalate
  - -10: fix caused new issue
  - -20: fix caused trade loss
  - +3: proactive fix before user noticed
- Training infrastructure:
  - Q-learning table (initial implementation, simple and interpretable)
  - PPO policy (future upgrade, when Q-table stabilizes)
  - Episode: incident detection → action selection → outcome measurement
  - Model saved to MinIO `phoenix-models` bucket
  - Periodic retraining (daily, using last 30 days of episodes)
- RL metrics tracked:
  - Average reward per episode
  - Action distribution over time
  - Fix success rate (should increase over time)
  - Time-to-resolution trend

**Acceptance Criteria:**
- [ ] Q-learning table initialized and trains on simulated incidents
- [ ] RL agent selects repair actions based on learned policy
- [ ] Average reward increases over 100 simulated episodes
- [ ] RL model persisted and loaded on Dev Agent restart
- [ ] Metrics visible in Dev Dashboard (M3.3)
- [ ] RL agent avoids destructive actions it has been penalized for

---

### M3.3: Dev Dashboard

**Duration:** Week 21 (5 days)
**Dependencies:** M3.1, M3.2
**Owner:** Frontend Engineer

**Description:**
Build the admin-only Dev Dashboard that shows the Dev Agent's activity, incidents, RL metrics, and code changes.

**Deliverables:**
- **Dev Dashboard** (sub-route under Admin, visible to admin role only):
  - **Incident Feed**: real-time list of all incidents with severity, type, status, resolution
  - **Incident Detail**: diagnosis, action taken, code diff (if any), outcome, RL reward
  - **RL Metrics Panel**:
    - Average reward trend (line chart)
    - Action distribution (pie chart)
    - Fix success rate over time (line chart)
    - Q-table heatmap (state-action values)
  - **Agent Health Grid**: matrix of all agents with color-coded health status
  - **Code Changes Log**: list of all config/code modifications made by Dev Agent
  - **Manual Controls**: pause Dev Agent, trigger manual diagnosis, override RL action
- Backend API:
  - `GET /api/v2/dev/incidents` — paginated incidents
  - `GET /api/v2/dev/incidents/:id` — incident detail
  - `GET /api/v2/dev/rl/metrics` — RL training metrics
  - `GET /api/v2/dev/agents/health` — all agent health statuses
  - `POST /api/v2/dev/agent/pause` — pause Dev Agent
  - `POST /api/v2/dev/diagnose/:agent_id` — trigger manual diagnosis

**Acceptance Criteria:**
- [ ] Incident feed shows real-time updates
- [ ] RL metrics charts render correctly with training data
- [ ] Code changes display diffs in readable format
- [ ] Only admin users can access Dev Dashboard (403 for others)
- [ ] Manual diagnosis trigger works and shows results
- [ ] Agent health grid reflects actual statuses from heartbeat data

---

### M3.4: Task Board & Agent Roles

**Duration:** Week 21–22 (7 days)
**Dependencies:** M1.11, M2.10
**Owner:** Full Stack Engineer

**Description:**
Build the Task Board where users can create agents with specific roles (Day Trader, Technical Analyst, Risk Analyzer, Market Researcher, etc.) and assign tasks to them. Agents can also create their own tasks.

**Deliverables:**
- **Task Board** (`/tasks`):
  - Kanban board using `@dnd-kit`:
    - Columns: Backlog, In Progress, Review, Done
    - Cards: task title, assigned agent (avatar + name), priority, labels, due date
    - Drag-and-drop between columns
  - Task creation form:
    - Title, description
    - Assign to agent (dropdown) or "Auto-assign" (system picks best agent for the role)
    - Priority (low, medium, high, critical)
    - Labels (e.g., "research", "trade", "analysis", "report")
    - Due date
  - Agent role templates:
    - Day Trader: fast execution, scalp-oriented
    - Technical Analysis Expert: chart patterns, indicators
    - Risk Analyzer: portfolio risk assessment, hedging suggestions
    - Market Research Analyst: news analysis, sector reports
    - Options Specialist: options strategies, Greeks analysis
    - Macro Economist: economic data, Fed decisions
    - Sentiment Analyst: social media, news sentiment
    - Report Generator: creates periodic reports and summaries
  - "New Agent" button → role-based creation wizard
  - Agent-created tasks: agents can create tasks for themselves or other agents via API
  - Task detail view: description, agent response/output, timeline, comments
- Backend API:
  - `GET/POST /api/v2/tasks` — CRUD for tasks
  - `PUT /api/v2/tasks/:id` — Update task (status, assignment)
  - `GET /api/v2/task-agents` — List task board agents (not trading/strategy agents)
  - `POST /api/v2/task-agents` — Create task board agent with role
  - `POST /api/v2/tasks/:id/output` — Agent submits task output

**Acceptance Criteria:**
- [ ] Kanban board renders with drag-and-drop working
- [ ] Task created and assigned to an agent of a specific role
- [ ] Agent picks up task and begins working on it
- [ ] Agent-created tasks appear on the board
- [ ] Task detail shows agent's output and reasoning
- [ ] All 8 role templates available in agent creation wizard
- [ ] Mobile: kanban scrolls horizontally, cards full-width

---

### M3.5: Automations

**Duration:** Week 22–23 (7 days)
**Dependencies:** M3.4, M2.6
**Owner:** Backend Engineer + Full Stack Engineer

**Description:**
Build the automation system that allows users to schedule recurring tasks using cron expressions or natural language. Automations launch agents on configured instances to perform tasks on a schedule.

**Deliverables:**
- Automation Scheduler in `services/automation/`:
  - Cron expression parser and scheduler
  - Natural language to cron conversion (via LLM):
    - "Every morning at 8am" → `0 8 * * *`
    - "Every Friday before market close" → `0 15 * * 5`
    - "Every hour during market hours" → `0 * 9-16 * * 1-5`
  - Automation execution: creates a task on the Task Board and assigns to agent
  - Delivery channel integration: send output to configured channel
- **Automations Panel** (sub-tab under Task Board):
  - "New Automation" button:
    - Natural language description (e.g., "Give me morning briefing of stock market")
    - Cron expression (generated from NL or manual input)
    - Agent role (which type of agent handles this)
    - OpenClaw instance (where to run)
    - Delivery channel: Dashboard, Telegram, Discord, WhatsApp, Email
  - Automation list: name, schedule (human-readable), last run, next run, status
  - Automation run history: past outputs and delivery confirmations
  - Enable/disable toggle per automation
- Pre-built automation templates:
  - "Morning Market Briefing" — daily at 8am, Market Research Analyst
  - "EOD Portfolio Summary" — daily at 4pm, Report Generator
  - "Weekly Performance Report" — Friday at 5pm, Report Generator
  - "Earnings Preview" — day before earnings, Technical Analysis Expert
  - "Options Expiration Alert" — weekly, Options Specialist
  - "Risk Assessment" — every 4 hours during market, Risk Analyzer

**Acceptance Criteria:**
- [ ] NL input "Every morning at 8am" generates correct cron and schedules
- [ ] Automation triggers at scheduled time and creates task for agent
- [ ] Agent completes task and output delivered to Telegram
- [ ] Pre-built templates installable with one click
- [ ] Automation history shows all past runs with output
- [ ] Disable toggle prevents automation from firing

---

### M3.6: Bidirectional Communication Channels

**Duration:** Week 23 (5 days)
**Dependencies:** M1.9, M3.5
**Owner:** Backend Engineer

**Description:**
Implement bidirectional communication between the user and agents via Telegram, Discord, and WhatsApp. Users can send commands and receive reports through their preferred channel.

**Deliverables:**
- **Telegram Bot**:
  - Bot created via BotFather, configured in Connectors tab
  - Commands: `/status`, `/portfolio`, `/agents`, `/trade <ticker>`, `/report`, `/ask <question>`
  - Receives agent outputs (automations, alerts, reports)
  - Inline keyboards for quick actions (approve trade, view details)
- **Discord Bot** (enhanced from connector):
  - Slash commands: `/phoenix status`, `/phoenix trade`, `/phoenix report`
  - Dedicated channel for agent outputs
  - Thread creation for ongoing discussions (e.g., earnings analysis)
- **WhatsApp** (via existing `shared/whatsapp/sender.py`):
  - Outbound: send agent reports, alerts, trade confirmations
  - Inbound: parse incoming messages for commands
  - Media: send chart images, PDF reports
- Unified message router:
  - Routes agent output to correct channel based on automation/alert config
  - Formats output for each channel (Markdown for Discord, HTML for Telegram, plain for WhatsApp)
  - Rate limiting to prevent spam

**Acceptance Criteria:**
- [ ] Telegram: `/status` returns current portfolio summary
- [ ] Discord: `/phoenix trade AAPL` triggers an agent analysis
- [ ] WhatsApp: receives morning briefing automation output
- [ ] User can ask a question via Telegram, agent responds within 60 seconds
- [ ] All channels configured via Connectors tab
- [ ] Messages formatted correctly for each platform

---

### M3.7: Admin & User Management Tab

**Duration:** Week 23–24 (5 days)
**Dependencies:** M1.3
**Owner:** Full Stack Engineer

**Description:**
Build the Admin & User Management tab with full RBAC, API Key Vault, and audit log.

**Deliverables:**
- **Admin Tab** (`/admin`):
  - **User Management**:
    - User list: name, email, role, last login, status
    - Create/edit/deactivate users
    - Role assignment: admin, manager, trader, viewer, custom
    - Custom role builder: select from 20 permissions
    - Tab visibility control: configure which tabs each role can see
    - MFA enforcement toggle per user
  - **API Key Vault**:
    - Centralized storage for all integration API keys
    - Supported key types: broker credentials, LLM API keys, connector API keys, webhook secrets
    - Add/edit/delete keys (encrypted with Fernet)
    - Masked display (last 4 characters only)
    - Key testing: verify key validity with provider
    - Key rotation reminders (configurable expiry)
    - Usage tracking (which services use each key)
  - **Audit Log**:
    - Searchable log of all administrative actions
    - Columns: timestamp, user, action, target, details
    - Filter by user, action type, date range
    - Export to CSV
- Backend API:
  - `GET/POST/PUT/DELETE /api/v2/admin/users` — User CRUD
  - `GET/POST/PUT/DELETE /api/v2/admin/roles` — Role CRUD
  - `GET/POST/PUT/DELETE /api/v2/admin/api-keys` — API Key Vault CRUD
  - `POST /api/v2/admin/api-keys/:id/test` — Test key validity
  - `GET /api/v2/admin/audit-log` — Paginated audit log

**Acceptance Criteria:**
- [ ] Admin can create user with "trader" role that can only see Trades, Positions, Agents tabs
- [ ] Custom role with specific permissions restricts API access
- [ ] API keys stored encrypted, displayed masked
- [ ] Key test button verifies Alpaca API key is valid
- [ ] Audit log captures all admin actions with details
- [ ] Non-admin users receive 403 on admin endpoints

---

### M3.8: Agent Network Visualization

**Duration:** Week 24 (5 days)
**Dependencies:** M2.10, M3.1
**Owner:** Frontend Engineer

**Description:**
Build the interactive agent network graph using `@xyflow/react` that shows all OpenClaw instances, agents, their connections, and real-time status.

**Deliverables:**
- **Agent Network** (`/network`):
  - Graph visualization using `@xyflow/react`:
    - Nodes:
      - OpenClaw instances (large container nodes)
      - Agents (smaller nodes inside instance containers)
      - Shared services (Database, Redis, Execution Service)
    - Edges:
      - Agent-to-agent communication (recent messages)
      - Agent-to-service connections (data flow)
      - Instance-to-Dashboard heartbeat lines
    - Node colors: green (healthy), yellow (warning), red (error), gray (offline)
    - Pulse animation on nodes with active communication
  - Interaction:
    - Click node → detail panel (agent status, metrics, recent activity)
    - Click edge → message log between connected agents
    - Zoom and pan
    - Filter: show/hide by instance, agent type, status
    - Auto-layout and manual arrangement
  - Real-time updates:
    - Node status refreshes every 60 seconds (heartbeat)
    - New agent-to-agent messages animate as edge pulses
    - New incidents highlighted with red glow
  - Minimap for navigation
- Backend API:
  - `GET /api/v2/network/graph` — Full graph data (nodes + edges)
  - `GET /api/v2/network/messages` — Recent inter-agent messages

**Acceptance Criteria:**
- [ ] Graph renders all instances and agents with correct hierarchy
- [ ] Node colors reflect real-time status
- [ ] Clicking agent node shows detail panel with status and metrics
- [ ] Edge pulse animation visible when agents communicate
- [ ] Graph handles 50+ nodes without performance degradation
- [ ] Mobile: simplified list view with status indicators (graph too complex for small screens)

---

### M3.9: Agent Code Generation & Predictive Models

**Duration:** Week 24–25 (7 days)
**Dependencies:** M2.1 (Advanced/AI skills), M3.1
**Owner:** AI Engineer + ML Engineer

**Description:**
Enable OpenClaw agents to write Python code, train ML models, and run predictions. Sandboxed execution ensures safety.

**Deliverables:**
- Code execution sandbox:
  - Docker container with Python 3.12 + data science libraries (pandas, numpy, scikit-learn, PyTorch, statsmodels)
  - No network access (data passed in/out via volumes)
  - Time limit: 5 minutes per execution
  - Memory limit: 2 GB
  - Output collected: stdout, stderr, generated files (models, charts)
- Agent code generation flow:
  - Agent writes Python code using `code-generator-python` skill
  - Code submitted to Backtest Runner (Docker-in-Docker execution)
  - Output captured and returned to agent
  - Generated models stored in MinIO `phoenix-models` bucket
- Predictive model lifecycle:
  - Agent trains model on historical data
  - Model serialized (pickle/ONNX) and versioned in MinIO
  - Agent can load and run inference on trained model
  - Model performance tracked (accuracy, prediction vs. actual)
- Supported model types:
  - Regression (price prediction)
  - Classification (up/down prediction)
  - Time series forecasting (LSTM, Prophet)
  - Anomaly detection (for unusual market behavior)
- Dashboard: model registry view in Agent detail page
  - List trained models per agent
  - Model metrics and performance charts
  - Download model artifacts

**Acceptance Criteria:**
- [ ] Agent generates valid Python code for a regression model
- [ ] Code executes in sandbox without host access
- [ ] Trained model saved to MinIO and loadable by agent
- [ ] Agent runs inference on loaded model and gets prediction
- [ ] Code execution respects 5-minute timeout and 2GB memory limit
- [ ] Failed code execution returns error message to agent without crashing

---

### M3.10: Progressive Web App (PWA)

**Duration:** Week 25 (5 days)
**Dependencies:** M1.4, M1.13
**Owner:** Frontend Engineer

**Description:**
Convert the dashboard into a PWA with offline capability, push notifications, and app-like experience on mobile.

**Deliverables:**
- `manifest.json`:
  - App name: "Phoenix Trading"
  - Theme color, background color
  - Icons (192x192, 512x512)
  - `display: standalone`
  - `start_url: /`
- Service Worker:
  - Cache-first strategy for static assets (JS, CSS, images)
  - Network-first for API calls (with fallback to cached data)
  - Background sync for offline actions (queued until online)
- Push notifications:
  - Trade filled notifications
  - Agent alerts (error, circuit breaker)
  - Automation results
  - Dev Agent incidents (admin only)
  - User can configure which notifications to receive
- Offline capability:
  - Dashboard shell loads offline (shows cached data)
  - "Offline" indicator bar
  - Queued actions submitted when reconnected

**Acceptance Criteria:**
- [ ] "Install App" prompt appears on mobile Chrome/Safari
- [ ] Installed app opens in standalone mode (no browser chrome)
- [ ] Push notification received when trade fills
- [ ] Dashboard loads (with cached data) when offline
- [ ] Queued actions (e.g., pause agent) execute when back online
- [ ] Service worker properly caches and updates assets

---

### M3.11: Walk-Forward Backtesting & Strategy Optimizer

**Duration:** Week 25 (5 days, parallel with M3.10)
**Dependencies:** M2.3, M2.6
**Owner:** Backend Engineer + AI Engineer

**Description:**
Enhance the backtesting engine with walk-forward analysis and automated strategy parameter optimization.

**Deliverables:**
- Walk-forward backtesting:
  - Rolling train/test windows (e.g., 6 months train, 1 month test, roll forward by 1 month)
  - Out-of-sample validation to detect overfitting
  - Parameter stability analysis (do optimal params stay consistent across windows?)
- Strategy optimizer:
  - Grid search over parameter ranges
  - Bayesian optimization for faster convergence (Optuna)
  - Optimization targets: Sharpe ratio, profit factor, max drawdown (configurable)
  - Overfitting detection: compare in-sample vs. out-of-sample metrics
- Results visualization:
  - Walk-forward equity curves (in-sample vs. out-of-sample)
  - Parameter sensitivity heatmaps
  - Optimization convergence chart
- Dashboard: "Optimize" button on Strategy Agent detail page
  - Configure parameter ranges
  - Start optimization run
  - View results and select best parameters

**Acceptance Criteria:**
- [ ] Walk-forward backtest produces separate in-sample and out-of-sample metrics
- [ ] Grid search tests all parameter combinations and finds best
- [ ] Bayesian optimization converges faster than grid search for 5+ parameters
- [ ] Overfitting warning when in-sample Sharpe > 2x out-of-sample Sharpe
- [ ] Optimized parameters can be applied to strategy agent config

---

### M3.12: Observability Stack

**Duration:** Week 25–26 (5 days)
**Dependencies:** M1.2
**Owner:** DevOps

**Description:**
Deploy and configure the full observability stack: Prometheus, Grafana, and Loki. Create dashboards and alerting rules.

**Deliverables:**
- Prometheus deployment:
  - Scrape configs for all services (15+ targets)
  - Node Exporter on each VPS
  - PostgreSQL Exporter
  - Redis Exporter
  - Custom metric endpoints on all Python services
- Grafana deployment:
  - 7 dashboards (from Architecture Plan Section 9.2):
    1. System Overview
    2. Trading Operations
    3. Agent Performance
    4. Infrastructure
    5. Circuit Breaker
    6. OpenClaw Instances
    7. Dev Agent
  - Each dashboard with appropriate panels, time ranges, and variables
- Loki deployment:
  - Log collection from all Docker containers
  - Promtail sidecar or Docker logging driver
  - Log queries from Grafana
- Alerting:
  - 8 alert rules (from Architecture Plan Section 9.4)
  - Alert routing to Discord webhook and email
  - Alert silencing and acknowledgment

**Acceptance Criteria:**
- [ ] All services appear as UP in Prometheus targets
- [ ] Grafana dashboards load with live data
- [ ] Loki shows logs from all services searchable by service name
- [ ] Alert fires when a test service is stopped
- [ ] Alert notification appears in Discord
- [ ] Dashboard accessible at `grafana.phoenix.yourdomain.com`

---

### M3.13: Load Testing, Security Hardening & Documentation

**Duration:** Week 26 (5 days)
**Dependencies:** All prior milestones
**Owner:** Full Team

**Description:**
Comprehensive testing, security review, and documentation before production go-live.

**Deliverables:**
- **Load Testing:**
  - Simulate 50 concurrent agents sending signals
  - Simulate 100 WebSocket connections
  - Measure: API latency (p50, p95, p99), trade execution latency, heartbeat processing time
  - Identify and fix bottlenecks
  - Target: API p95 < 200ms, trade execution < 500ms, heartbeat < 1000ms
- **Security Hardening:**
  - Dependency vulnerability scan (Snyk/Dependabot)
  - API rate limiting on all public endpoints
  - SQL injection testing (automated)
  - XSS testing on dashboard (CSP headers)
  - Credential rotation: generate new encryption keys, rotate all API keys
  - Penetration test on VPN and public endpoints
  - Review RBAC: verify permission enforcement on every endpoint
- **Documentation:**
  - User Guide: dashboard walkthrough, agent creation, strategy setup
  - API Documentation: OpenAPI spec auto-generated from FastAPI
  - Operations Guide: deployment, monitoring, incident response
  - Skill Development Guide: how to create and test new skills
  - Architecture Decision Records (ADRs) for major decisions

**Acceptance Criteria:**
- [ ] Load test passes all targets (p95 latency, execution time)
- [ ] Zero high-severity vulnerabilities in dependency scan
- [ ] RBAC enforced on all 50+ API endpoints (automated test)
- [ ] Documentation covers all major features and operations
- [ ] OpenAPI spec published and accessible

---

### M3.14: Production Deployment & Go-Live

**Duration:** Week 26 (3 days, after M3.13)
**Dependencies:** M3.13, all prior milestones
**Owner:** DevOps + Lead Engineer

**Description:**
Final production deployment, data migration (if applicable), and go-live checklist.

**Deliverables:**
- **Pre-Go-Live Checklist:**
  - [ ] All Coolify services deployed and healthy
  - [ ] All OpenClaw instances running with agents configured
  - [ ] WireGuard VPN stable across all nodes
  - [ ] SSL certificates valid and auto-renewing
  - [ ] Database backup configured (daily, retained 30 days)
  - [ ] Redis persistence (RDB + AOF) enabled
  - [ ] MinIO bucket versioning enabled
  - [ ] Monitoring dashboards loaded with real data
  - [ ] Alert routing verified (Discord, email)
  - [ ] Circuit breaker tested (trigger and reset)
  - [ ] Kill switch tested (with paper trading accounts)
  - [ ] Broker connections verified (Alpaca paper, then live)
  - [ ] First automation running (morning briefing)
  - [ ] Mobile PWA installable
  - [ ] Documentation published
- **Data Migration** (from Phoenix v1, if applicable):
  - Migrate user accounts
  - Migrate trading account configurations
  - Migrate historical trade data
  - Verify data integrity
- **Go-Live Sequence:**
  1. Deploy to production Coolify server
  2. Configure DNS cutover
  3. Verify all services healthy
  4. Create admin account
  5. Configure first OpenClaw instance (paper trading)
  6. Set up first connector (Discord test channel)
  7. Create first trading agent (paper mode)
  8. Verify end-to-end: signal → agent → backtest → paper trade
  9. Enable monitoring and alerting
  10. Announce go-live

**Acceptance Criteria:**
- [ ] All checklist items verified
- [ ] End-to-end test passes: signal → evaluation → trade → monitoring → close
- [ ] Dashboard accessible from desktop and mobile
- [ ] No errors in Loki logs for first 24 hours
- [ ] Heartbeat stable across all instances for 24 hours
- [ ] Ready to accept live broker credentials and begin live trading

---

## Dependency Graph

```
Week 1: M1.1 (Repo) ────┐
                          │
Week 1-2: M1.2 (Infra) ──┤
                          │
Week 2-3: M1.3 (Auth) ◄──┤
                          │
Week 2-3: M1.4 (Shell) ◄─┘────┐
                               │
Week 3: M1.5 (UI Lib) ◄───────┤
                               │
Week 3-4: M1.6 (DB) ◄─────────┤
                               │
Week 4-5: M1.7 (Bridge) ◄─────┼──────────┐
                               │          │
Week 5: M1.8 (First OC) ◄─────┤          │
                               │          │
Week 5-6: M1.9 (Connectors) ◄─┤          │
                               │          │
Week 6-7: M1.10 (Trades UI) ◄─┤          │
                               │          │
Week 7: M1.11 (Agent CRUD) ◄──┤          │
                               │          │
Week 7-8: M1.12 (Execution) ◄─┤          │
                               │          │
Week 8: M1.13 (Mobile) ◄──────┘          │
                                          │
Week 9-10: M2.1 (30 Skills) ◄────────────┤
                                          │
Week 10: M2.2 (Skill Sync) ◄─────────────┤
                                          │
Week 10-12: M2.3 (Backtest) ◄────────────┤
                                          │
Week 12-13: M2.4 (Lifecycle) ◄───────────┤
                                          │
Week 13-14: M2.5 (Trade Agent) ◄─────────┤
                                          │
Week 14-15: M2.6 (Strategy) ◄────────────┤
                                          │
Week 15-16: M2.7 (Performance UI) ◄──────┤
                                          │
Week 16-17: M2.8 (Connectors) ◄──────────┤
                                          │
Week 17: M2.9 (Skills UI) ◄──────────────┤
                                          │
Week 17-18: M2.10 (Agent Comms) ◄────────┤
                                          │
Week 18: M2.11 (Brokers) ◄───────────────┤
                                          │
Week 18: M2.12 (Market Center) ◄─────────┤
                                          │
Week 16: M2.13 (Monitoring) ◄────────────┤
                                          │
Week 16-17: M2.14 (Circuit Breaker) ◄────┤
                                          │
Week 15-18: M2.15 (85 Skills) ◄──────────┤
                                          │
Week 19-20: M3.1 (Dev Agent) ◄───────────┤
                                          │
Week 20-21: M3.2 (RL Loop) ◄─────────────┤
                                          │
Week 21: M3.3 (Dev Dashboard) ◄──────────┤
                                          │
Week 21-22: M3.4 (Task Board) ◄──────────┤
                                          │
Week 22-23: M3.5 (Automations) ◄─────────┤
                                          │
Week 23: M3.6 (Comms Channels) ◄─────────┤
                                          │
Week 23-24: M3.7 (Admin Tab) ◄───────────┤
                                          │
Week 24: M3.8 (Network Viz) ◄────────────┤
                                          │
Week 24-25: M3.9 (Code Gen) ◄────────────┤
                                          │
Week 25: M3.10 (PWA) ◄───────────────────┤
                                          │
Week 25: M3.11 (Walk-Forward) ◄──────────┤
                                          │
Week 25-26: M3.12 (Observability) ◄──────┤
                                          │
Week 26: M3.13 (Testing/Security) ◄──────┤
                                          │
Week 26: M3.14 (Go-Live) ◄───────────────┘
```

---

## Concurrent Build Matrix

After Phase 1 is complete (or at least through M1.11), Phase 2 and Phase 3 can be built in parallel using three workstreams. Dependencies between workstreams (e.g. M2.7 depends on M2.4, M2.5) remain as in the Dependency Graph; within each stream, order by the graph.

| Workstream | Focus | Milestones |
|---|---|---|
| **A — Backend / services** | Skill sync, backtesting, connectors, agent comms, monitoring, automations, observability | M2.2, M2.3, M2.8, M2.10, M2.13, M2.14, M3.5, M3.6, M3.12 |
| **B — Frontend / dashboard** | Performance tab, Skills tab, Market Center, Dev Dashboard, Task Board, Admin tab, Network viz, PWA | M2.7, M2.9, M2.12, M3.3, M3.4, M3.7, M3.8, M3.10 |
| **C — OpenClaw / skills / agents** | 30 + 85 skills, lifecycle, trading/strategy agents, brokers, Dev Agent, RL, code gen, walk-forward | M2.1, M2.4, M2.5, M2.6, M2.11, M2.15, M3.1, M3.2, M3.9, M3.11 |

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| OpenClaw API changes in new version | High | Medium | Pin OpenClaw version, abstract all OC calls behind Bridge Service |
| Broker API rate limits during high-volume trading | High | Medium | Queue-based execution with backoff, multiple broker accounts |
| LLM latency spikes (Claude/GPT-4) | Medium | High | Cache common evaluations, use faster models for simple decisions, timeout + fallback |
| WireGuard VPN instability | High | Low | Automatic reconnection, heartbeat monitoring, fallback to direct HTTPS with mTLS |
| PostgreSQL disk full | High | Low | TimescaleDB retention policies, alerts at 85%, archive to MinIO |
| Agent makes catastrophic trade | Critical | Low | 3-layer risk checks, circuit breaker, kill switch, max position size, daily loss limit |
| Single point of failure (Coolify server) | High | Low | Daily backups, documented recovery procedure, can rebuild from Docker images + DB backup in < 1 hour |
| Skill sync conflict (simultaneous edits) | Low | Medium | Version-based sync with conflict detection, last-write-wins with audit trail |
| RL Dev Agent makes wrong fix | Medium | Medium | Destructive actions require admin approval, rollback capability, RL penalty for bad fixes |
| Scope creep in Phase 2-3 | Medium | High | Strict milestone scope, cut features to "future" rather than delaying phase |
