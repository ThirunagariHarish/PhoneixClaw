# Phase 3: Agent Knowledge Wiki — Dashboard UI
**Date:** 2025-01-01  
**Commit:** `acaaca6`

## What Changed

### `apps/dashboard/src/components/AgentWikiTab.tsx` (primary file)
Complete spec-alignment pass on the existing 743-line implementation.

#### Added
| Feature | Detail |
|---|---|
| `CATEGORY_META` | Spec-compliant record with `icon`, `color`, `label` for all 8 categories (`MARKET_PATTERNS`, `SYMBOL_PROFILES`, `STRATEGY_LEARNINGS`, `MISTAKES`, `WINNING_CONDITIONS`, `SECTOR_NOTES`, `MACRO_CONTEXT`, `TRADE_OBSERVATION`) |
| `getCategoryMeta()` | Fallback helper for entries with non-spec category strings (backward-compat) |
| `ConfidenceBar` | 1px coloured bar — green ≥0.7, yellow ≥0.4, red <0.4 — matches spec |
| `formatRelativeTime()` | `Xs/Xm/Xh/Xd ago` relative formatter |
| **Phoenix Brain toggle** | Button above entry list; when ON, queries `GET /api/v2/brain/wiki?category=&search=`. TanStack Query key: `['brain-wiki', category, search]`. Read-only: hides New Entry button. Violet info banner. |
| **Created-by badge** | 🤖 Agent (emerald) / 👤 User (violet) on both entry cards and detail panel |
| `BrainWikiResponse` interface | Typed response for brain wiki endpoint |
| `Bot`, `User` Lucide icons | Added to imports |
| `isBrain` prop on `EntryCard` | Renders `🧠 Brain` badge on cards from the brain endpoint |

#### Changed
| Before | After |
|---|---|
| Old category list (`TRADE_OBSERVATION`, `MARKET_PATTERN`, …8 legacy names) | New spec categories |
| `CATEGORY_LABELS` Record | Replaced by `CATEGORY_META` (icons + colours) |
| `ConfidenceBadge` used emerald/amber/rose Tailwind classes | Now uses spec colours: `bg-green-500/20`, `bg-yellow-500/20`, `bg-red-500/20` |
| Export filename: `wiki-{id}.md` | `agent-wiki-{id}.md` (per spec) |
| Confidence input: `<input type="number" min=0 max=1>` | Slider (`<input type="range">`) + live `ConfidenceBar` preview |
| `EntryCard` had no content preview | Shows first 100 chars of content |
| `EntryCard` used `toLocaleDateString()` | Uses `formatRelativeTime()` |
| Category sidebar used text-only labels | Shows emoji icon + coloured label |
| `AgentWikiTabProps.agent` — absent | Added as `agent?: unknown` (reserved, not rendered) |
| `created_by: string` | `created_by: 'agent' | 'user'` (strict union) |

#### Removed
- `CATEGORY_LABELS` Record (replaced by `CATEGORY_META`)
- `BookOpen` from Lucide imports (was unused after empty-state icon switch to `Brain`)

### `apps/dashboard/src/pages/AgentDashboard.tsx`
- Line 1588: pass `agent={agent}` to `<AgentWikiTab>` (spec requirement)

## Files Touched
1. `apps/dashboard/src/components/AgentWikiTab.tsx`
2. `apps/dashboard/src/pages/AgentDashboard.tsx`

## Tests Added
None (component-level; Quill covers E2E). No unit test harness exists for React components in this project.

## Build / Type-check Results
- **TypeScript:** 0 errors in files I own. 12 pre-existing errors across 6 unrelated files (`Login.tsx`, `Connectors.tsx`, `Tasks.tsx`, `Backtests.tsx`, `types/index.ts`, `AgentDashboard.tsx` lines 1068–1134). Confirmed pre-existing via `git stash` test.
- **Vite build:** fails due to same pre-existing TS errors. Pre-existing before this phase.

## Deviations from Spec
| Spec | Decision |
|---|---|
| `grid-cols-9 → grid-cols-10` | Dashboard already has `grid-cols-11` (Skills tab was added in a prior phase). No change needed — wiki trigger already present. |
| `AgentWikiTab agentId={agentId} agent={agent}` | Typed `agent` as `unknown` (vs `Record<string, unknown>`) to avoid TS2322 since `AgentData` has no index signature. Component doesn't use `agent` at runtime. |

## Open Risks
- **Category mismatch:** Agent tools and backend may write old category strings (e.g., `MARKET_PATTERN`, `RISK_NOTE`). `getCategoryMeta()` fallback handles unknown values gracefully with a generic icon. Backend migration needed to unify.
- **Brain endpoint 404:** `/api/v2/brain/wiki` may not be deployed yet (parallel backend agent). TanStack Query will surface error silently (no toast); brain button will show empty state.
- **Pre-existing build failure:** The `tsc -b && vite build` pipeline was already broken before this phase. Cortex / Helix should track this as a blocker for CD.
