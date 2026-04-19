# Phoenix v2 — Smoke, E2E, Integration & Feature Test Suites

Generated from [ArchitecturePlan.md](../newdocs/ArchitecturePlan.md), [Milestones.md](../newdocs/Milestones.md), and [ImplementationPlan.md](../newdocs/ImplementationPlan.md).  
**See also:** [manual/UI_TEST_CASES.md](manual/UI_TEST_CASES.md) (full UI test cases) and [manual/MASTER_MANUAL_RUN.md](manual/MASTER_MANUAL_RUN.md) (combined run order).

---

## 1. Smoke Tests (Critical Path)

Run first; must pass before deeper suites.

| ID | Feature | Steps | Expected | Pass |
|----|----------|--------|----------|------|
| S01 | App loads | Open `/` | Redirect to login or dashboard | [x] |
| S02 | Login page | Open `/login` | Email, Password, Sign in visible | [x] |
| S03 | Login (valid) | Submit valid creds | Redirect to `/trades` | [x] |
| S04 | API health | GET `/health` (API) | 200, `{"status":"ok"}` or similar | [x] |
| S05 | Instances API | GET `/api/v2/instances` (with auth) | 200, array (may be empty) | [x] |
| S06 | Dashboard nav | After login, click Trades, Positions, Agents | Each route loads, no 500 | [x] |

---

## 2. End-to-End (E2E) Tests by Feature

### 2.1 Auth (M1.3, M1.4)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E01 | Login page render | Go to `/login` | Heading "Phoenix v2", Email, Password, Sign in | [x] |
| E02 | Login validation | Submit empty | Validation or error message | [x] |
| E03 | Login success | Valid email/password | Redirect to `/trades` | [x] |
| E04 | Logout | Click Logout after login | Redirect to `/login` | [x] |
| E05 | Protected route | Open `/trades` without login | Redirect to `/login` | [x] |

### 2.2 Navigation & Shell (M1.4, M1.13)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E06 | Sidebar items | After login, check sidebar | Trades, Positions, Performance, Agents, Connectors, Skills, Market, Admin, Network, Tasks, Settings | [x] |
| E07 | Route Trades | Click Trades | URL `/trades`, page content | [x] |
| E08 | Route Positions | Click Positions | URL `/positions` | [x] |
| E09 | Route Agents | Click Agents | URL `/agents` | [x] |
| E10 | Route Settings | Click Settings | URL `/settings` | [x] |
| E11 | Mobile nav | Resize to 375px | Bottom nav or hamburger visible | [x] |

### 2.3 Trades (M1.10)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E12 | Trades page | Go to `/trades` | Table or empty state, no crash | [x] |
| E13 | Trades stats | View trades tab | Stats/summary cards or placeholders | [x] |
| E14 | Trade detail | Click a trade row (if any) | Side panel or detail opens | [x] |

### 2.4 Positions (M1.10)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E15 | Positions page | Go to `/positions` | Open/closed positions or empty state | [x] |
| E16 | Summary cards | View positions | Summary metrics visible | [x] |
| E17 | Close position | If open position, click Close | Modal or confirm | [x] |

### 2.5 Agents (M1.11, M1.8)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E18 | Agents list | Go to `/agents` | Agent cards or empty state | [x] |
| E19 | New Agent wizard | Click New Agent | Dialog, step 1 (name/type) | [x] |
| E20 | Wizard instance step | Step 2 | Instance dropdown; if no instances, message | [x] |
| E21 | Create agent (with instance) | Fill name, select instance, Create | Agent created or error | [x] |
| E22 | Instance in dropdown | After registering agent instance | Instance appears in Agent wizard | [x] |
| E23 | Pause/Resume | If agent exists, Pause then Resume | State toggles | [x] |

### 2.6 Agent Instance (M1.8, §6 Architecture)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E24 | Register instance | POST `/api/v2/instances` { name, host, port } | 201, instance in list | [x] |
| E25 | List instances | GET `/api/v2/instances` | 200, array includes registered instance | [x] |
| E26 | Network page | Go to `/network` | Instances and agents shown or empty | [x] |

### 2.7 Connectors (M1.9)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E27 | Connectors page | Go to `/connectors` | List or empty, Add button | [x] |
| E28 | Add connector | Click Add, fill type/name | Dialog, create or error | [x] |
| E29 | Test connection | If connector exists, Test | Success/failure message | [x] |

### 2.8 Skills (M2.x)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E30 | Skills page | Go to `/skills` | Grid or list, categories | [x] |
| E31 | Sync skills | Click Sync (if present) | Request sent, no crash | [x] |

### 2.9 Market, Tasks, Admin, Settings

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E32 | Market page | Go to `/market` | Indices/chart/placeholders | [x] |
| E33 | Tasks page | Go to `/tasks` | Kanban or list | [x] |
| E34 | Admin page | Go to `/admin` | Users/API keys/audit section | [x] |
| E35 | Settings page | Go to `/settings` | Form or sections | [x] |
| E36 | Performance | Go to `/performance` | Charts or summary | [x] |
| E37 | Daily Signals | Go to `/daily-signals` | Pipeline or feed | [x] |
| E38 | Zero DTE | Go to `/zero-dte` | Gamma/MOC sections | [x] |
| E39 | Dev dashboard | Go to `/dev` | Status/incidents | [x] |

---

## 3. Integration Tests (API + DB)

Run against running API (and DB).

| ID | Scope | Test | Expected | Pass |
|----|--------|------|----------|------|
| I01 | Auth | POST `/auth/register` then login | 201, then 200 + tokens | [x] |
| I02 | Instances | POST create instance, GET list, GET by id | 201, 200 with item, 200 | [x] |
| I03 | Agents | POST agent (instance_id from I02), GET list | 201, 200 with agent | [x] |
| I04 | Trades | GET `/api/v2/trades` | 200, array | [x] |
| I05 | Positions | GET `/api/v2/positions` | 200, array | [x] |
| I06 | Connectors | POST connector, GET list | 201, 200 | [x] |
| I07 | Skills | GET `/api/v2/skills` | 200, array | [x] |
| I08 | Tasks | GET `/api/v2/tasks`, POST task, PATCH move | 200, 201, 200 | [x] |

---

## 4. Feature-Based Test Matrix (by Milestone)

| Milestone | Feature | Smoke | E2E | Integration |
|-----------|---------|-------|-----|-------------|
| M1.3 | Auth | S02,S03 | E01–E05 | I01 |
| M1.4 | Dashboard shell | S01,S06 | E06–E11 | — |
| M1.8 | First agent instance | — | E22,E24–E26 | I02 |
| M1.9 | Connectors | — | E27–E29 | I06 |
| M1.10 | Trades & Positions | — | E12–E17 | I04,I05 |
| M1.11 | Agent CRUD | — | E18–E23 | I03 |
| M1.12 | Execution / risk | — | (API only) | — |
| M1.13 | Mobile | — | E11 | — |
| M2.x | Skills, Tasks, etc. | — | E30–E39 | I07,I08 |

---

## 5. Agent Instance Registration

**Register via API (with JWT):**
```bash
curl -X POST http://localhost:8011/api/v2/instances \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT>" \
  -d '{"name":"Agent-Instance","host":"<host>","port":<port>,"role":"general","node_type":"vps"}'
```

---

## 6. Running the Suites

- **Auth API**: Register, login, and me live under `/auth` (e.g. `POST /auth/register`, `POST /auth/login`, `GET /auth/me`), not under `/api/v2/auth`.
- **Smoke**: Manual browser + `curl` for API; or pytest E2E for S01–S06.
- **E2E**: Playwright (pytest) in `tests/e2e/`; or follow TEST_SUITES checklist in browser.
- **Integration**: `pytest apps/api/tests/integration/` with DB + API up; mock Bridge in conftest if needed.

Run recursively: fix failures, re-run until all checkboxes pass, then deploy.
