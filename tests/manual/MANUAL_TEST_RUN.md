# Manual Test Run Report — TEST_SUITES.md

**Date:** 2026-03-03  
**Tester:** Automated (browser + curl)  
**Dashboard:** http://localhost:3000 (running)  
**API:** http://localhost:8011 — **not running** (connection refused)

---

## Prerequisites

- Dashboard dev server was running at `http://localhost:3000`.
- API was **not** running; Postgres/Redis were not verified (docker-compose failed: port 5432 already in use).

---

## 1. Smoke Tests (TEST_SUITES.md §1)

| ID   | Feature         | Result | Notes |
|------|-----------------|--------|--------|
| S01  | App loads       | **PASS** | Open `/` → showed login page (redirect to login). |
| S02  | Login page      | **PASS** | Email, Password, Sign in, Sign up visible. |
| S03  | Login (valid)   | **BLOCKED** | API down; cannot register or login. |
| S04  | API health      | **FAIL** | `GET http://localhost:8011/health` — connection refused. |
| S05  | Instances API   | **BLOCKED** | Requires API + auth. |
| S06  | Dashboard nav   | **BLOCKED** | Requires successful login. |

---

## 2. E2E by Feature

### 2.1 Auth (E01–E05)

| ID   | Test              | Result | Notes |
|------|-------------------|--------|--------|
| E01  | Login page render | **PASS** | "Phoenix v2", Email, Password, Sign in, Sign up present. |
| E02  | Login validation  | **PASS** | Submit empty → form validation (no submit). |
| E03  | Login success     | **BLOCKED** | API down; no valid login. |
| E04  | Logout            | **BLOCKED** | Requires login first. |
| E05  | Protected route   | **PASS** | `/trades` and `/agents` unauthenticated → redirect to login. |

### 2.2 Navigation & Shell (E06–E11)

| ID   | Test         | Result | Notes |
|------|--------------|--------|--------|
| E06–E10 | Sidebar / routes | **BLOCKED** | Requires login. |
| E11  | Mobile nav   | **NOT RUN** | Requires login to see sidebar; viewport 375px tested on login/register — layout usable. |

### 2.3 Register & Sign-in link

| Check | Result | Notes |
|-------|--------|--------|
| Register page | **PASS** | `/register` — Name, Email, Password, "Create account", "Already have an account? Sign in". |
| Sign up link on login | **PASS** | "Don't have an account? Sign up" → `/register`. |
| Register submit (API down) | **PASS** | UI shows "Registration failed" (expected when API unavailable). |

### 2.4 Trades, Positions, Agents, etc. (E12–E39)

All **BLOCKED** — require authenticated session and API.

---

## 3. Integration Tests (I01–I08)

All **BLOCKED** — require running API (and DB) at `http://localhost:8011`.

---

## 4. Summary

| Category     | Pass | Fail | Blocked |
|-------------|------|------|---------|
| Smoke       | 2    | 1    | 4       |
| E2E Auth    | 3    | 0    | 2       |
| E2E Nav     | 0    | 0    | 5       |
| E2E Other   | 0    | 0    | 28      |
| Integration | 0    | 0    | 8       |

**To complete full manual run:**

1. Start API: from repo root, with `DATABASE_URL` and optional `REDIS_URL` set (e.g. `export DATABASE_URL=postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader`), run `python -m apps.api.src.main` or `uvicorn apps.api.src.main:app --host 0.0.0.0 --port 8011` (with `PYTHONPATH=.`).
2. Ensure DB migrations are applied so `/auth/register` and `/auth/login` work.
3. Re-run Smoke S03–S07, E2E E03–E39, and Integration I01–I08; then mark checkboxes in [tests/TEST_SUITES.md](../TEST_SUITES.md).

---

## 5. How to Run This Again

1. Start dashboard: `cd apps/dashboard && npm run dev` (port 3000).
2. Start API: `cd <repo_root> && PYTHONPATH=. python -m uvicorn apps.api.src.main:app --host 0.0.0.0 --port 8011` (with Postgres/Redis and `.env` configured).
3. Use [tests/manual/MANUAL_TEST_PLAN.md](MANUAL_TEST_PLAN.md) and [tests/TEST_SUITES.md](../TEST_SUITES.md) as checklists; run in browser and curl, then update this report or the Pass column in TEST_SUITES.md.
