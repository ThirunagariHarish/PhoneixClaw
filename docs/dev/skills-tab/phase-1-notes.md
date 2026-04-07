# Phase 1 Implementation Notes — Skills/Tools Tab (Frontend Only)

**Phase:** 1  
**Date:** 2025-01-31  
**Status:** Complete — ready for Cortex review

---

## What Changed

### Created: `apps/dashboard/src/components/AgentSkillsTab.tsx`

New self-contained React component implementing the Skills/Tools tab for the Agent Detail page.

**Features implemented:**
- **Backtesting placeholder** — when `agent.type === 'backtesting'`, renders a placeholder card ("Tools are configured when the agent is promoted to live") and makes **zero** API calls.
- **Loading state** — 3-card skeleton grid + identity section skeleton shown while `useQuery` is in flight.
- **Error state** — `AlertCircle` card with "Failed to load agent capabilities" message and a **Retry** button that calls `queryClient.invalidateQueries`.
- **Empty state** — if manifest has no tools, skills, or MCP servers, renders a Wrench icon + message card.
- **Character & Identity section** — 4-field grid: character type, analyst, Discord channel, active mode (mode shown as a highlighted `Badge`). Missing fields gracefully fall back to `—`.
- **Tools section** — responsive grid (2-col mobile → 3-col desktop) of `CapabilityCard` components. Each card shows: active/inactive dot, formatted name, color-coded category badge, description.
- **Skills section** — same card layout; heading always visible even when empty.
- **MCP Servers section** — derived entirely client-side from `agent.config.robinhood_credentials`. Shows Paper Mode (yellow) vs. Live (red) badge per AC-03.2.

**TypeScript interfaces (verbatim from architecture doc):**
- `ToolCategory`, `ManifestTool`, `ManifestSkill`, `ManifestIdentity`, `ManifestModes`, `AgentManifestPayload`, `ManifestResponse`, `MCPMode`, `MCPServer`, `AgentSkillsTabProps`, `CapabilityCardProps`, `MCPServerCardProps`

**Static constants:** `TOOL_META`, `SKILL_META`, `CATEGORY_COLORS`

**Helper functions:** `formatName`, `normaliseCategory`, `normaliseTools`, `normaliseSkills`, `deriveMCPServers`

**Query config:**
- `queryKey: ['agent-manifest', agentId]` — matches architecture convention
- `staleTime: 30_000` (30 s)
- `enabled: !isBacktesting` — no fetch for backtesting agents (AC-05.2)

**API pattern:** Uses `api` (axios instance) from `@/lib/api` — same as `AgentScheduleTab.tsx`.

**Agent prop type:** Inline structural type `{ type: string; config: Record<string, unknown> }` — compatible with `AgentData` from `AgentDashboard.tsx` without creating a circular import.

---

### Modified: `apps/dashboard/src/pages/AgentDashboard.tsx`

**Change 1 — Lucide import (line ~29):**  
Added `Wrench` to the existing Lucide import block.

**Change 2 — Component import (line ~38):**  
Added `import { AgentSkillsTab } from '@/components/AgentSkillsTab'` after the other tab component imports.

**Change 3 — `TabsList` grid (line ~1375):**  
Changed `grid-cols-9` → `grid-cols-10`.

**Change 4 — `TabsTrigger` (line ~1386):**  
Added `<TabsTrigger value="skills">` with `Wrench` icon after the `runtime` trigger.

**Change 5 — `TabsContent` (line ~1413):**  
Added `<TabsContent value="skills">` rendering `<AgentSkillsTab agentId={id} agent={agent} />`.

---

## Files Touched

| Action | File |
|---|---|
| CREATE | `apps/dashboard/src/components/AgentSkillsTab.tsx` |
| MODIFY | `apps/dashboard/src/pages/AgentDashboard.tsx` |

---

## Tests Added

None — this is a pure read-only frontend display component with no business logic mutations. All rendering logic is deterministic given props + query data. Unit tests (mocked query, snapshot) are deferred to the QA phase per team convention.

---

## Self-Check Results

| Check | Result |
|---|---|
| `npx tsc --noEmit` — errors in `AgentSkillsTab.tsx` | **0** |
| `ls apps/dashboard/src/components/AgentSkillsTab.tsx` | **exists** |
| `grep "skills" AgentDashboard.tsx` — TabsTrigger + TabsContent present | **✓** |
| `grep ": any" AgentSkillsTab.tsx` count | **0** |

**Pre-existing TS errors (not introduced by this phase):**
- `AgentDashboard.tsx:900-966` — `ModelResult` cast warnings in backtesting sort code
- `Backtests.tsx`, `Connectors.tsx`, `Login.tsx`, `Tasks.tsx`, `types/index.ts` — unrelated pre-existing issues

---

## Deviations from Architecture

**None.** All interfaces, constants, helper functions, and component structure match the architecture doc verbatim.

One minor addition beyond the architecture spec:
- `normaliseTools` / `normaliseSkills` helpers — added to handle backward-compatible raw strings in manifest arrays (the fallback manifest from `agents.py:1450` can return `tools: []`, but existing agents may store tools as string arrays). This is defensive programming, not a design change.

---

## Open Risks

1. **Manifest tool shape variance** — existing agents may store tools as plain string arrays rather than `ManifestTool[]` objects. The `normaliseTools`/`normaliseSkills` helpers handle this via runtime type narrowing.
2. **No unit tests** — the component has no test coverage in this phase. Quill's E2E smoke test (per PRD success metrics) will serve as the primary verification path.
3. **`agent.type === 'backtesting'` check** — in `AgentDashboard.tsx`, `AgentData.type` is typed as `string` (not `AgentType` from `types/agent.ts`). The backtesting check works as a runtime string comparison, but if the type naming ever changes on the backend the placeholder won't trigger. This is consistent with how `LIVE` check works in the same file.
