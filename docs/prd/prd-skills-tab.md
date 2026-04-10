# PRD: Skills / Tools Tab — Agent Detail Page

_Status: Draft · Author: Nova (PM) · Date: 2025-01-31_

---

## 1. Problem

Operators and developers who manage trading agents cannot, today, answer a basic
question from the agent detail page: **"What can this agent actually do?"**

The current nine-tab layout (`Portfolio | Trades | Chat | Feed | Intel | Logs |
Schedule | Rules | Runtime`) exposes _what the agent has done_ and _how it is
configured operationally_, but no tab surfaces the agent's capability surface —
its registered tools, skills, MCP server connections, and character identity.

This creates friction in three scenarios:

1. **Debugging** — an operator suspects a tool is misconfigured or disabled; they
   must read raw JSON in an admin panel rather than seeing a formatted card.
2. **Promotion reviews** — before promoting a backtesting agent to live, a
   reviewer cannot see the intended capability set from the UI; they must query
   the database directly.
3. **Onboarding** — new team members have no visual map of what each agent is
   capable of; documentation gaps are filled by tribal knowledge.

The data to answer all three scenarios already exists: the
`GET /api/v2/agents/:id/manifest` endpoint returns `tools[]`, `skills[]`,
`identity{}`, `modes{}`, and `current_mode` today, but nothing in the frontend
renders it in a human-readable format on the agent detail page.

---

## 2. Target Users & Jobs-to-be-Done

| User | Job-to-be-done |
|---|---|
| **Trading system operator** | Quickly verify which tools are active/inactive on a live agent before a market session |
| **Developer / DevOps engineer** | Debug a misbehaving agent by checking its full capability footprint without querying the DB |
| **Agent reviewer (pre-promotion)** | Confirm a backtesting agent has the correct tool set before approving promotion to live |
| **New team member (onboarding)** | Understand what a given agent is built to do from its identity, skills, and tool descriptions |

---

## 3. Goals & Non-Goals

### Goals
- Add a **"Skills"** tab to the `LiveSection` tab bar in `AgentDashboard.tsx`
- Display **tools**, **skills**, **MCP servers**, and **character/identity** data
  drawn entirely from the existing `/api/v2/agents/:id/manifest` response and
  agent `config` JSONB — no new required backend work
- Provide clear **loading**, **error**, and **empty** states for every section
- Match the existing dark-theme visual language (Radix/Tailwind/card components)
- Be **fully responsive** (2-column mobile → 3-column desktop)
- Enforce **TypeScript strict mode** throughout the new component (zero `any` types)
- Show an appropriate **placeholder** for `backtesting`-type agents

### Non-Goals
- Editing or toggling tools/skills from this tab (read-only display only)
- Adding a brand-new backend endpoint (the existing manifest endpoint is
  sufficient; a dedicated `/skills` endpoint is optional and out-of-scope for
  the initial release)
- Surfacing the full `risk{}` or `rules[]` sections (those belong to existing tabs)
- Changing data stored in the manifest (that is an admin/configuration concern)
- Mobile-native or PWA support beyond standard responsive CSS

---

## 4. Success Metrics

| Metric | Target |
|---|---|
| Tab renders without console errors for all agent types | 100 % of agents in QA smoke test |
| Time-to-first-meaningful-paint for the Skills tab | < 400 ms (manifest is already cached by TanStack Query in most flows) |
| Developer task: "find what tools agent X has" — steps from agent page | Reduced from 4+ steps (navigate to admin / raw JSON) to 1 click |
| TypeScript compilation errors in new component | 0 |
| Backtesting-agent placeholder shown correctly | 100 % of backtesting agents in QA |

---

## 5. User Stories

_(Full acceptance criteria in § 6. Stories reference priority P0/P1/P2.)_

| ID | Story | Priority |
|---|---|---|
| US-01 | As an **operator**, I want to open the Skills tab on any live agent and see its tools displayed as cards with name, description, category badge, and active/inactive status, so that I can verify the agent's capability set before a trading session. | P0 |
| US-02 | As a **developer**, I want to see the agent's skills (distinct from tools) in their own grid section, so that I can distinguish data-processing capabilities from execution tools. | P0 |
| US-03 | As a **developer**, I want to see which MCP servers the agent is connected to (e.g., Robinhood in Paper vs. Live mode) inferred from the agent's config, so that I can confirm brokerage connectivity at a glance. | P1 |
| US-04 | As any **user**, I want to see the agent's character, analyst name, active mode, and Discord channel in a Character & Identity section, so that I understand the agent's persona and current operational mode without reading raw JSON. | P1 |
| US-05 | As a **reviewer**, when I open a `backtesting`-type agent's Skills tab, I want to see a clear placeholder message — "Tools are configured when the agent is promoted to live" — so that I am not confused by an empty state and understand it is by design. | P1 |

---

## 6. Acceptance Criteria

### US-01 — Tools Section

**AC-01.1** Given the Skills tab is open on a live agent whose manifest has a
non-empty `tools` array, when the manifest loads, then each tool is rendered as
a card containing: a formatted display name, a description string, a category
badge (color-coded: trading=blue, analysis=purple, data=green, risk=red,
reporting=gray), and an active/inactive status indicator (green dot = active,
gray dot = inactive).

**AC-01.2** Given the manifest `tools` array is empty or absent, when the tab
renders, then a message "No tools configured" is displayed in place of the grid.

**AC-01.3** Given the manifest is loading, when the tab first renders, then
skeleton placeholder cards are shown (minimum 3 skeletons) with no layout shift.

**AC-01.4** Given the manifest API call returns a non-2xx status, when the tab
renders, then an error state with message "Failed to load agent capabilities" is
shown with a retry affordance.

**AC-01.5** Given a desktop viewport (≥ 1024 px), when the tools grid renders,
then cards are arranged in a 3-column grid. Given a mobile viewport (< 768 px),
then cards collapse to a 2-column grid.

---

### US-02 — Skills Section

**AC-02.1** Given the manifest has a non-empty `skills` array, when the tab
renders, then each skill is shown as a card with: formatted name, description,
and category badge using the same color scheme as tools.

**AC-02.2** Given the `skills` array is empty or absent, when the tab renders,
then the Skills section heading is still visible but shows "No skills configured"
beneath it (section is not hidden entirely).

**AC-02.3** The Tools section and Skills section are visually separated with a
section heading and optional icon (`Wrench`/`Cpu` for Tools; `Zap`/`BookOpen`
for Skills per the design spec).

---

### US-03 — MCP Servers Section

**AC-03.1** Given an agent whose `config` JSONB contains a non-null
`robinhood_credentials` key, when the tab renders, then a Robinhood MCP server
card is shown.

**AC-03.2** Given the Robinhood card is shown, then it displays a badge
indicating **"Paper Mode"** if `config.paper_trading` is truthy, or **"Live"**
if falsy/absent, with Live rendered in a red/warning color.

**AC-03.3** Given an agent with no recognizable MCP credentials in config, when
the tab renders, then the MCP Servers section shows "No MCP servers connected".

---

### US-04 — Character & Identity Section

**AC-04.1** Given the manifest has an `identity` object, when the tab renders,
then the following fields are displayed: character type (`identity.character`),
analyst name (`identity.analyst`), Discord channel (`identity.channel`), and
active mode (`current_mode` from the manifest API response).

**AC-04.2** Given any field in `identity` is missing or empty, when the tab
renders, then that field shows a graceful fallback value (e.g., "—" or
"Unknown") rather than `undefined`, `null`, or a blank cell.

**AC-04.3** `current_mode` is rendered as a highlighted badge distinct from
plain text fields.

---

### US-05 — Backtesting Agent Placeholder

**AC-05.1** Given the agent's `type` field (from agent data or `config.type`) is
`"backtesting"`, when the Skills tab is selected, then the entire content area
shows only the message: _"Tools are configured when the agent is promoted to
live"_ along with a suitable icon, and none of the tools/skills/MCP/identity
sections are rendered.

**AC-05.2** The placeholder does not make any API call to the manifest endpoint
(avoid unnecessary network requests for backtesting agents).

---

### Cross-cutting Quality Criteria

**AC-QC-1** The `AgentSkillsTab` component has zero TypeScript `any` types; the
TypeScript compiler reports no errors in strict mode.

**AC-QC-2** No new console errors or warnings are introduced in the browser
DevTools when the Skills tab is mounted or unmounted.

**AC-QC-3** The tab trigger label "Skills" with a `Wrench` icon is inserted into
the `LiveSection` `TabsList` in `AgentDashboard.tsx`; the `grid-cols-9` class is
updated to `grid-cols-10` to accommodate the new tab.

**AC-QC-4** The manifest query is keyed as `['agent-manifest', agentId]` in
TanStack Query, consistent with the project's query-key naming convention, and
uses `staleTime: 30_000` (30 s) to avoid redundant fetches when the user
switches between tabs.

**AC-QC-5** If a new `GET /api/v2/agents/:id/skills` endpoint is added, it must
have a corresponding unit test in `apps/api/tests/`.

---

## 7. Open Questions

_None — all requirements have been specified by the feature owner. Any future
ambiguities should be filed as follow-up tickets._

---

## 8. Out-of-Scope

- **Editing tools/skills** from this tab (write/toggle operations are out of scope)
- **Dedicated `/skills` backend endpoint** — optional; the manifest endpoint is sufficient for v1
- **`risk{}` and `rules[]` manifest sections** — already covered by the Rules tab and Runtime tab
- **Tool enable/disable toggle** — requires backend mutation design; deferred to a future story
- **Historical tool activation log** — would need a new audit table; deferred
- **Comparison view across agents** — multi-agent capability diff is a separate feature
- **Mobile app / PWA** — beyond responsive CSS, native mobile is out of scope

---

## 9. Files to Create / Modify

| Action | Path | Notes |
|---|---|---|
| **CREATE** | `apps/dashboard/src/components/AgentSkillsTab.tsx` | New self-contained tab component |
| **MODIFY** | `apps/dashboard/src/pages/AgentDashboard.tsx` | Add tab trigger + `<TabsContent>` in `LiveSection`; update `grid-cols-9` → `grid-cols-10` (line ~1375) |
| **OPTIONAL CREATE** | `apps/api/src/routes/agents.py` | `GET /{agent_id}/skills` convenience endpoint |
| **OPTIONAL CREATE** | `apps/api/tests/test_agent_skills.py` | Unit test for new endpoint if added |

---

## 10. Research & Sources

> All codebase references are from direct static analysis of the repo at
> `/Users/harishkumar/Projects/TradingBot/ProjectPhoneix`.

| Reference | Location | Finding |
|---|---|---|
| Manifest endpoint | `apps/api/src/routes/agents.py` — `@router.get("/{agent_id}/manifest")` | Confirmed: returns `{ agent_id, manifest, current_mode, rules_version }`. `manifest` contains `tools[]`, `skills[]`, `identity{}`, `modes{}`, `risk{}`, `rules[]`. Falls back to a synthetic manifest if `agent.manifest` is null. |
| Manifest schema (fallback) | `agents.py` lines containing `"tools": [], "skills": [], "knowledge": {}` | Confirmed: `tools` and `skills` are always present in the response (at minimum as empty arrays). |
| `LiveSection` tab bar | `AgentDashboard.tsx` lines 1374–1385 | Confirmed: 9 tabs in `grid-cols-9`. Values: `portfolio`, `trades`, `chat`, `messages`, `intelligence`, `logs`, `schedule`, `rules`, `runtime`. |
| Tab component pattern | `AgentScheduleTab.tsx` lines 1–40 | Pattern: standalone `.tsx` in `components/`, TanStack Query (`useQuery`), typed interfaces at top, Radix UI `Card`/`Badge`, Lucide icons. |
| Global Skills page | `apps/dashboard/src/pages/Skills.tsx` | A global catalog page already exists at `/skills` route — the new tab is _per-agent_ and distinct from this global page. Reuse of `SKILL_CATEGORIES` constants is possible. |
| Agent `config` JSONB fields | `agents.py` — agent creation payload | `robinhood_credentials`, `discord_channel`, `type`, `paper_trading`, `modes`, `rules`, `risk_params` stored in JSONB `config`. |
| Manifest PUT — updatable keys | `agents.py` — `update_agent_manifest` | `rules`, `modes`, `risk`, `knowledge`, `models`, `identity`, `tools`, `skills` are all writable — confirms `tools` and `skills` are first-class manifest keys. |
| UI component library | `apps/dashboard/src/components/ui/` | `Card`, `Badge`, `Skeleton`, `EmptyState`, `StatusBadge` are all available — no new UI primitives needed. |

