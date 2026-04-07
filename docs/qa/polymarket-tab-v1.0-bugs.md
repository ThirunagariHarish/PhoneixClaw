# Polymarket Tab v1.0 — QA Bug Report

QA by: Quill
Date: 2026-04-07
Scope: Static QA + test re-run against PRD `docs/prd/polymarket-tab.md` v1.0 features (F1, F2, F3, F9, F10, F12, F13).

---

## BUG-1: Promotion gate does not enforce "walk-forward backtest attached, dated <=30 days"

**Severity:** P1 (promotion gate is section 5's hard contract; a gate rule is not enforced)
**Feature:** Promotion Gate / F10 / S10.2
**PRD reference:** `docs/prd/polymarket-tab.md` section 5 "Paper -> Live Promotion Gate", rule 1:
> "A walk-forward backtest (F10) is attached, dated within the last 30 days, with Brier <= user-set threshold and Sharpe >= user-set threshold."

**Steps:**
1. Read `shared/polymarket/promotion_gate.py`.
2. Grep for `backtest`, `walk_forward`, `attached`, `30`, `BacktestRun`.

**Expected:** Gate evaluation loads the most recent PM walk-forward backtest run for the strategy, verifies it exists, verifies `created_at >= now - 30d`, and verifies its Brier/Sharpe against `max_brier`/`min_sharpe`. An absent or stale backtest is a gate failure written to the audit log.

**Actual:** `promotion_gate.py` evaluates `paper_soak_days`, `brier`, `sharpe`, and `f9_coverage` — the last three against a `calibration` record, not a backtest artifact. There is **no check that a backtest artifact is attached or dated**. A strategy with live calibration numbers but zero backtest history could pass the gate.

**Evidence:** `shared/polymarket/promotion_gate.py` — no occurrence of `backtest`, `walk_forward`, `attached`, or a 30-day recency check anywhere in the file. `services/backtest-runner/src/loaders/polymarket_loader.py` exists (F10 data loader) so the backing capability is present but unwired into the gate.

**Suspected fix location:** `shared/polymarket/promotion_gate.py` — add a `backtest_attached` rule that queries the most recent PM walk-forward `BacktestRun` for the strategy and asserts recency + thresholds.

**File:line:** `shared/polymarket/promotion_gate.py:1-413` (whole module — rule is missing, not broken).

---

## BUG-2: Markets-tab filters are not URL-shareable

**Severity:** P3 (AC miss on a convenience requirement)
**Feature:** F2 / S2.2
**PRD reference:** Section 4, F2 S2.2:
> "AC: filters persist per user; URL-shareable."

**Steps:**
1. Read `apps/dashboard/src/pages/polymarket/index.tsx`.
2. Grep for `useSearchParams`, `URLSearchParams`, `window.location`.

**Expected:** Category / min-volume / tradeable-only filter state is reflected in the URL query string (`?cat=...&min_volume=...`) so a link can be shared and the Markets tab rehydrates from the URL on load. Ideally also persisted per-user.

**Actual:** Filter state is held only in `useState` (`category`, `minVolume`, `tradeableOnly`). No reads or writes to the URL; no localStorage or user-scoped persistence. Reloading the page or sharing the URL loses the filter.

**Evidence:** `apps/dashboard/src/pages/polymarket/index.tsx` — zero matches for `useSearchParams`, `URLSearchParams`, or `window.location`. Filter state at lines ~445-456.

**Suspected fix location:** `apps/dashboard/src/pages/polymarket/index.tsx` MarketsTab component (~L440-540) — bind filter state to `useSearchParams` from react-router.

**File:line:** `apps/dashboard/src/pages/polymarket/index.tsx:445`
