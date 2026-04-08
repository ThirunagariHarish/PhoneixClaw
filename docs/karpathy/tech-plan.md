# Tech Plan: Phoenix Karpathy Features
### Verifiable Alpha CI · Agent Knowledge Wiki · Nightly Consolidation · Smart Context Builder · Phoenix Brain

**Status:** v1.0 — Ready for implementation  
**Date:** 2025-01-28  
**Author:** Atlas (Architect)  
**Architecture ref:** [`architecture.md`](./architecture.md)  
**Implementing engineer:** Devin (implement one phase at a time — do not skip ahead)

---

## Ground Rules for Devin

1. **Do NOT re-greenfield existing code.** Read each "existing file to extend" entry before writing anything. The codebase has 43 route files, a live scheduler, a full auth/IDOR middleware stack, and 34 Alembic migrations. Extend, don't replace.
2. **Migration pattern:** Copy the `_has_column(table, col)` guard from `034_add_analyst_agent.py`. Every new column add must be idempotent.
3. **Repository pattern:** All new DB access goes through a new `XRepository` class that extends `BaseRepository` from `apps/api/src/repositories/base.py`. Never issue raw SQLAlchemy queries from route handlers.
4. **Route pattern:** `APIRouter(prefix="/api/v2/...", tags=["..."])` — register in `apps/api/src/main.py` using the existing include_router block.
5. **Auth pattern:** `request.state.user_id` for IDOR checks, `request.state.is_admin` for admin. Never invent a new auth mechanism.
6. **Dependency injection:** Use `DbSession` from `apps/api/src/deps.py` (`Annotated[AsyncSession, Depends(get_session)]`).
7. **Agent tools:** Follow `agents/templates/live-trader-v1/tools/report_to_phoenix.py` exactly — use `httpx`, read `PHOENIX_API_URL` / `PHOENIX_API_KEY` / `PHOENIX_TARGET_AGENT_ID` from env.
8. **Tests:** Unit tests in `tests/unit/` (SQLite in-memory fixture), API integration tests in `apps/api/tests/`. Every phase must have passing tests before handoff.
9. **_ensure_prod_schema():** Add table existence checks for every new table at the end of `_ensure_prod_schema()` in `apps/api/src/main.py`.

---

## Phase 0: Verifiable Alpha CI

**Goal:** Every rule in `agents.pending_improvements` gets a backtest CI run before it can be activated. The RulesTab shows a `⚠️ Pending Validation` badge on un-validated rules. Users cannot activate a rule with `backtest_status != "passed"`.

**Dependencies:** None — this is the safety gate prerequisite for all subsequent phases.

**Estimated complexity:** Medium (new service + 1 endpoint + UI badge)

---

### 0.1 Files to Create

#### `apps/api/src/services/backtest_ci.py` — NEW

**Class:** `BacktestCIService`

**Thresholds (class constants):**
```python
SHARPE_MIN = 0.8
WIN_RATE_MIN = 0.53
MAX_DRAWDOWN_MIN = -0.15   # e.g. -0.12 passes, -0.18 fails
PROFIT_FACTOR_MIN = 1.3
MIN_TRADES = 15
BORDERLINE_TOLERANCE = 0.10  # 10% miss on a single threshold = borderline
```

**Methods to implement:**
- `async def evaluate_rule(self, agent_id: UUID, improvement_id: str, rule_dict: dict, session: AsyncSession) -> BacktestCIResult`
  1. Load the `Agent` row via the session.
  2. Check `len(agent.pending_improvements) <= 50` (reject if over cap with 400).
  3. Set `pending_improvements[improvement_id]["backtest_status"] = "running"` and save.
  4. Dispatch `asyncio.create_task(self._run_async(agent_id, improvement_id, rule_dict, session))`.
  5. Return immediately with `status="running"`.

- `async def _run_async(self, agent_id: UUID, improvement_id: str, rule_dict: dict, session: AsyncSession) -> None`
  1. Call the **existing** `ClaudeBacktester` (import from `apps/api/src/services/claude_backtester.py`) — pass `rule_dict` as the strategy config.
  2. Await completion; read resulting `AgentBacktest` row by ID.
  3. Call `_evaluate_thresholds(backtest_row)` to get status.
  4. Write result back: `agent.pending_improvements[improvement_id]["backtest_status"] = status`, populate `backtest_metrics`, `backtest_passed`, `backtest_run_id`, `backtest_ran_at`, and optionally `borderline_reason`.
  5. Save agent row with `session.commit()`.
  6. Write an `AgentLog` entry (INFO level, context includes improvement_id and status).

- `def _evaluate_thresholds(self, backtest: AgentBacktest) -> tuple[str, str | None]`
  - Returns `("passed", None)`, `("borderline", reason_str)`, or `("failed", reason_str)`.
  - Logic: count how many thresholds fail. 0 fails → passed. 1 fail AND within tolerance → borderline. 1+ fail beyond tolerance OR 2+ fails → failed.

**Pydantic response model:**
```python
class BacktestCIResult(BaseModel):
    improvement_id: str
    backtest_status: str  # "running" | "passed" | "failed" | "borderline"
    message: str
```

---

### 0.2 Files to Modify

#### `apps/api/src/routes/agents.py` — EXTEND (do NOT rewrite)

Add one new endpoint AFTER the existing routes in the file:

```python
@router.post("/{agent_id}/improvements/{improvement_id}/run-backtest", status_code=202)
async def run_improvement_backtest(
    agent_id: str,
    improvement_id: str,
    request: Request,
    session: DbSession,
) -> BacktestCIResult:
```

- IDOR check: `agent.user_id == request.state.user_id` (raise 403 if mismatch).
- Check improvement_id exists in `agent.pending_improvements` (raise 404 if missing).
- Check `pending_improvements[improvement_id].get("backtest_status") != "running"` (raise 409 if already running).
- Instantiate `BacktestCIService()` and call `evaluate_rule(...)`.
- Import `BacktestCIService` at top of file.

#### `apps/api/src/main.py` — EXTEND

- Import and register the backtest CI route (it's already on the agents router, so no new `include_router` call needed — but verify the agents router is already registered under `/api/v2/agents`).
- No `_ensure_prod_schema()` change needed for Phase 0 (no new tables).

#### `apps/dashboard/src/components/AgentDashboard.tsx` — EXTEND (RulesTab section only)

**IMPORTANT:** Do NOT touch PortfolioTab, TradesTab, ChatTab, IntelligenceTab, LogsTab, or ScheduleTab. Only modify the Rules tab rendering section.

Find the section that renders rule items in the Rules tab. For each rule/item in `pending_improvements`, add:
- If `item.backtest_status === undefined || item.backtest_status === "pending"`: render `<Badge variant="outline" className="text-yellow-600">⚠️ Pending Validation</Badge>`
- If `item.backtest_status === "running"`: render `<Badge variant="outline" className="text-blue-500">🔄 Running CI...</Badge>`
- If `item.backtest_status === "borderline"`: render `<Badge variant="outline" className="text-orange-500">⚠️ Borderline — Review Required</Badge>`
- If `item.backtest_status === "failed"`: render `<Badge variant="destructive">✗ CI Failed</Badge>`
- If `item.backtest_status === "passed"`: render `<Badge variant="default" className="text-green-600">✓ CI Passed</Badge>`

Disable the "Activate Rule" button (if present) when `backtest_status !== "passed"`.

Add a "Run Backtest CI" button next to each pending improvement that calls:
```
POST /api/v2/agents/{id}/improvements/{improvement_id}/run-backtest
```
Use TanStack Query `useMutation` (existing pattern in the dashboard).

---

### 0.3 Tests

**`tests/unit/test_backtest_ci.py`** — NEW
- Test `_evaluate_thresholds` with a mock `AgentBacktest` for all three outcomes: passed, borderline (1 threshold missed by 5%), failed (2 thresholds missed).
- Test that `evaluate_rule` sets `backtest_status="running"` synchronously.
- Use SQLite in-memory fixture from existing `tests/conftest.py`.

**`apps/api/tests/test_routes_improvements.py`** — NEW
- Test `POST /api/v2/agents/{id}/improvements/{imp_id}/run-backtest` returns 202.
- Test 403 on wrong user_id.
- Test 404 on missing improvement_id.
- Test 409 on already-running backtest.

---

### 0.4 Definition of Done — Phase 0

- [ ] `BacktestCIService` passes all unit tests
- [ ] Endpoint returns 202 with correct shape
- [ ] IDOR (403), 404, 409 cases covered by tests
- [ ] RulesTab shows correct badge for each `backtest_status` value
- [ ] Activate button disabled for non-passed rules
- [ ] No existing tests broken

---

## Phase 1: Wiki DB + API

**Goal:** Create the `agent_wiki_entries` and `agent_wiki_entry_versions` tables, the SQLAlchemy models, the `WikiRepository`, and all 8 REST API endpoints. No frontend, no agent tool yet.

**Dependencies:** Phase 0 complete (or run in parallel — no code dependency).

**Estimated complexity:** High (new models + full CRUD + search + export)

---

### 1.1 Files to Create

#### `shared/db/migrations/versions/035_agent_wiki.py` — NEW

**Revision:** `035_agent_wiki`  
**Down revision:** `034_add_analyst_agent` (string, must match exactly)  
**Branch labels:** None  
**Depends on:** None

**`upgrade()` must:**
1. `CREATE EXTENSION IF NOT EXISTS pg_trgm` — wrapped in try/except (extension may already exist or require superuser; catch and log warning, do not fail migration).
2. Create table `agent_wiki_entries` with all columns from the data model (Section 6.1 of architecture.md). Use `op.create_table(...)` with all column definitions.
3. Create table `agent_wiki_entry_versions` with all columns including UNIQUE constraint on `(entry_id, version)`.
4. Create all indexes listed in the data model (use `op.create_index(...)`).
5. Wrap every `op.create_table` and `op.create_index` call in `_has_table` / `_has_index` guards for idempotency.

**`_has_table(table_name)` helper** (add to migration file, same pattern as `_has_column`):
```python
def _has_table(table_name: str) -> bool:
    from sqlalchemy import text
    conn = op.get_bind()
    result = conn.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_name=:t"),
        {"t": table_name},
    )
    return result.scalar() is not None
```

**`downgrade()` must:** Drop both tables (CASCADE) and indexes.

#### `shared/db/models/wiki.py` — NEW

```python
# Illustrative class structure — pseudocode, Devin writes the real implementation
class AgentWikiEntry(Base):
    __tablename__ = "agent_wiki_entries"
    # All columns per architecture.md Section 6.1
    # Use ARRAY(String) for tags, symbols
    # Use ARRAY(UUID(as_uuid=True)) for trade_ref_ids
    # Use mapped_column with Mapped[] typed annotations (same pattern as agent.py)

class AgentWikiEntryVersion(Base):
    __tablename__ = "agent_wiki_entry_versions"
    # All columns per architecture.md Section 6.1
    # UniqueConstraint("entry_id", "version", name="uq_wiki_version")
```

Import location for other modules: `from shared.db.models.wiki import AgentWikiEntry, AgentWikiEntryVersion`

#### `apps/api/src/repositories/wiki_repo.py` — NEW

**Class:** `WikiRepository(BaseRepository)`

**Constructor:** `def __init__(self, session: AsyncSession): super().__init__(session, AgentWikiEntry)`

**Methods to implement:**
- `async def list_entries(self, agent_id: UUID, category: str | None, tag: str | None, symbol: str | None, search: str | None, is_shared: bool | None, page: int, per_page: int) -> tuple[list[AgentWikiEntry], int]`
  - Filter `is_active=True`
  - `category` → `WHERE category = :cat`
  - `tag` → `WHERE :tag = ANY(tags)`
  - `symbol` → `WHERE :symbol = ANY(symbols)`
  - `search` → `WHERE similarity(content, :q) > 0.1 OR title ILIKE '%:q%'` — wrap in try/except for pg_trgm fallback
  - Returns `(rows, total_count)`

- `async def get_entry(self, agent_id: UUID, entry_id: UUID) -> AgentWikiEntry | None`
  - `WHERE id=entry_id AND agent_id=agent_id AND is_active=True`

- `async def get_versions(self, entry_id: UUID) -> list[AgentWikiEntryVersion]`
  - `ORDER BY version DESC`

- `async def create_entry(self, agent_id: UUID, user_id: UUID, data: dict) -> AgentWikiEntry`
  - Insert entry row.
  - Insert version row (version=1, content=data["content"]).
  - Return entry.

- `async def update_entry(self, agent_id: UUID, entry_id: UUID, data: dict) -> AgentWikiEntry | None`
  - Load entry (404 if missing).
  - Increment `version`.
  - Update fields.
  - Insert new `AgentWikiEntryVersion` row (with `updated_by`, `change_reason` if provided).
  - Return updated entry.

- `async def soft_delete(self, agent_id: UUID, entry_id: UUID) -> bool`
  - `UPDATE SET is_active=False WHERE id=entry_id AND agent_id=agent_id`

- `async def export_entries(self, agent_id: UUID) -> list[AgentWikiEntry]`
  - All active entries, ordered by category, created_at.

- `async def semantic_search(self, agent_id: UUID, query_text: str, category: str | None, top_k: int, include_shared: bool) -> list[tuple[AgentWikiEntry, float]]`
  - Try pg_trgm: `SELECT *, similarity(content, :q) AS score FROM agent_wiki_entries WHERE (agent_id=:aid OR (is_shared=True AND :include_shared)) AND is_active=True ORDER BY score DESC LIMIT :top_k`
  - On exception (pg_trgm unavailable): fallback to ILIKE with score=0.5 for all results.

- `async def list_shared(self, category: str | None, symbol: str | None, search: str | None, min_confidence: float, page: int, per_page: int) -> tuple[list[AgentWikiEntry], int]`
  - `WHERE is_shared=True AND is_active=True AND confidence_score >= min_confidence`
  - Joins agents table to include agent name.

#### `apps/api/src/routes/wiki.py` — NEW

**Router:** `APIRouter(prefix="/api/v2/agents/{agent_id}/wiki", tags=["wiki"])`

**Pydantic models to define in this file:**
```python
class WikiEntryCreate(BaseModel):
    category: str
    title: str
    content: str
    subcategory: str | None = None
    tags: list[str] = []
    symbols: list[str] = []
    confidence_score: float = 0.5
    trade_ref_ids: list[str] = []
    is_shared: bool = False

class WikiEntryUpdate(BaseModel):
    # All fields optional
    category: str | None = None
    title: str | None = None
    content: str | None = None
    subcategory: str | None = None
    tags: list[str] | None = None
    symbols: list[str] | None = None
    confidence_score: float | None = None
    trade_ref_ids: list[str] | None = None
    is_shared: bool | None = None
    change_reason: str | None = None

class WikiQueryRequest(BaseModel):
    query_text: str
    category: str | None = None
    top_k: int = 10
    include_shared: bool = True

class WikiEntryResponse(BaseModel):
    id: str
    agent_id: str
    category: str
    subcategory: str | None
    title: str
    content: str
    tags: list[str]
    symbols: list[str]
    confidence_score: float
    trade_ref_ids: list[str]
    created_by: str
    is_active: bool
    is_shared: bool
    version: int
    created_at: str
    updated_at: str
```

**IDOR helper** (define at top of routes file):
```python
async def _get_agent_or_403(agent_id: str, request: Request, session: AsyncSession) -> Agent:
    agent = await session.get(Agent, UUID(agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if str(agent.user_id) != str(request.state.user_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    return agent
```

**8 endpoints** — all follow the exact contract in architecture.md Section 7.2.

**Export endpoint special handling:**
- `format=json`: Return `JSONResponse` with `Content-Disposition: attachment; filename="wiki_export.json"`
- `format=markdown`: Build markdown string grouping entries by category, return `Response(content=md, media_type="text/markdown", headers={"Content-Disposition": "attachment; filename=wiki_export.md"})`

---

### 1.2 Files to Modify

#### `apps/api/src/main.py` — EXTEND

**Two changes:**

1. Add import and `app.include_router(wiki_router)` in the routers block:
```python
from apps.api.src.routes.wiki import router as wiki_router
# ... in the include_router block:
app.include_router(wiki_router)
```

2. In `_ensure_prod_schema()`, add at the end:
```python
# Karpathy Phase 1: wiki tables
for tbl in ["agent_wiki_entries", "agent_wiki_entry_versions"]:
    result = await session.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_name=:t"), {"t": tbl}
    )
    if not result.scalar():
        logger.warning(f"_ensure_prod_schema: table {tbl} missing — run alembic upgrade")
```

#### `shared/db/models/__init__.py` — EXTEND

Add `from shared.db.models.wiki import AgentWikiEntry, AgentWikiEntryVersion` to the existing imports (follow the pattern of how Agent is imported).

---

### 1.3 Tests

**`tests/unit/test_wiki_repo.py`** — NEW
- Test `create_entry` creates both entry and version row.
- Test `update_entry` increments version and creates version snapshot.
- Test `soft_delete` sets `is_active=False` without deleting row.
- Test `list_entries` filters by category, tag, symbol.
- Test `semantic_search` fallback when pg_trgm raises exception.
- Use SQLite in-memory; note: `similarity()` function unavailable in SQLite — mock the pg_trgm branch.

**`apps/api/tests/test_routes_wiki.py`** — NEW
- Test all 8 endpoints: 201 on create, 200 on list/get/versions, 200 on query, 204 on delete, 200 on export (both formats).
- Test 403 on wrong user_id for CRUD endpoints.
- Test 404 on missing entry_id.
- Test pagination (page=2, per_page=5).

---

### 1.4 Definition of Done — Phase 1

- [ ] Migration `035_agent_wiki.py` runs cleanly on fresh DB and is idempotent (run twice without error)
- [ ] `AgentWikiEntry` and `AgentWikiEntryVersion` models importable from `shared.db.models.wiki`
- [ ] All 8 wiki endpoints return correct status codes and shapes
- [ ] IDOR enforced (403 on wrong user)
- [ ] Export endpoint returns downloadable JSON and Markdown
- [ ] `semantic_search` fallback to ILIKE when pg_trgm unavailable
- [ ] `_ensure_prod_schema()` logs warning if tables missing
- [ ] All unit and route tests pass
- [ ] No existing tests broken

---

## Phase 2: Wiki Agent Tool + Frontend

**Goal:** Live agent can write wiki entries via `write_wiki_entry.py` tool. Dashboard shows a new "Wiki" tab in `AgentDashboard.tsx`.

**Dependencies:** Phase 1 complete (wiki API must be live).

**Estimated complexity:** Medium (tool is simple; frontend is the bulk of work)

---

### 2.1 Files to Create

#### `agents/templates/live-trader-v1/tools/write_wiki_entry.py` — NEW

**Pattern:** Exactly follow `agents/templates/live-trader-v1/tools/report_to_phoenix.py`.

**Implementation:**
1. Read env vars: `PHOENIX_API_URL`, `PHOENIX_API_KEY`, `PHOENIX_TARGET_AGENT_ID`.
2. Parse CLI args using `argparse`:
   - `--category` (required, must be one of the 8 valid categories — validate and exit 1 if invalid)
   - `--title` (required)
   - `--content` (required)
   - `--subcategory` (optional)
   - `--symbols` (optional, comma-separated → list)
   - `--tags` (optional, comma-separated → list)
   - `--confidence` (optional, float, default 0.5)
   - `--trade_ref_ids` (optional, comma-separated UUIDs → list)
   - `--is_shared` (optional, bool flag, default false)
3. Build payload dict.
4. `httpx.post(f"{PHOENIX_API_URL}/api/v2/agents/{PHOENIX_TARGET_AGENT_ID}/wiki", json=payload, headers={"X-API-Key": PHOENIX_API_KEY}, timeout=10)`
5. On success (201): print `{"success": true, "entry_id": response.json()["id"]}` to stdout; exit 0.
6. On error: print `{"success": false, "error": response.text}` to stdout; exit 1.

**Important:** Do NOT use `async` — keep it synchronous `httpx` (not `httpx.AsyncClient`), same as `report_to_phoenix.py`.

#### `apps/dashboard/src/components/AgentWikiTab.tsx` — NEW

**Props:** `{ agentId: string }`

**State / queries:**
- `useQuery` for `GET /api/v2/agents/{agentId}/wiki` with params for category filter, search text, page.
- `useMutation` for `POST`, `PATCH`, `DELETE` endpoints.

**UI sections:**
1. **Filter bar:** Category dropdown (all 8 categories + "All"), search input (debounced 300ms), symbol filter input.
2. **Entry list:** Card per entry showing:
   - Title (bold), category badge (color-coded), confidence score pill.
   - `symbols` as small badges.
   - `tags` as small outline badges.
   - `created_by` icon (robot for "agent", person for "user").
   - `is_shared` indicator (globe icon if shared).
   - Version number small text.
   - Updated at relative time.
   - Action buttons: Edit (pencil icon), Delete (trash icon, soft-delete), Share toggle.
3. **Create entry button:** Opens a modal/dialog with all fields.
4. **Entry detail modal:** Full `content` rendered as markdown (use `react-markdown` if already in dependencies, otherwise plain `<pre>`). Shows version history button.
5. **Pagination:** Page controls at bottom.

**Import:** Use `BookOpen` icon from `lucide-react` for the tab trigger (existing import pattern in the dashboard).

**Do NOT import any new npm packages** without confirming they are already in `apps/dashboard/package.json`. Use existing Radix UI components, TanStack Query, and Tailwind CSS.

#### `apps/dashboard/src/pages/BrainWikiPage.tsx` — NEW (stub only in Phase 2)

Create a minimal stub that renders "Phoenix Brain — coming in Phase 5" with a `BookOpen` icon. Full implementation is in Phase 5.

---

### 2.2 Files to Modify

#### `apps/dashboard/src/components/AgentDashboard.tsx` — EXTEND

**IMPORTANT:** Read the full file before editing. Make surgical additions only.

**Change 1 — Add Wiki tab trigger:**  
In the `<TabsList>` block (within the Live agent section, where Portfolio/Trades/Chat/Intelligence/Logs/Rules/Schedule tabs are), add after the Schedule tab trigger:
```tsx
<TabsTrigger value="wiki">
  <BookOpen className="h-4 w-4 mr-1" />
  Wiki
</TabsTrigger>
```

**Change 2 — Add Wiki tab content:**  
In the `<TabsContent>` section, add:
```tsx
<TabsContent value="wiki">
  <AgentWikiTab agentId={id} />
</TabsContent>
```

**Change 3 — Add Brain trigger button in Intelligence tab:**  
In the Intelligence tab content, add a `<Button>` labeled "🧠 Open Phoenix Brain" that links to `/brain/wiki` (use React Router `<Link>` or `navigate()`).

**Change 4 — Import AgentWikiTab:**  
Add `import { AgentWikiTab } from './AgentWikiTab'` at the top of the file with other component imports.

**Change 5 — Import BookOpen:**  
Check if `BookOpen` is already imported from `lucide-react`; if not, add it to the existing lucide-react import line.

---

### 2.3 Tests

**`tests/unit/test_write_wiki_entry.py`** — NEW
- Test CLI arg parsing for valid and invalid categories.
- Mock `httpx.post` — verify payload shape and headers.
- Test success (201 mock) prints correct stdout JSON.
- Test error (400 mock) prints error JSON and exits 1.

**Frontend:** No automated tests required for Phase 2. Devin must manually verify:
- Wiki tab appears in AgentDashboard for LIVE/PAPER/RUNNING agents.
- Create entry flow works end-to-end.
- Category filter narrows the list.
- Delete (soft) removes entry from list without page reload (optimistic update or refetch).

---

### 2.4 Definition of Done — Phase 2

- [ ] `write_wiki_entry.py` CLI works end-to-end against local dev API
- [ ] Agent can call the tool from a Claude Code session and see entry appear in the DB
- [ ] `AgentWikiTab.tsx` renders list of wiki entries with filtering
- [ ] Create, edit, delete flows complete without errors
- [ ] Wiki tab appears in `AgentDashboard.tsx` with `BookOpen` icon
- [ ] Brain trigger button in Intelligence tab links to `/brain/wiki`
- [ ] `BrainWikiPage.tsx` stub renders without errors
- [ ] All Phase 1 and Phase 2 unit tests pass

---

## Phase 3: Nightly Consolidation Pipeline

**Goal:** A Claude Code session runs nightly at 18:15 ET for each live agent with `consolidation_enabled=true`. It reads TRADE_OBSERVATION wiki entries and recent trades, synthesizes patterns, and proposes rule improvements. The dashboard shows a ConsolidationPanel.

**Dependencies:** Phase 1 complete (wiki API), Phase 0 complete (backtest CI for proposed rules).

**Estimated complexity:** High (new table + service + scheduler + tool + frontend)

---

### 3.1 Files to Create

#### `shared/db/migrations/versions/036_consolidation_runs.py` — NEW

**Revision:** `036_consolidation_runs`  
**Down revision:** `035_agent_wiki`  
**Branch labels:** None

**`upgrade()` must:**
1. Create table `consolidation_runs` with all columns from architecture.md Section 6.1.
2. Create indexes: `ix_consolidation_agent_id` on `(agent_id)`, `ix_consolidation_status` on `(status)`.
3. Use `_has_table` guard (copy from 035).

**`downgrade()` must:** Drop table and indexes.

#### `shared/db/models/consolidation.py` — NEW

```python
# Illustrative class structure — pseudocode
class ConsolidationRun(Base):
    __tablename__ = "consolidation_runs"
    # All columns per architecture.md Section 6.1
    # Use same Mapped[] / mapped_column pattern as agent.py
```

Import location: `from shared.db.models.consolidation import ConsolidationRun`

#### `apps/api/src/repositories/consolidation_repo.py` — NEW

**Class:** `ConsolidationRepository(BaseRepository)`

**Constructor:** `super().__init__(session, ConsolidationRun)`

**Methods:**
- `async def create_run(self, agent_id: UUID, run_type: str, scheduled_for: datetime | None) -> ConsolidationRun`
- `async def update_run(self, run_id: UUID, data: dict) -> ConsolidationRun | None`
  - Partial update — only keys present in data are written.
- `async def get_run(self, run_id: UUID) -> ConsolidationRun | None`
- `async def list_runs(self, agent_id: UUID, page: int, per_page: int) -> tuple[list[ConsolidationRun], int]`
  - ORDER BY created_at DESC.
- `async def get_running_run(self, agent_id: UUID) -> ConsolidationRun | None`
  - `WHERE agent_id=:aid AND status='running'` — used for 409 check.

#### `apps/api/src/services/consolidation_service.py` — NEW

**Class:** `ConsolidationService`

**Methods:**

- `async def run_for_agent(self, agent_id: UUID, run_type: str, session: AsyncSession) -> UUID`
  1. Check `agent.manifest.get("consolidation_enabled", False)` — raise 403 if false and run_type != "manual".
  2. Check for existing running run via `ConsolidationRepository.get_running_run()` — raise 409 if found.
  3. Check token budget: `agent.tokens_used_month_usd < agent.monthly_token_budget_usd` (if budget set) — skip if over budget.
  4. Create `ConsolidationRun` row with `status="pending"`.
  5. `asyncio.create_task(self._run_consolidation(agent_id, run_id, session))`.
  6. Return `run_id`.

- `async def _run_consolidation(self, agent_id: UUID, run_id: UUID, session: AsyncSession) -> None`
  1. Update run `status="running"`, `started_at=now()`.
  2. Load agent and prepare working directory (follow `_prepare_analyst_directory` pattern from `agent_gateway.py` — copy workdir setup, include tools/).
  3. Copy `nightly_consolidation.py` tool into workdir.
  4. Spawn Claude Code session (use `claude_agent_sdk.query()` — same import as `agent_gateway.py`).
  5. On success: update `status="completed"`, `completed_at=now()`, populate metrics from tool stdout.
  6. On exception: update `status="failed"`, `error_message=str(e)`.
  7. Write `AgentLog` entry.

- `async def run_nightly_for_all_agents(self) -> None`
  - Called by scheduler at 18:15 ET.
  - Acquire fresh `AsyncSession` via `get_session()`.
  - `SELECT agents WHERE status IN ('RUNNING', 'PAPER')`.
  - For each agent: check `manifest.get("consolidation_enabled")`. If `total_trades >= 20` and `consolidation_enabled` is not yet True, set it and save (gate check).
  - For each `consolidation_enabled=True` agent: call `run_for_agent(agent_id, "nightly", session)`.
  - Log total agents processed.

#### `agents/templates/live-trader-v1/tools/nightly_consolidation.py` — NEW

**Pattern:** Synchronous httpx, same as `write_wiki_entry.py`.

**CLI args:**
- `--agent_id` (required, UUID)
- `--consolidation_run_id` (required, UUID)

**Implementation steps:**
1. Fetch all TRADE_OBSERVATION wiki entries: `GET /wiki?category=TRADE_OBSERVATION&per_page=100&page=1` — paginate if needed.
2. Fetch recent filled trades: `GET /live-trades?status=FILLED&limit=200`.
3. Analyze patterns (this is the Claude Code task — the LLM does the analysis by reading the data and calling the write tools).
4. For each discovered pattern: call `write_wiki_entry.py` tool via subprocess OR direct HTTP (preferred: direct HTTP to avoid subprocess overhead).
5. For proposed rules: `PATCH /agents/{id}` to append to `pending_improvements`.
6. Print final JSON metrics to stdout:
   ```json
   {"trades_analyzed": N, "wiki_entries_written": M, "patterns_found": K, "rules_proposed": J}
   ```

**NOTE:** The tool is used by a Claude Code agent session — the LLM reads the data fetched in steps 1–2, decides what patterns to write, and calls the write_wiki_entry HTTP directly. The `nightly_consolidation.py` tool is the orchestrator that fetches data and reports metrics back.

#### `apps/api/src/routes/consolidation.py` — NEW

**Router:** `APIRouter(prefix="/api/v2/agents/{agent_id}/consolidation", tags=["consolidation"])`

**Pydantic models:**
```python
class ConsolidationRunRequest(BaseModel):
    run_type: str = "manual"

class ConsolidationRunResponse(BaseModel):
    id: str
    agent_id: str
    run_type: str
    status: str
    scheduled_for: str | None
    started_at: str | None
    completed_at: str | None
    trades_analyzed: int
    wiki_entries_written: int
    wiki_entries_updated: int
    wiki_entries_pruned: int
    patterns_found: int
    rules_proposed: int
    consolidation_report: str | None
    error_message: str | None
    created_at: str
```

**2 endpoints** — both matching contracts in architecture.md Section 7.4.

#### `apps/dashboard/src/components/ConsolidationPanel.tsx` — NEW

**Props:** `{ agentId: string }`

**Sections:**
1. **Status card:** Last run status (badge), last run time, next scheduled run (18:15 ET next weekday).
2. **Metrics row:** trades_analyzed, wiki_entries_written, patterns_found, rules_proposed — styled as metric cards.
3. **Manual trigger button:** `POST /api/v2/agents/{agentId}/consolidation/run` — disabled if status is "running" or if `consolidation_enabled` is false. Show tooltip: "Agent needs 20+ trades to enable consolidation".
4. **Run history table:** Last 10 runs with status badge, timestamps, metrics.
5. **Consolidation report:** Collapsible markdown viewer for the last completed run's `consolidation_report`.

---

### 3.2 Files to Modify

#### `apps/api/src/services/scheduler.py` — EXTEND

**IMPORTANT:** Read the full file before editing. Do NOT change any existing jobs. Add ONE new job.

In the `start_scheduler()` function, after the last `scheduler.add_job(...)` call, add:

```python
# Karpathy Phase 3: Nightly consolidation at 18:15 ET weekdays
scheduler.add_job(
    _job_nightly_consolidation,
    CronTrigger(hour=18, minute=15, day_of_week="mon-fri", timezone=_ET_TZ),
    id="nightly_consolidation",
    replace_existing=True,
    misfire_grace_time=1800,
)
```

Add the job function at the bottom of the file (before any `if __name__ == "__main__"` block):

```python
async def _job_nightly_consolidation() -> None:
    """18:15 ET weekdays — run consolidation for all eligible agents."""
    from apps.api.src.services.consolidation_service import ConsolidationService
    try:
        svc = ConsolidationService()
        await svc.run_nightly_for_all_agents()
    except Exception as exc:
        logger.exception("nightly_consolidation job failed: %s", exc)
```

#### `apps/api/src/main.py` — EXTEND

1. Add `from apps.api.src.routes.consolidation import router as consolidation_router` and `app.include_router(consolidation_router)`.
2. In `_ensure_prod_schema()`, add check for `consolidation_runs` table.
3. Add `from shared.db.models.consolidation import ConsolidationRun` to model imports (if not already present via `__init__.py`).

#### `shared/db/models/__init__.py` — EXTEND

Add `from shared.db.models.consolidation import ConsolidationRun`.

#### `apps/dashboard/src/components/AgentDashboard.tsx` — EXTEND

Add `ConsolidationPanel` to the agent detail page. Suggested placement: below the existing tab content, always visible (not inside a tab), or as a new "Consolidation" tab. **Decision:** Add as a new "Consolidation" tab in the live section tab list (following the same pattern as Wiki tab from Phase 2).

Tab trigger: Use `BarChart2` icon from lucide-react.

---

### 3.3 Tests

**`tests/unit/test_consolidation_service.py`** — NEW
- Test `run_for_agent` raises 403 when `consolidation_enabled=False`.
- Test `run_for_agent` raises 409 when a run is already running.
- Test `run_nightly_for_all_agents` sets `consolidation_enabled=True` when `total_trades >= 20`.
- Mock `asyncio.create_task` — do not actually spawn Claude Code in unit tests.

**`apps/api/tests/test_routes_consolidation.py`** — NEW
- Test `POST .../consolidation/run` returns 202 with correct shape.
- Test 409 when already running.
- Test `GET .../consolidation/runs` returns paginated list.
- Test 403 on wrong user.

**`tests/unit/test_nightly_consolidation_tool.py`** — NEW
- Mock httpx — verify the tool calls GET wiki, GET trades, and returns correct metrics JSON.

---

### 3.4 Definition of Done — Phase 3

- [ ] Migration `036_consolidation_runs.py` runs cleanly and is idempotent
- [ ] Scheduler starts 18:15 ET job without error (check `scheduler.get_jobs()`)
- [ ] `ConsolidationService.run_for_agent()` correctly gates on `consolidation_enabled`
- [ ] `nightly_consolidation.py` tool runs against local API and writes wiki entries
- [ ] Consolidation tab/panel visible in AgentDashboard
- [ ] Manual trigger button works; status updates after run
- [ ] All new tests pass; no existing tests broken

---

## Phase 4: Smart Context Builder

**Goal:** Replace static context loading in `chat_responder.py` with priority-tiered, token-budgeted context assembly. Behind `ENABLE_SMART_CONTEXT=false` feature flag. Add `ContextDebugger.tsx` panel to the Chat tab.

**Dependencies:** Phase 1 complete (wiki repo must be available for `_tier_wiki`).

**Estimated complexity:** Medium-High (new service + DB table + two service modifications + frontend panel)

---

### 4.1 Files to Create

#### `shared/db/migrations/versions/037_context_sessions.py` — NEW

**Revision:** `037_context_sessions`  
**Down revision:** `036_consolidation_runs`

**`upgrade()` must:**
1. Create `context_sessions` table with all columns from architecture.md Section 6.1.
2. Create index `ix_context_sessions_agent_id` on `(agent_id)`.
3. Use `_has_table` guard.

#### `shared/db/models/context_session.py` — NEW

```python
# Illustrative class structure — pseudocode
class ContextSession(Base):
    __tablename__ = "context_sessions"
    # All columns per architecture.md Section 6.1
```

#### `shared/context/__init__.py` — NEW

```python
from shared.context.builder import ContextBuilderService

__all__ = ["ContextBuilderService"]
```

#### `shared/context/builder.py` — NEW

**Class:** `ContextBuilderService`

**Class constants:**
```python
TIER_LIMITS = {
    "signal":   500,
    "wiki":     2000,
    "wins":     1500,
    "manifest": 1500,
    "recent":   1500,
    "chat":     1000,
}
DEFAULT_BUDGET = 8000
```

**Methods:**

- `async def build_for_chat(self, agent_id: UUID, user_message: str, session: AsyncSession) -> "ContextBundle"`
  1. Load agent row.
  2. Get budget: `agent.manifest.get("wiki_token_budget") or int(os.getenv("WIKI_CONTEXT_TOKEN_BUDGET", 8000))`.
  3. Call `_build(agent_id, user_message, budget, session_type="chat", session=session)`.

- `async def build_for_signal(self, agent_id: UUID, signal: dict, session: AsyncSession) -> "ContextBundle"`
  1. Extract signal text from signal dict.
  2. Call `_build(...)` with `session_type="signal"`.

- `async def _build(self, agent_id: UUID, query_text: str, budget: int, session_type: str, session: AsyncSession) -> "ContextBundle"`
  1. Iterate through TIER_LIMITS in order.
  2. For each tier: compute `remaining = min(tier_limit, budget - tokens_used)`. If remaining <= 0, skip.
  3. Call the appropriate `_tier_*` method.
  4. Accumulate context dict and token count.
  5. Compute `quality_score` = `wiki_entries_injected / max(1, top_k)` (rough proxy).
  6. Fire-and-forget: `asyncio.create_task(self._record_session(agent_id, session_type, ..., session))`.
  7. Return `ContextBundle`.

- `async def _tier_wiki(self, agent_id: UUID, query: str, token_limit: int, session: AsyncSession) -> tuple[list[dict], int]`
  - Instantiate `WikiRepository(session)`.
  - Call `semantic_search(agent_id, query, top_k=10)`.
  - Convert entries to dicts, estimate tokens (len(content) / 4 — rough approximation).
  - Truncate list to fit within token_limit.
  - Return `(entries, tokens_used)`.

- `async def _tier_winning_trades(self, agent_id: UUID, token_limit: int, session: AsyncSession) -> tuple[list[dict], int]`
  - `SELECT * FROM live_trades WHERE agent_id=:aid AND status='FILLED' AND pnl > 0 ORDER BY pnl DESC LIMIT 20`
  - Truncate to token_limit.

- `async def _tier_manifest_sections(self, agent: Agent, query: str, token_limit: int) -> tuple[dict, int]`
  - Extract relevant sections from `agent.manifest` (rules, modes, knowledge).
  - Serialize to JSON, truncate to token_limit.

- `async def _tier_recent_trades(self, agent_id: UUID, token_limit: int, session: AsyncSession) -> tuple[list[dict], int]`
  - `SELECT * FROM live_trades WHERE agent_id=:aid AND created_at > now() - interval '5 days' ORDER BY created_at DESC LIMIT 50`

- `async def _tier_chat_history(self, agent_id: UUID, token_limit: int, session: AsyncSession) -> tuple[list[dict], int]`
  - `SELECT * FROM chat_messages WHERE agent_id=:aid ORDER BY created_at DESC LIMIT 8` — reverse to chronological order.

- `async def _record_session(self, agent_id: UUID, session_type: str, tokens_used: int, wiki_entries_injected: int, trades_injected: int, budget: int, quality_score: float, session: AsyncSession) -> None`
  - Best-effort: wrap in try/except, swallow all errors.
  - INSERT `context_sessions` row.

**Dataclass:**
```python
@dataclass
class ContextBundle:
    context: dict[str, Any]  # {tier_name: data}
    tokens_used: int
    budget: int
    wiki_entries_injected: int
    trades_injected: int
    quality_score: float
    session_type: str
```

#### `apps/dashboard/src/components/ContextDebugger.tsx` — NEW

**Props:** `{ agentId: string; enabled: boolean }`

**UI:** Collapsible panel (default collapsed) shown at bottom of Chat tab.
- When `enabled=false`: show message "Smart Context disabled — set ENABLE_SMART_CONTEXT=true".
- When `enabled=true`: query `GET /api/v2/agents/{agentId}/context-sessions?limit=1` (see note below about the endpoint).
- Display last context session: token budget used, wiki entries injected, tier breakdown bar chart (use Radix UI progress bars — no new charting library).

**Note:** The `context-sessions` read endpoint is a simple list query — add it to `apps/api/src/routes/agents.py` as:
```
GET /api/v2/agents/{agent_id}/context-sessions
```
Returns last 10 sessions with all columns. Auth: same IDOR pattern. This is a small addition — add it directly in Phase 4 routes work.

---

### 4.2 Files to Modify

#### `apps/api/src/services/chat_responder.py` — EXTEND

**IMPORTANT:** Read the full file first. The change is minimal — a conditional branch around context loading.

In `respond_to_chat(agent_id, user_message)`, find the call to `_load_context(agent_id)`. Wrap it:

```python
# Pseudocode showing the modification pattern — Devin writes the real code
import os
ENABLE_SMART_CONTEXT = os.getenv("ENABLE_SMART_CONTEXT", "false").lower() == "true"

if ENABLE_SMART_CONTEXT:
    from shared.context.builder import ContextBuilderService
    builder = ContextBuilderService()
    bundle = await builder.build_for_chat(agent_id, user_message, session)
    ctx = bundle.context
    # Merge bundle.context into the existing ctx dict shape expected by _prepare_workdir
    # Map: ctx["wiki"] → ctx["wiki_entries"], etc.
else:
    ctx = await _load_context(agent_id)
```

**Key:** `_prepare_workdir` and `_build_prompt` must still receive the same shape dict they expect. If the smart context bundle has extra keys, that is fine — the workdir functions will just include more context. Do NOT change `_prepare_workdir` or `_build_prompt` signatures.

#### `apps/api/src/services/agent_gateway.py` — EXTEND (minimal change)

In `_run_analyst` or wherever the live trading context is assembled, add a similar `ENABLE_SMART_CONTEXT` conditional. This is a secondary integration — if it requires large changes, defer to a sub-task and mark as "Phase 4 stretch goal".

#### `apps/api/src/main.py` — EXTEND

1. Add `context_sessions` table check to `_ensure_prod_schema()`.
2. Add `from shared.db.models.context_session import ContextSession` to model imports.
3. Add `GET /agents/{id}/context-sessions` endpoint to `agents.py` route file (or a new small routes file).

#### `shared/db/models/__init__.py` — EXTEND

Add `from shared.db.models.context_session import ContextSession`.

#### `apps/dashboard/src/components/AgentDashboard.tsx` — EXTEND

In the Chat tab content, add `<ContextDebugger agentId={id} enabled={smartContextEnabled} />` at the bottom. `smartContextEnabled` is a prop or env-derived constant — hardcode to `false` initially (matches the default flag).

---

### 4.3 Tests

**`tests/unit/test_context_builder.py`** — NEW
- Test `_build` with a mock wiki repo returning 3 entries — verify `wiki_entries_injected=3`.
- Test token budget exhaustion — verify lower-priority tiers are skipped when budget is exceeded by earlier tiers.
- Test `_tier_wiki` fallback when `WikiRepository.semantic_search` raises.
- Test `_record_session` exception is swallowed (best-effort).

**Integration test:**
- Set `ENABLE_SMART_CONTEXT=true` in test env.
- Send a chat message — verify `context_sessions` row is written.
- Verify chat response still arrives (smart context does not break chat).

---

### 4.4 Definition of Done — Phase 4

- [ ] Migration `037_context_sessions.py` runs cleanly and is idempotent
- [ ] `ContextBuilderService` builds context within token budget (unit tested)
- [ ] `ENABLE_SMART_CONTEXT=false` (default) — chat behavior identical to pre-Phase 4
- [ ] `ENABLE_SMART_CONTEXT=true` — context bundle injected, `context_sessions` row written
- [ ] `ContextDebugger.tsx` renders last session stats without errors
- [ ] No chat latency regression when flag is false
- [ ] All new tests pass; no existing tests broken

---

## Phase 5: Phoenix Brain + Cross-Agent Wiki Sharing + QA + Release

**Goal:** Implement the Phoenix Brain cross-agent wiki view. Extend `ContextBuilderService` to pull shared entries from other agents. Full QA pass. Release.

**Dependencies:** All prior phases complete.

**Estimated complexity:** Medium (brain endpoint is simple; cross-agent context is a small builder extension)

---

### 5.1 Files to Create

#### `apps/api/src/routes/brain.py` — NEW

**Router:** `APIRouter(prefix="/api/v2/brain", tags=["brain"])`

**Endpoint:** `GET /api/v2/brain/wiki` — see architecture.md Section 7.3 for full contract.

**Implementation:**
- Auth: any authenticated user (`request.state.user_id` must be non-null).
- Instantiate `WikiRepository(session)`.
- Call `repo.list_shared(category, symbol, search, min_confidence, page, per_page)`.
- Join agent names: for each entry, add `agent_name` field by loading agent rows (batch load, not N+1).
- Return paginated response.

#### `apps/dashboard/src/pages/BrainWikiPage.tsx` — FULL IMPLEMENTATION

Replace the Phase 2 stub with the full page.

**Sections:**
1. **Header:** "🧠 Phoenix Brain" with subtitle "Cross-agent knowledge base — shared learnings from all agents".
2. **Filter bar:** Category dropdown, symbol input, min_confidence slider (0.0–1.0, step 0.1), search text.
3. **Entry list:** Same card layout as AgentWikiTab but includes agent_name badge on each card.
4. **Pagination.**
5. **Empty state:** "No shared knowledge yet. Agents share entries by setting is_shared=true in their wiki."

**Route:** Register at `/brain/wiki` in the React Router config (check `apps/dashboard/src/App.tsx` or main router file — add the route without breaking existing routes).

---

### 5.2 Files to Modify

#### `shared/context/builder.py` — EXTEND

In `_tier_wiki`, after fetching agent-owned entries, if budget allows and `include_shared=True`:
```python
# Pseudocode — illustrative only
if tokens_used_so_far < token_limit and include_shared:
    shared = await repo.list_shared(
        category=None, symbol=signal_symbol, search=query,
        min_confidence=0.7, page=1, per_page=5
    )
    # Append shared entries (deduplicate by id)
    # Mark each with {"source": "brain", "agent_name": "..."}
```

This ensures cross-agent learnings from Phoenix Brain appear in Smart Context for all agents.

#### `apps/api/src/main.py` — EXTEND

Register brain router:
```python
from apps.api.src.routes.brain import router as brain_router
app.include_router(brain_router)
```

---

### 5.3 QA Checklist (for Quill)

- [ ] `GET /api/v2/brain/wiki` returns only `is_shared=true` entries
- [ ] Agent A cannot read Agent B's private (non-shared) wiki entries
- [ ] IDOR: user X cannot modify wiki entries belonging to user Y's agents
- [ ] Soft-deleted entries (`is_active=false`) never appear in any list endpoint
- [ ] `pending_improvements` rule with `backtest_status=failed` cannot be activated via API
- [ ] `consolidation_enabled` auto-sets after 20th trade
- [ ] 18:15 ET scheduler job fires (verify in scheduler_status route)
- [ ] Smart context (`ENABLE_SMART_CONTEXT=true`) does not exceed token budget
- [ ] Wiki export (JSON + Markdown formats) downloads correctly
- [ ] Version history shows correct number of versions after multiple edits
- [ ] Migration idempotency: run `alembic upgrade head` twice without error
- [ ] All 43 existing routes still return expected shapes (regression)

---

### 5.4 Release Checklist (for Helix)

- [ ] Migrations 035, 036, 037 in correct order in `alembic.ini` / migration chain
- [ ] `ENABLE_SMART_CONTEXT` env var documented in `SETUP.md` and `docker-compose.yml`
- [ ] `WIKI_CONTEXT_TOKEN_BUDGET` env var documented
- [ ] `CHANGELOG.md` updated with Karpathy feature set
- [ ] All Docker images build cleanly
- [ ] `_ensure_prod_schema()` logs no warnings on fresh deploy
- [ ] Version bump in `apps/api/src/main.py` (FastAPI app `version=` field)

---

### 5.5 Definition of Done — Phase 5

- [ ] `GET /api/v2/brain/wiki` returns shared entries across all agents
- [ ] `BrainWikiPage.tsx` loads and filters brain wiki correctly
- [ ] Smart Context Builder includes cross-agent shared entries (high-confidence only)
- [ ] Full QA checklist above passes
- [ ] Release checklist above complete
- [ ] No regressions in existing functionality

---

## Appendix A: File Creation Checklist

Use this as a master tracking list. Check off each file as Devin completes it.

### New Files — Backend

| File | Phase | Status |
|---|---|---|
| `apps/api/src/services/backtest_ci.py` | 0 | ☐ |
| `shared/db/migrations/versions/035_agent_wiki.py` | 1 | ☐ |
| `shared/db/models/wiki.py` | 1 | ☐ |
| `apps/api/src/repositories/wiki_repo.py` | 1 | ☐ |
| `apps/api/src/routes/wiki.py` | 1 | ☐ |
| `agents/templates/live-trader-v1/tools/write_wiki_entry.py` | 2 | ☐ |
| `shared/db/migrations/versions/036_consolidation_runs.py` | 3 | ☐ |
| `shared/db/models/consolidation.py` | 3 | ☐ |
| `apps/api/src/repositories/consolidation_repo.py` | 3 | ☐ |
| `apps/api/src/services/consolidation_service.py` | 3 | ☐ |
| `agents/templates/live-trader-v1/tools/nightly_consolidation.py` | 3 | ☐ |
| `apps/api/src/routes/consolidation.py` | 3 | ☐ |
| `shared/db/migrations/versions/037_context_sessions.py` | 4 | ☐ |
| `shared/db/models/context_session.py` | 4 | ☐ |
| `shared/context/__init__.py` | 4 | ☐ |
| `shared/context/builder.py` | 4 | ☐ |
| `apps/api/src/routes/brain.py` | 5 | ☐ |

### Modified Files — Backend

| File | Phase | Change Summary |
|---|---|---|
| `apps/api/src/routes/agents.py` | 0 | Add run-backtest endpoint |
| `apps/api/src/main.py` | 1,3,4,5 | Register routers + _ensure_prod_schema checks |
| `shared/db/models/__init__.py` | 1,3,4 | Add new model imports |
| `apps/api/src/services/scheduler.py` | 3 | Add 18:15 ET consolidation job |
| `apps/api/src/services/chat_responder.py` | 4 | Conditional smart context branch |
| `apps/api/src/services/agent_gateway.py` | 4 | Stretch: smart context for signal path |
| `shared/context/builder.py` | 5 | Add cross-agent shared entry tier |

### New Files — Frontend

| File | Phase | Status |
|---|---|---|
| `apps/dashboard/src/components/AgentWikiTab.tsx` | 2 | ☐ |
| `apps/dashboard/src/pages/BrainWikiPage.tsx` | 2 (stub), 5 (full) | ☐ |
| `apps/dashboard/src/components/ConsolidationPanel.tsx` | 3 | ☐ |
| `apps/dashboard/src/components/ContextDebugger.tsx` | 4 | ☐ |

### Modified Files — Frontend

| File | Phase | Change Summary |
|---|---|---|
| `apps/dashboard/src/components/AgentDashboard.tsx` | 0,2,3,4 | Badges, Wiki tab, Brain trigger, Consolidation tab, ContextDebugger |
| `apps/dashboard/src/App.tsx` (or router file) | 5 | Add `/brain/wiki` route |

### New Test Files

| File | Phase |
|---|---|
| `tests/unit/test_backtest_ci.py` | 0 |
| `apps/api/tests/test_routes_improvements.py` | 0 |
| `tests/unit/test_wiki_repo.py` | 1 |
| `apps/api/tests/test_routes_wiki.py` | 1 |
| `tests/unit/test_write_wiki_entry.py` | 2 |
| `tests/unit/test_consolidation_service.py` | 3 |
| `apps/api/tests/test_routes_consolidation.py` | 3 |
| `tests/unit/test_nightly_consolidation_tool.py` | 3 |
| `tests/unit/test_context_builder.py` | 4 |

---

## Appendix B: Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ENABLE_SMART_CONTEXT` | `false` | Enable ContextBuilderService in chat_responder |
| `WIKI_CONTEXT_TOKEN_BUDGET` | `8000` | Token budget for smart context build |
| `RUN_SCHEDULER` | `""` (auto) | Existing: controls scheduler leader election |

---

## Appendix C: Migration Chain

```
... → 033_pm_phase15 → 09b0dd176f5d → 034_add_analyst_agent
                                              ↓
                                    035_agent_wiki
                                              ↓
                                    036_consolidation_runs
                                              ↓
                                    037_context_sessions
```

**Verification command (run after each migration):**
```bash
alembic history --verbose
alembic current
```

---

## Appendix D: Thresholds Reference (Phase 0)

| Metric | Threshold | Borderline (miss by < 10%) |
|---|---|---|
| Sharpe Ratio | ≥ 0.8 | ≥ 0.72 |
| Win Rate | ≥ 53% | ≥ 47.7% |
| Max Drawdown | ≥ -15% (i.e., drawdown no worse than -15%) | ≥ -16.5% |
| Profit Factor | ≥ 1.3 | ≥ 1.17 |
| Minimum Trades | ≥ 15 | ≥ 13 |

**Rules:**
- 0 threshold failures → `status="passed"`, `backtest_passed=True`
- Exactly 1 threshold failure, within borderline range → `status="borderline"`, `backtest_passed=False`, requires human review
- Exactly 1 threshold failure, outside borderline range → `status="failed"`, `backtest_passed=False`
- 2+ threshold failures (regardless of margin) → `status="failed"`, `backtest_passed=False`
