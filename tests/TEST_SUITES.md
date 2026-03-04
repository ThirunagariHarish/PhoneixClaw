# Phoenix v2 — Smoke, E2E, Integration & Feature Test Suites

Generated from [ArchitecturePlan.md](../newdocs/ArchitecturePlan.md), [Milestones.md](../newdocs/Milestones.md), and [ImplementationPlan.md](../newdocs/ImplementationPlan.md).

---

## 1. Smoke Tests (Critical Path)

Run first; must pass before deeper suites.

| ID | Feature | Steps | Expected | Pass |
|----|----------|--------|----------|------|
| S01 | App loads | Open `/` | Redirect to login or dashboard | [ ] |
| S02 | Login page | Open `/login` | Email, Password, Sign in visible | [ ] |
| S03 | Login (valid) | Submit valid creds | Redirect to `/trades` | [ ] |
| S04 | API health | GET `/health` (API) | 200, `{"status":"ok"}` or similar | [ ] |
| S05 | Instances API | GET `/api/v2/instances` (with auth) | 200, array (may be empty) | [ ] |
| S06 | Dashboard nav | After login, click Trades, Positions, Agents | Each route loads, no 500 | [ ] |
| S07 | OpenClaw connect | Register instance 187.124.77.249:18800 (or :41100) | Instance appears in list | [ ] |

---

## 2. End-to-End (E2E) Tests by Feature

### 2.1 Auth (M1.3, M1.4)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E01 | Login page render | Go to `/login` | Heading "Phoenix v2", Email, Password, Sign in | [ ] |
| E02 | Login validation | Submit empty | Validation or error message | [ ] |
| E03 | Login success | Valid email/password | Redirect to `/trades` | [ ] |
| E04 | Logout | Click Logout after login | Redirect to `/login` | [ ] |
| E05 | Protected route | Open `/trades` without login | Redirect to `/login` | [ ] |

### 2.2 Navigation & Shell (M1.4, M1.13)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E06 | Sidebar items | After login, check sidebar | Trades, Positions, Performance, Agents, Connectors, Skills, Market, Admin, Network, Tasks, Settings | [ ] |
| E07 | Route Trades | Click Trades | URL `/trades`, page content | [ ] |
| E08 | Route Positions | Click Positions | URL `/positions` | [ ] |
| E09 | Route Agents | Click Agents | URL `/agents` | [ ] |
| E10 | Route Settings | Click Settings | URL `/settings` | [ ] |
| E11 | Mobile nav | Resize to 375px | Bottom nav or hamburger visible | [ ] |

### 2.3 Trades (M1.10)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E12 | Trades page | Go to `/trades` | Table or empty state, no crash | [ ] |
| E13 | Trades stats | View trades tab | Stats/summary cards or placeholders | [ ] |
| E14 | Trade detail | Click a trade row (if any) | Side panel or detail opens | [ ] |

### 2.4 Positions (M1.10)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E15 | Positions page | Go to `/positions` | Open/closed positions or empty state | [ ] |
| E16 | Summary cards | View positions | Summary metrics visible | [ ] |
| E17 | Close position | If open position, click Close | Modal or confirm | [ ] |

### 2.5 Agents & OpenClaw (M1.11, M1.8)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E18 | Agents list | Go to `/agents` | Agent cards or empty state | [ ] |
| E19 | New Agent wizard | Click New Agent | Dialog, step 1 (name/type) | [ ] |
| E20 | Wizard instance step | Step 2 | Instance dropdown; if no instances, message | [ ] |
| E21 | Create agent (with instance) | Fill name, select instance, Create | Agent created or error | [ ] |
| E22 | Instance in dropdown | After registering OpenClaw instance | Instance appears in Agent wizard | [ ] |
| E23 | Pause/Resume | If agent exists, Pause then Resume | State toggles | [ ] |

### 2.6 OpenClaw Instance (M1.8, §6 Architecture)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E24 | Register instance | POST `/api/v2/instances` { name, host: "187.124.77.249", port: 18800 } | 201, instance in list | [ ] |
| E25 | List instances | GET `/api/v2/instances` | 200, array includes registered instance | [ ] |
| E26 | Network page | Go to `/network` | Instances and agents shown or empty | [ ] |

### 2.7 Connectors (M1.9)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E27 | Connectors page | Go to `/connectors` | List or empty, Add button | [ ] |
| E28 | Add connector | Click Add, fill type/name | Dialog, create or error | [ ] |
| E29 | Test connection | If connector exists, Test | Success/failure message | [ ] |

### 2.8 Skills (M2.x)

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E30 | Skills page | Go to `/skills` | Grid or list, categories | [ ] |
| E31 | Sync skills | Click Sync (if present) | Request sent, no crash | [ ] |

### 2.9 Market, Tasks, Admin, Settings

| ID | Test | Steps | Expected | Pass |
|----|------|--------|----------|------|
| E32 | Market page | Go to `/market` | Indices/chart/placeholders | [ ] |
| E33 | Tasks page | Go to `/tasks` | Kanban or list | [ ] |
| E34 | Admin page | Go to `/admin` | Users/API keys/audit section | [ ] |
| E35 | Settings page | Go to `/settings` | Form or sections | [ ] |
| E36 | Performance | Go to `/performance` | Charts or summary | [ ] |
| E37 | Daily Signals | Go to `/daily-signals` | Pipeline or feed | [ ] |
| E38 | Zero DTE | Go to `/zero-dte` | Gamma/MOC sections | [ ] |
| E39 | Dev dashboard | Go to `/dev` | Status/incidents | [ ] |

---

## 3. Integration Tests (API + DB)

Run against running API (and DB). Mock OpenClaw Bridge where needed.

| ID | Scope | Test | Expected | Pass |
|----|--------|------|----------|------|
| I01 | Auth | POST `/api/v2/auth/register` then login | 201, then 200 + tokens | [ ] |
| I02 | Instances | POST create instance, GET list, GET by id | 201, 200 with item, 200 | [ ] |
| I03 | Agents | POST agent (instance_id from I02), GET list | 201, 200 with agent | [ ] |
| I04 | Trades | GET `/api/v2/trades` | 200, array | [ ] |
| I05 | Positions | GET `/api/v2/positions` | 200, array | [ ] |
| I06 | Connectors | POST connector, GET list | 201, 200 | [ ] |
| I07 | Skills | GET `/api/v2/skills` | 200, array | [ ] |
| I08 | Tasks | GET `/api/v2/tasks`, POST task, PATCH move | 200, 201, 200 | [ ] |

---

## 4. Feature-Based Test Matrix (by Milestone)

| Milestone | Feature | Smoke | E2E | Integration |
|-----------|---------|-------|-----|-------------|
| M1.3 | Auth | S02,S03 | E01–E05 | I01 |
| M1.4 | Dashboard shell | S01,S06 | E06–E11 | — |
| M1.8 | First OpenClaw instance | S07 | E22,E24–E26 | I02 |
| M1.9 | Connectors | — | E27–E29 | I06 |
| M1.10 | Trades & Positions | — | E12–E17 | I04,I05 |
| M1.11 | Agent CRUD | — | E18–E23 | I03 |
| M1.12 | Execution / risk | — | (API only) | — |
| M1.13 | Mobile | — | E11 | — |
| M2.x | Skills, Tasks, etc. | — | E30–E39 | I07,I08 |

---

## 5. OpenClaw Remote Instance (187.124.77.249)

- **OpenClaw UI**: http://187.124.77.249:41100/ (login page).
- **Bridge API** (for Phoenix): Usually on port **18800** on the same host. Some setups expose Bridge on **41100** (same as UI); try both if one fails.

**Register via script (after login, set PHOENIX_TOKEN):**
```bash
# Get token: login at http://localhost:3000/login, then from browser DevTools → Application → Local Storage copy phoenix-v2-token
export PHOENIX_TOKEN="<paste_token>"
export OPENCLAW_HOST=187.124.77.249
export OPENCLAW_PORT=18800   # or 41100 if Bridge is on same port as UI
python scripts/register_openclaw_instance.py
```

**Register via API (with JWT):**
```bash
curl -X POST http://localhost:8011/api/v2/instances \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT>" \
  -d '{"name":"OpenClaw-Remote","host":"187.124.77.249","port":18800,"role":"general","node_type":"vps"}'
```

**Mocking**: For tests without a live OpenClaw, use a mock Bridge (e.g. stub HTTP server returning `/health`, `/agents`) or in-memory instance; ensure the app can still "connect" (register instance and show it in the dashboard).

---

## 6. Running the Suites

- **Smoke**: Manual browser + `curl` for API; or pytest E2E for S01–S06.
- **E2E**: Playwright (pytest) in `tests/e2e/`; or follow TEST_SUITES checklist in browser.
- **Integration**: `pytest apps/api/tests/integration/` with DB + API up; mock Bridge in conftest if needed.

Run recursively: fix failures, re-run until all checkboxes pass, then deploy.
