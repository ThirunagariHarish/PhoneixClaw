# Phase 15.7 Implementation Notes

**Phase:** 15.7 — Dashboard UI  
**Date:** 2025-04-07  
**Author:** Devin (dev)  
**Status:** Complete — pending Cortex review

---

## Summary

Implemented all Phase 15.7 Dashboard UI deliverables for the Prediction Markets feature. Added
`VenueSelectorPills`, `TopBetsPanel`, `ChatTab` (8th tab), and `LogsTab` (9th tab); updated
`JurisdictionBanner` styling and copy; renamed the nav label; and wired the new components into
the existing Polymarket page.

---

## Files Changed

### Modified
| File | Change |
|------|--------|
| `apps/dashboard/src/components/layout/AppShell.tsx` | Renamed nav label `'Polymarket'` → `'Prediction Markets'` |
| `apps/dashboard/src/pages/polymarket/index.tsx` | Updated imports, `JurisdictionBanner`, `MarketsTab`, page title, tab list |

### Created
| File | Purpose |
|------|---------|
| `apps/dashboard/src/pages/polymarket/VenueSelectorPills.tsx` | Three-pill venue segmented control with health status dots |
| `apps/dashboard/src/pages/polymarket/TopBetsPanel.tsx` | Card grid of top bets with probability bars, AI reasoning expander, Place Bet modal |
| `apps/dashboard/src/pages/polymarket/ChatTab.tsx` | SSE-streaming chat interface with history, context selector, and clear action |
| `apps/dashboard/src/pages/polymarket/LogsTab.tsx` | Agent health cards, activity log table, and research log section |

---

## Detailed Changes

### 1. Nav label rename (`AppShell.tsx`)
Changed the `label` field on the `/polymarket` nav item from `'Polymarket'` to
`'Prediction Markets'`.

### 2. `JurisdictionBanner` update (`index.tsx`)
- Swapped `AlertTriangle` (yellow) import for `Info` (blue) from `lucide-react`.
- Border: `border-yellow-500/40` → `border-blue-500/40`
- Background: `bg-yellow-500/10` → `bg-blue-500/10`
- Icon: `text-yellow-400` → `text-blue-400`
- Heading: `text-yellow-200` → `text-blue-200` with updated copy.
- Body copy updated per F15-E: "Prediction Markets are available in the US via Robinhood (primary)
  and Polymarket (secondary). All trades in this tab are paper mode only."
- Attestation flow (`Dialog`) preserved unchanged.

### 3. `VenueSelectorPills` (`VenueSelectorPills.tsx`)
- Three pill buttons: "Robinhood Predictions" | "Polymarket" | "All Venues".
- Selected pill gets `bg-background shadow-sm` styling; unselected shows muted text.
- Fetches `GET /api/polymarket/agents/health` every 30s; maps venue name → `healthy/degraded/dead`
  and renders a coloured dot (green/yellow/red) next to each pill.
- Exports `VenueId` type (`'robinhood' | 'polymarket' | 'all'`).

### 4. `TopBetsPanel` + `TopBetCard` (`TopBetsPanel.tsx`)
- Fetches `GET /api/polymarket/top-bets` with optional `venue` param, polling every 60s.
- 3-column responsive card grid.
- Loading skeleton: 3 animated pulse cards.
- Empty state: dashed border card with informational message.
- `TopBetCard`:
  - Question title + venue badge + reference_class badge + category badge
  - Confidence badge (green ≥80%, yellow ≥60%, muted otherwise)
  - YES/NO probability bars (green/red, width = probability × 100%)
  - Edge bps display
  - Expandable "AI Reasoning" section (bull/bear arguments, collapsed by default)
  - "Place Bet" modal with YES/NO side selector, amount input, paper-mode disclaimer
  - Place bet calls `POST /api/polymarket/top-bets/{id}/accept` with `{ side, amount_usd }`
  - Success toast on completion

### 5. `ChatTab` (8th tab, `ChatTab.tsx`)
- Loads history from `GET /api/polymarket/chat/history` on mount.
- User messages right-aligned (primary bubble), assistant messages left-aligned (muted bubble).
- Animated typing dots shown while streaming response is in progress.
- SSE streaming: uses native `fetch` + `ReadableStream` reader; parses `data: {...}` lines;
  accumulates `chunk` fields into the assistant message in real time until `done: true`.
- Non-streaming fallback: if response has no body, falls back to `.json()` parse.
- Context market selector: dropdown populated from cached `pm-top-bets` query; passes
  `context_market_id` to `POST /api/polymarket/chat`.
- "Clear History" button: `DELETE /api/polymarket/chat/history`, clears local state, invalidates cache.
- On send failure: removes the empty assistant placeholder, shows error toast.
- Invalidates `pm-chat-history` on stream completion.

### 6. `LogsTab` (9th tab, `LogsTab.tsx`)
- **Agent health panel**: fetches `GET /api/polymarket/agents/health` every 30s; renders a card per
  agent with coloured status dot, "last seen X ago", scan count, and bet count.
  "Trigger Cycle" button calls `POST /api/polymarket/agents/cycle`.
- **Activity log table**: fetches `GET /api/polymarket/agents/activity` every 30s; columns:
  Time, Agent, Event, Message; rows color-coded by severity (red=error, yellow=warning).
  Scrollable max-height container.
- **Research logs**: fetches `GET /api/polymarket/research` every 60s; shows last 5 entries
  with category pills, date, summary, query count, and "Applied ✓" indicator.

### 7. `MarketsTab` wiring (`index.tsx`)
- Added `selectedVenue` state (`VenueId`, default `'all'`).
- Renders `VenueSelectorPills` + `TopBetsPanel` at the top of the Markets tab, above the
  existing market filter form and table.
- TopBetsPanel's `venue` prop is driven by `selectedVenue`, causing a re-fetch when changed.

### 8. Page title update
- H1 text: `'Polymarket'` → `'Prediction Markets'`
- Subtitle updated to include "chat, and logs".

---

## API Routes Used (all `/api/polymarket/...`)

| Method | Route | Component |
|--------|-------|-----------|
| GET | `/api/polymarket/agents/health` | `VenueSelectorPills`, `LogsTab` |
| GET | `/api/polymarket/top-bets` | `TopBetsPanel` |
| POST | `/api/polymarket/top-bets/{id}/accept` | `TopBetCard` modal |
| GET | `/api/polymarket/chat/history` | `ChatTab` |
| POST | `/api/polymarket/chat` | `ChatTab` |
| DELETE | `/api/polymarket/chat/history` | `ChatTab` |
| GET | `/api/polymarket/agents/activity` | `LogsTab` |
| POST | `/api/polymarket/agents/cycle` | `LogsTab` |
| GET | `/api/polymarket/research` | `LogsTab` |

---

## Deviations from Task Description

1. **API route prefix**: The task spec references `/api/v2/pm/...` routes, but the architecture
   doc (`polymarket-phase15.md` section 8) and all existing code use `/api/polymarket/...`.
   I followed the architecture doc and existing codebase convention to maintain consistency.
   Routes used: `/api/polymarket/top-bets`, `/api/polymarket/chat`, etc.

2. **POST `/top-bets/{id}/accept` vs `/execute`**: Task says `/execute`; architecture says
   `/accept`. Used `/accept` per architecture doc.

3. **TopBetsPanel placement**: Architecture places TopBetsPanel "above the TabsList, visible on
   all tabs". Task instruction says "in the existing first tab (Markets), ADD the TopBetsPanel
   + VenueSelector at the top, above the existing market list." Followed the task instruction
   (Markets tab only). If the architecture placement is desired, a follow-up phase can move it.

4. **LogsTab sub-tabs**: Architecture mentions 4 sub-tabs inside LogsTab; PRD F15-C shows 3 data
   sections. Implemented 3 sections (health, activity, research) as distinct visual panels rather
   than nested Radix sub-tabs to keep the implementation simple and the component under 250 lines.
   This can be promoted to sub-tabs in a follow-up if required.

5. **Pre-existing TypeScript errors**: `npx tsc --noEmit` reports 12 errors in 6 pre-existing
   files (`AgentDashboard.tsx`, `Backtests.tsx`, `Connectors.tsx`, `Login.tsx`, `Tasks.tsx`,
   `types/index.ts`). None of these are in Phase 15.7 files. All new/modified Phase 15.7 files
   compile cleanly.

---

## Tests Added

No unit tests added in this phase — Phase 15.7 DoD specifies TypeScript compilation + lint
clean as the quality gate. Component-level tests would be added in a follow-up if the team
adopts Vitest/React Testing Library for the dashboard.

---

## Open Risks

- `POST /api/polymarket/agents/cycle` endpoint may not exist in the backend yet (not in original
  Phase 10 routes). The UI will show an error toast gracefully if the endpoint is missing.
- SSE streaming assumes the backend sends `data: {"chunk": "..."}` lines terminated by
  `data: {"done": true}`. If the format differs, the non-streaming JSON fallback will apply.
- The `pm-agents-health` query is shared between `VenueSelectorPills` (in Markets tab) and
  `LogsTab`. TanStack Query deduplicates these automatically via the same query key.

---

## Cortex Fix Round

**Date:** 2025-07-11  
**Author:** Devin (dev)  
**Fixes two Cortex-flagged blockers in `ChatTab.tsx`.**

---

### Blocker 1 — SSE reader cleanup on unmount

**Problem:** The `fetch()` + `reader.read()` loop inside `sendMessage()` had no `AbortController`
tied to the component lifecycle. If the user navigated away mid-stream, the loop continued running
and React would warn about state updates on an unmounted component.

**Fix applied (`ChatTab.tsx`):**

1. Added `const abortRef = useRef<AbortController | null>(null)` alongside the other refs.
2. Added a dedicated mount-scoped `useEffect` with an empty dependency array whose cleanup
   function calls `abortRef.current?.abort()` — ensuring any in-flight stream is cancelled when
   the component unmounts.
3. In `sendMessage()`, before the `fetch` call: abort any previous in-flight stream with
   `abortRef.current?.abort()`, then assign a fresh `AbortController` to `abortRef.current`.
4. Passed `signal: abortRef.current.signal` to the `fetch()` options so the underlying request
   is truly cancelled (not just the JS loop).
5. Wrapped the SSE `while (true)` reader loop in an inner `try/catch`. When `err.name ===
   'AbortError'` the handler silently returns (user navigated away). All other errors are
   re-thrown so the outer catch can call `toast.error` as before.

---

### Blocker 2 — Raw `fetch()` bypassing centralised axios client config

**Problem:** `sendMessage()` read the API base URL directly from
`import.meta.env.VITE_API_URL` instead of from the already-imported axios instance. If the
base URL or its derivation were ever changed in `api.ts`, the SSE call would silently diverge.

**Fix applied (`ChatTab.tsx`):**

1. Replaced the `import.meta` env cast with `const baseURL = api.defaults.baseURL ?? ''`,
   pulling the base URL from the same axios instance that all other calls use.
2. Kept `localStorage.getItem('phoenix-v2-token')` — this is the same key used by `api.ts`'s
   request interceptor, so it remains consistent. If the key ever changes in `api.ts`, a single
   grep will surface both sites.
3. Built `headers` as `Record<string, string>` and conditionally added the `Authorization`
   header — same `Bearer` prefix as the interceptor in `api.ts`.
4. Removed the now-unnecessary `import.meta as ImportMeta & { env: ... }` type cast.

---

### Files changed

| File | Change |
|------|--------|
| `apps/dashboard/src/pages/polymarket/ChatTab.tsx` | Both blockers fixed (see above) |
| `docs/dev/polymarket-tab/phase-15-7-notes.md` | This section appended |

### TypeScript check

```
cd apps/dashboard && npx tsc --noEmit 2>&1 | grep -E "polymarket|ChatTab"
# → (no output) — zero errors in these files
```
The 12 pre-existing errors in `AgentDashboard.tsx`, `Backtests.tsx`, `Connectors.tsx`,
`Login.tsx`, `Tasks.tsx`, and `types/index.ts` remain unchanged and are not introduced by
this fix.

### Test suite

`make test` fails with Python `|`-union-type collection errors across 30 pre-existing unit
tests (Python < 3.10 environment). These failures are unrelated to this TypeScript-only change
and were already present before this fix round.
