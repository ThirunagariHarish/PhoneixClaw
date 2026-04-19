# Master Manual Test Run — Phoenix Claw

Combined run order for manual testing: Smoke (TEST_SUITES.md), E2E (TEST_SUITES.md), UI test cases (UI_TEST_CASES.md), and optional Integration (TEST_SUITES.md). Run in a browser with app and API up.

---

## Preconditions

- [ ] App running (e.g. `http://localhost:3000`)
- [ ] API running (e.g. `http://localhost:8011`) for auth and data
- [ ] Test user available (register at `/register` or use existing)

---

## Phase 1 — Smoke (Critical path)

**Source:** [TEST_SUITES.md](../TEST_SUITES.md) § 1.

| ID | Feature | Pass |
|----|---------|------|
| S01 | App loads: Open `/` → redirect to login or dashboard | [ ] |
| S02 | Login page: Open `/login` → Email, Password, Sign in visible | [ ] |
| S03 | Login (valid): Submit valid creds → redirect to `/trades` | [ ] |
| S04 | API health: GET `/health` (API) → 200, status ok | [ ] |
| S05 | Instances API: GET `/api/v2/instances` with auth → 200, array | [ ] |
| S06 | Dashboard nav: After login, click Trades, Positions, Agents → each loads | [ ] |

---

## Phase 2 — E2E (Auth, shell, features)

**Source:** [TEST_SUITES.md](../TEST_SUITES.md) § 2.

### Auth (E01–E05)

| ID | Test | Pass |
|----|------|------|
| E01 | Login page: heading "Phoenix Claw", Email, Password, Sign in | [ ] |
| E02 | Login validation: submit empty → validation or error | [ ] |
| E03 | Login success: valid creds → redirect to `/trades` | [ ] |
| E04 | Logout: click Logout → redirect to `/login` | [ ] |
| E05 | Protected route: open `/trades` without login → redirect to login | [ ] |

### Navigation & shell (E06–E11)

| ID | Test | Pass |
|----|------|------|
| E06 | Sidebar: Trades, Positions, Performance, Agents, Connectors, Skills, Market, Admin, Network, Tasks, Settings | [ ] |
| E07 | Route Trades → URL `/trades`, content | [ ] |
| E08 | Route Positions → URL `/positions` | [ ] |
| E09 | Route Agents → URL `/agents` | [ ] |
| E10 | Route Settings → URL `/settings` | [ ] |
| E11 | Mobile: 375px → bottom nav or hamburger visible | [ ] |

### Trades, Positions, Agents, etc. (E12–E39)

| ID | Test | Pass |
|----|------|------|
| E12–E17 | Trades page, stats, detail; Positions page, summary, close | [ ] |
| E18–E23 | Agents list, wizard, instance step, create, Pause/Resume | [ ] |
| E24–E26 | Register instance, list instances, Network page | [ ] |
| E27–E29 | Connectors page, Add connector, Test connection | [ ] |
| E30–E31 | Skills page, Sync skills | [ ] |
| E32–E39 | Market, Tasks, Admin, Settings, Performance, Daily Signals, Zero DTE, Dev | [ ] |

---

## Phase 3 — UI test cases (full UI)

**Source:** [UI_TEST_CASES.md](UI_TEST_CASES.md).

Run sections in order: U01 → U02 → … → U10. Mark Pass in UI_TEST_CASES.md.

| Section | Description | Count |
|---------|-------------|-------|
| U01 | Branding | 6 |
| U02 | Shell & navigation | 11 |
| U03 | Page headers | 5 |
| U04 | Global components | 8 |
| U05 | Forms & dialogs | 8 |
| U06 | All pages load | 20 |
| U07 | Responsive | 5 |
| U08 | Theme | 3 |
| U09 | Empty & error | 4 |
| U10 | Accessibility | 4 |

**Total:** 74 UI cases. Use [UI_TEST_CASES.md](UI_TEST_CASES.md) for steps and expected results.

---

## Phase 4 — Integration (optional)

**Source:** [TEST_SUITES.md](../TEST_SUITES.md) § 3.

Run with API + DB up; use curl or pytest.

| ID | Scope | Pass |
|----|--------|------|
| I01 | Auth: POST register, login | [ ] |
| I02 | Instances: POST, GET list, GET by id | [ ] |
| I03 | Agents: POST, GET list | [ ] |
| I04 | Trades: GET | [ ] |
| I05 | Positions: GET | [ ] |
| I06 | Connectors: POST, GET | [ ] |
| I07 | Skills: GET | [ ] |
| I08 | Tasks: GET, POST, PATCH move | [ ] |

---

## Run order summary

1. **Phase 1** — Smoke (S01–S07). Must pass before deeper testing.
2. **Phase 2** — E2E (E01–E39). Auth and shell first, then feature pages.
3. **Phase 3** — UI (U01–U10). Full UI checklist in UI_TEST_CASES.md.
4. **Phase 4** — Integration (I01–I08). Optional; can run in parallel or after UI.

For a quick regression: Phase 1 + Phase 2 (E01–E11) + Phase 3 (U01–U04, U06.1–U06.5).

**Sign-off:** _________________ Date: _______
