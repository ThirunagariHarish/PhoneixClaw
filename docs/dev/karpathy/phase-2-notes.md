# Phase 2: Agent Knowledge Wiki — Agent Tool + Frontend Tab
## Implementation Notes

**Phase:** 2  
**Date:** 2025-01-15  
**Author:** Devin (implementation)

---

## Summary

Implemented the Agent Knowledge Wiki feature — an agent tool for writing/querying knowledge entries and a full frontend tab + Brain Wiki page for browsing them.

---

## Files Created

### Python (Agent Tool)
| File | Purpose |
|------|---------|
| `agents/templates/live-trader-v1/tools/write_wiki_entry.py` | Agent tool with `write_wiki_entry`, `query_wiki`, `get_wiki_summary` async functions + argparse CLI |
| `tests/unit/test_write_wiki_entry.py` | 25 unit tests covering happy path, default `is_shared` logic, error handling |

### Frontend (React/TypeScript)
| File | Purpose |
|------|---------|
| `apps/dashboard/src/components/AgentWikiTab.tsx` | 3-pane wiki tab (category sidebar, entry list, detail panel) with add/edit/delete modals |
| `apps/dashboard/src/pages/BrainWikiPage.tsx` | Read-only Phoenix Brain page showing all `is_shared=true` entries across agents |

### Modified
| File | Change |
|------|--------|
| `apps/dashboard/src/pages/AgentDashboard.tsx` | Added wiki tab trigger + `<TabsContent>` in `LiveSection`, changed `grid-cols-10` → `grid-cols-11`, imported `AgentWikiTab` |
| `apps/dashboard/src/App.tsx` | Added `BrainWikiPage` import + `<Route path="brain/wiki">` |
| `apps/dashboard/src/components/layout/AppShell.tsx` | Added `Brain` to lucide-react imports; added Phoenix Brain nav item to Agents section |

---

## Design Decisions & Deviations

1. **`is_shared` defaults per category** — `TRADE_OBSERVATION` and `GENERAL` default to `False`; all 6 other categories (`MARKET_PATTERN`, `STRATEGY_LEARNING`, `RISK_NOTE`, `SECTOR_INSIGHT`, `INDICATOR_NOTE`, `EARNINGS_PLAYBOOK`) default to `True`. This matches the spec intent (trade-level data stays private; pattern/strategy learnings are community knowledge).

2. **Export dropdown** — Implemented as a CSS `group-hover` dropdown rather than Radix `DropdownMenu` to keep the component self-contained without additional imports. This is visually simpler but slightly less accessible. No risk — the button is clearly labeled.

3. **Category counts in sidebar** — The counts shown in the sidebar are derived from the current page's entry list, not a dedicated `/wiki/summary` endpoint call. This avoids an extra API call but means counts reflect filtered results. If a dedicated summary endpoint is available, a `useQuery` call to `get_wiki_summary` should be added.

4. **Debounced search** — Uses `setTimeout` inside the handler rather than a custom `useDebounce` hook (no such hook exists in the codebase). The cleanup function is returned but the `handleSearchChange` is memoized with `useCallback`. Functionally equivalent to a hook.

5. **`WikiCategory` type alias** — Removed the unused `WikiCategory` type alias during TypeScript fixing (it was derived from `typeof ALL_CATEGORIES[number]` but never used in function signatures — `string` is used everywhere for flexibility with server-returned values).

---

## Tests Added

**File:** `tests/unit/test_write_wiki_entry.py`

| Class | Tests | What's covered |
|-------|-------|----------------|
| `TestDefaultIsShared` | 9 | All 8 categories + case-insensitivity |
| `TestWriteWikiEntry` | 8 | Happy path, correct endpoint, `is_shared` defaults, override, auth header, 4xx/5xx errors |
| `TestQueryWiki` | 4 | Happy path, category filter, no-filter, 4xx error |
| `TestGetWikiSummary` | 4 | Happy path, categories CSV, no-filter, 4xx error |

**Result:** 25/25 passed.

---

## Self-Check Results

| Check | Result |
|-------|--------|
| `make lint-fix` / ruff on `write_wiki_entry.py` | ✅ CLEAN (0 errors after en-dash → hyphen fix) |
| `npx tsc --noEmit` — new files | ✅ 0 new errors |
| `npx tsc --noEmit` — pre-existing errors | 10 pre-existing errors in `AgentDashboard.tsx` (lines 900-966), `Backtests.tsx`, `Connectors.tsx`, `Login.tsx`, `Tasks.tsx`, `types/index.ts` — NOT introduced by Phase 2 |
| Python unit tests | ✅ 25/25 passed |

---

## Open Risks

1. **Backend endpoints not yet implemented** — Phase 2 is frontend + tool only. The API endpoints (`POST /api/v2/agents/{id}/wiki`, `GET /api/v2/agents/{id}/wiki`, `PATCH`, `DELETE`, `GET /versions`, `GET /api/v2/brain/wiki`, `GET /wiki/export`) need to be implemented in Phase 1 (backend). The frontend will gracefully handle 404/500 errors through TanStack Query's error state.

2. **`/wiki/summary` endpoint** — The `get_wiki_summary` Python function calls `GET /api/v2/agents/{id}/wiki/summary`. If this endpoint isn't implemented backend-side, the category counts in the sidebar will fall back to page-level counts (current behavior).

3. **Export auth** — The export uses a direct `<a href>` click with the API base URL. If the backend requires auth headers for the export endpoint, this approach won't work — it would need to be changed to a `blob` fetch with the axios interceptor. Flag for Cortex review.

4. **Pre-existing TypeScript errors** — 10 pre-existing TS errors in unrelated files should be addressed in a separate cleanup PR to avoid accumulating tech debt.
