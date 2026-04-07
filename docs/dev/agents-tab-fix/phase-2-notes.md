# Phase 2 Implementation Notes — Frontend Fixes

**Phase:** 2  
**Feature:** Agents Tab Bug-Fix  
**Commit:** `83c8f6c`  
**Date:** 2025-01-28  
**Author:** Devin  

---

## What Changed

### 2.1 – `canAdvance()` wizard guard fix (`Agents.tsx`)

**Before (bug):**
```typescript
return form.connector_ids.length > 0   // hard-blocked non-trading types
```

**After (fix):**
```typescript
return true   // non-trading types only need a name
```

The wizard `canAdvance(step 0)` logic was extracted into an exported pure function `computeCanAdvance()` so it can be unit-tested without rendering the full component. The component's internal `canAdvance` now delegates to this function:
```typescript
const canAdvance = (step: number): boolean =>
  computeCanAdvance(step, form.name, form.type, form.connector_ids, form.selected_channel)
```

The `trading` type guard is **unchanged** — it still requires exactly 1 connector + a selected channel (AC1.1.3 preserved).

### 2.2 – `error_message` field in `AgentData` type

Added `error_message?: string | null` to the `AgentData` interface (now exported).

### 2.3 – `ERROR` status in `STATUS_CONFIG`

Added `ERROR` entry to the `STATUS_CONFIG` record:
```typescript
ERROR: { color: 'text-red-600 dark:text-red-400', bgColor: 'bg-red-500/10', borderColor: 'border-red-500/30', label: 'Error' }
```

`getStatusConfig()` already has a fallback (`?? STATUS_CONFIG.CREATED`) but the explicit entry ensures the correct red styling without hitting the fallback.

### 2.4 – Error banner on `AgentCard`

When `agent.status === 'ERROR' && agent.error_message`, a red alert banner is rendered below the status badge containing:
- `AlertCircle` icon  
- The `error_message` text (word-wrapped)  
- A disabled `Retry (contact admin)` button with tooltip per AC1.2.3 scope note

### 2.5 – Error panel in `SidePanel`

Added an `ERROR` section to the agent detail side-panel. When `selected.status === 'ERROR'`, shows a red panel with "Agent Error" heading and `selected.error_message` (falls back to a generic message if null).

### 2.6 – Action buttons for `ERROR` agents

Action buttons already work correctly for `ERROR` without changes:
- Pause button only shows for `RUNNING` — not shown for `ERROR` ✓
- Resume button only shows for `PAUSED` — not shown for `ERROR` ✓  
- Delete button is always visible — correct for `ERROR` ✓
- `isLocked` only applies to `BACKTESTING` — `ERROR` agents can be clicked/navigated ✓

---

## Files Touched

| File | Change |
|------|--------|
| `apps/dashboard/src/pages/Agents.tsx` | All Phase 2 logic changes |
| `apps/dashboard/tests/unit/Agents.canAdvance.test.tsx` | New — 8 unit tests |

---

## Tests Added

**File:** `apps/dashboard/tests/unit/Agents.canAdvance.test.tsx`

| Test | Assertion | Result |
|------|-----------|--------|
| `canAdvance_step0_trend_no_connector` | `computeCanAdvance(0, name, 'trend', [], null) === true` | ✅ Pass |
| `canAdvance_step0_trading_no_connector` | `computeCanAdvance(0, name, 'trading', [], null) === false` | ✅ Pass |
| `canAdvance_step0_trading_with_connector_and_channel` | `computeCanAdvance(0, name, 'trading', ['c'], ch) === true` | ✅ Pass |
| `canAdvance_step0_empty_name` | Returns `false` for empty/whitespace name for any type | ✅ Pass |
| `canAdvance_step0_sentiment_no_connector` | `computeCanAdvance(0, name, 'sentiment', [], null) === true` | ✅ Pass |
| `agent_card_renders_error_message` | Error banner visible when `status=ERROR` + `error_message` set | ✅ Pass |
| `agent_card_no_error_message_when_running` | No banner when `status=RUNNING` | ✅ Pass |
| `agent_card_no_error_banner_when_error_message_null` | No banner text when `error_message=null` | ✅ Pass |

**Existing test regression:** `app.test.tsx > renders without crashing` fails due to a pre-existing `localStorage` issue in `ThemeContext.tsx` — confirmed present on the unmodified tree before Phase 2. This is **not** a regression introduced by Phase 2.

---

## Deviations from Spec

| Spec location | Spec says | What was done | Reason |
|---------------|-----------|---------------|--------|
| Tech plan §2.3: "Action buttons: ERROR agents show Delete only" | Show only Delete, not Start/Approve/Stop | No change needed | The existing conditional rendering (`agent.status === 'RUNNING'` for Pause, `agent.status === 'PAUSED'` for Resume) already excludes ERROR agents from those buttons. The Delete button is always shown. |
| Tech plan §Phase 2 tests path: `src/__tests__/` | `apps/dashboard/src/__tests__/` | `apps/dashboard/tests/unit/` | vitest config `include` pattern is `tests/**/*.{test,spec}.{ts,tsx}` — the `src/__tests__` path is outside the include glob and tests would not run. |

---

## Open Risks

1. **`app.test.tsx` pre-existing failure** — the existing smoke test fails on `localStorage.getItem is not a function` in `ThemeContext.tsx`. This should be fixed in a follow-up by adding `localStorage` mock to `setup.ts`. Not in Phase 2 scope.
2. **Retry endpoint** — AC1.2.3 requires a functional retry action. Phase 2 delivers a disabled placeholder. A follow-up ticket is needed to implement `POST /api/v2/agents/{id}/retry` and wire up the button.

---

## Self-Check Results

| Check | Status |
|-------|--------|
| `npx tsc --noEmit` — zero errors in `Agents.tsx` | ✅ |
| All 8 new unit tests pass | ✅ |
| Pre-existing `app.test.tsx` failure unchanged (not a regression) | ✅ |
| `canAdvance(0)` returns `true` for `type='trend'` with no connector and valid name | ✅ |
| `canAdvance(0)` returns `false` for `type='trading'` with no connector | ✅ |
| Agent card shows red error banner when `status === 'ERROR'` and `error_message` set | ✅ |
| `ERROR` status has distinct red styling in `STATUS_CONFIG` | ✅ |
| Backend files untouched | ✅ |
| Wizard layout unchanged (3 steps, same labels) | ✅ |
