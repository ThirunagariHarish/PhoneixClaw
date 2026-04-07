# Copilot Instructions — Phoenix Trade Bot

Phoenix Trade Bot is an enterprise multi-tenant AI trading platform. Monorepo with a React/Vite dashboard, FastAPI backend, PostgreSQL, Redis, Kafka, and OpenClaw AI agents for automated trading. Python 3.11+, Node.js 18+.

## Commands

### Quick Start
```bash
make setup          # First-time: install deps + create .env
make dev-run        # Infra + API (:8011) + Dashboard (:3000)
```

### Development
```bash
make dev-install              # Install Python prod + dev deps (editable)
make dashboard-install        # Install dashboard npm deps
make infra-up / make infra-down
make run-api                  # FastAPI on :8011
make run-dashboard            # Vite dev server on :3000
```

### Testing
```bash
make test                     # All unit tests (tests/unit/ + apps/api/tests/)
make test-api                 # API tests only
make test-cov                 # Coverage report

# Single file / single test
python3 -m pytest tests/unit/test_foo.py -v --tb=short
python3 -m pytest tests/unit/test_foo.py::test_name -v
```

### Code Quality
```bash
make lint           # Ruff (E, F, I, N, W), line-length 120
make lint-fix       # Auto-fix
make typecheck      # MyPy strict on shared/
```

### Database
```bash
make db-init                  # Bootstrap tables (no Alembic needed locally)
make db-migrate msg="desc"    # Generate Alembic migration
make db-upgrade / make db-downgrade
```

## Architecture

### Three-Plane Design

**Control Plane** — Single server: API (FastAPI), Dashboard (React/Vite), PostgreSQL, Redis, BullMQ orchestrator for agent lifecycle.

**Execution Plane** — Remote VPS nodes each running an OpenClaw instance (Claude AI agents + workspaces) with a Bridge Service sidecar (`openclaw/bridge/`) that exposes a REST API for the Control Plane.

**Shared Services** — MinIO (artifact storage), TimescaleDB (market data), Execution Service (broker adapters: Alpaca/IBKR), Prometheus + Grafana.

### Key Directories
```
apps/api/src/          FastAPI backend — routes/, repositories/, middleware/, services/
apps/dashboard/src/    React 18 — pages/, components/, hooks/, context/, lib/
shared/                Importable libraries: db models, events, broker, LLM, backtest, NLP
services/              Microservices: orchestrator, execution, backtest-runner, llm-gateway, ws-gateway, etc.
openclaw/bridge/       Bridge Service for remote OpenClaw agent management
agents/backtesting/    9-step ML pipeline (transform → train 8 models → evaluate → patterns → live agent)
tests/                 unit/, integration/, e2e/ (Playwright), benchmark/
```

### Agent Lifecycle (State Machine)
```
CREATED → approved → executing → idle → disabled
```
Agents are created via wizard, backtested, then promoted to Docker-managed trading workers. State lives entirely in PostgreSQL.

### ML Training Pipeline
Runs 8 models **sequentially** (memory-constrained): XGBoost → LightGBM → CatBoost → LSTM → Transformer → TFT → TCN → Hybrid ensemble + Meta-learner. ~200 features across price action, technicals, volume, sentiment, and options data.

## Key Conventions

### Repository Pattern (mandatory for all DB access)
All database operations go through repository classes — no raw SQL or direct ORM queries in routes/services.

```python
# apps/api/src/repositories/base.py — BaseRepository provides:
# get_by_id, list_all, create, update, delete_by_id, count

class AgentRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session, Agent)
```

### FastAPI Route Pattern
Every route module defines its own `router` and inline Pydantic schemas. Use `DbSession` from `deps.py` for database access:

```python
from apps.api.src.deps import DbSession

router = APIRouter(prefix="/api/v2/agents", tags=["agents"])

@router.get("/{agent_id}")
async def get_agent(agent_id: UUID, db: DbSession) -> AgentResponse:
    repo = AgentRepository(db)
    ...
```

### Auth — `request.state`
`JWTAuthMiddleware` decodes the Bearer token and injects into every request:
- `request.state.user_id` — UUID string (None if unauthenticated)
- `request.state.is_admin` — bool
- `request.state.role` — e.g. `"trader"`, `"viewer"`
- `request.state.permissions` — list of permission strings

### SQLAlchemy Models
Use `Mapped` type annotations. Prefer `JSONB` for flexible config/metadata fields. All models extend `shared.db.models.base.Base`.

```python
class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
```

### Two Config Systems
- **`shared/config/base_config.py`** — Python dataclasses for shared services (Kafka, Redis, DB, Auth). Read from env vars directly.
- **`apps/api/src/config.py`** — pydantic-settings `Settings` class for the API. Use `from apps.api.src.config import settings`.

### Event Bus
Use Redis Streams via `shared/events/bus.py`:
```python
bus = EventBus(redis_url)
await bus.publish("stream:name", {"key": "value"})
async for msg_id, data in bus.subscribe("stream:name", group="grp", consumer="c1"):
    ...
```

### Dashboard API Client
All frontend HTTP calls go through `apps/dashboard/src/lib/api.ts` (axios, auto-injects `phoenix-v2-token` from localStorage). Use TanStack Query for server state.

### Testing Notes
- `asyncio_mode = "auto"` — all async tests run without `@pytest.mark.asyncio`
- `tests/conftest.py` sets `DATABASE_URL=sqlite+aiosqlite:///test.db` and stub env vars — no real DB needed for unit tests
- New unit tests go in `tests/unit/`; API endpoint tests go in `apps/api/tests/`

### PYTHONPATH
Always set to the repo root (`.`) when running services or tests outside of `make` targets:
```bash
PYTHONPATH=. python3 -m services.execution.main
```

### Schema Self-Heal
`apps/api/src/main.py` runs `_ensure_prod_schema()` on every startup — idempotent `ALTER TABLE … ADD COLUMN IF NOT EXISTS` statements for columns that migrations may have missed. Add new must-exist columns here as a safety net alongside the proper Alembic migration.

### 3-Layer Risk Chain
All order submissions pass through: agent-level risk → execution-level risk → global risk monitor. Circuit breaker (three-state: closed/open/half-open) wraps all broker adapter calls.
