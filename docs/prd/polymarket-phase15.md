# PRD: Prediction Markets Phase 15 — Top Bets + Chat + Logs + Auto-Research + Robinhood Venue + LLM Inference

**Version:** 2.0  
**Status:** Draft  
**Author:** Nova (PM)  
**Changelog:** v2.0 — Added F15-E (Prediction Markets tab + Robinhood venue), F15-F (LLM RAG inference pipeline), updated F15-A TopBetCard, success metrics M7–M10, new DB tables, new API routes, UI additions. All v1.0 content preserved.  
**Depends on:** Phases 1–14 (all existing Polymarket infrastructure)

---

## 1. Problem

Phoenix Trade Bot has 14 phases of Polymarket infrastructure — live broker adapters, arbitrage agents, resolution-risk scoring, promotion gates, backtesting, and a 7-tab dashboard — yet the user has no opinionated, actionable answer to the most fundamental question: **"What should I bet on right now, and why?"**

The agents run silently. There is no surface for the user to see what the agents have found, talk to them in natural language, watch them work in real-time, or trust that they are continuously learning better strategies. As a result:
- The user cannot act on agent intelligence without manually navigating markets, reading prices, and applying judgment themselves.
- Accepted/rejected trade recommendations have no workflow; they fall into a void.
- Agent activity is invisible — no heartbeat, no scan count, no error feed.
- Strategy quality is static; there is no mechanism to incorporate new alpha from the broader Polymarket community.
- The jurisdiction banner frightens US users away from markets they are legally permitted to trade (sports, entertainment), because the copy implies a total geo-block that is no longer accurate.
- The platform is Polymarket-only, locking US users out of the fastest-growing regulated prediction market venue: **Robinhood Prediction Markets** (CFTC-regulated, launched 2024, no geo-restriction for US users).
- Bet scoring relies entirely on hand-crafted heuristics; there is no mechanism to leverage historical resolved markets as a training signal for future recommendations.

Phase 15 closes these gaps by adding a **24/7 high-confidence bet scanner agent**, a **conversational Chat tab**, a **real-time Logs tab**, a **nightly Auto-Research loop**, a **Robinhood Prediction Markets venue**, and an **LLM-powered RAG inference scoring pipeline** — all wired into the existing tab page, agent infrastructure, and database.

---

## 2. Target Users & Jobs-to-Be-Done

| User Segment | Job-to-Be-Done |
|---|---|
| **Solo discretionary trader (primary)** | "Show me the 5 best bets the agent found today so I can decide quickly whether to take them, without having to scan hundreds of markets myself." |
| **US-first trader** | "I want to use Robinhood Prediction Markets since it's CFTC-regulated and I already have a Robinhood account — show me those markets as the default, not Polymarket." |
| **Hands-on monitor** | "Let me watch what the agent is doing right now — what it scanned, what it skipped, whether it threw an error — so I feel confident it is working 24/7." |
| **Curious learner** | "I want to ask the agent questions in plain English: what's the best election bet right now? Is there an Iran/ceasefire market? What's the Kelly fraction?" |
| **Strategy improver** | "I want the system to go out, read how experts make money on prediction markets, pull in those strategies, and continuously raise the quality bar without me having to do the research myself." |
| **Evidence-based trader** | "I want AI recommendations grounded in data from thousands of past resolved markets — not just price math — so I can trust the reasoning behind each bet." |

---

## 3. Goals & Non-Goals

### Goals
- Surface a daily ranked list of **top 5–10 high-confidence bets** produced by a new 24/7 agent.
- Give the user an **Accept / Reject** workflow that routes accepted bets into paper trades automatically.
- Add a **Chat tab** so the user can query the PM agent in natural language and receive inline "Accept bet" actions.
- Add a **Logs tab** so the user can monitor agent health, scan counts, and activity in real-time.
- Integrate with the existing **AutoResearch** system so the agent improves its strategy config nightly.
- Fix the **jurisdiction banner** copy to reflect the accurate 2024 US-access status for Polymarket.
- **Rename the "Polymarket" tab to "Prediction Markets"** and add a venue selector supporting Robinhood (primary) and Polymarket (secondary).
- **Add Robinhood Prediction Markets** as the primary venue: CFTC-regulated, US-accessible without restrictions, using Robinhood's existing OAuth2 authentication.
- **Build an LLM-powered RAG scoring pipeline** that retrieves similar historical resolved markets and produces a probability estimate + reasoning for each candidate bet.

### Non-Goals (Phase 15)
- **Full automation / autonomous live execution** — Phase 15 is manual-accept only; automation is a future phase.
- **Mobile / native app** — dashboard only.
- **Backtesting the top-bets agent itself** — walk-forward backtester already exists; plugging top-bets output into it is a future phase.
- **Multi-user / multi-tenant chat** — single-user (operator) chat only.
- **Redesigning existing tabs** — Markets, Strategies, Orders, Positions, Promotion, Briefing, Risk are frozen for this phase.
- **LLM model selection UI** — the agent will use whatever LLM is already configured in OpenClaw.
- **WebSocket for Chat** — HTTP streaming (SSE or chunked POST) is sufficient; full WS upgrade is a future phase.
- **Live Robinhood order placement in Phase 15** — Robinhood operates in **paper mode only**; user manually places live trades from recommendations. Live Robinhood execution is Phase 16.
- **pgvector extension setup** — use JSONB array + Python cosine similarity for v1.0; pgvector upgrade path documented for v1.2.
- **Fine-tuning any base model** — RAG-only approach; no gradient updates or model weight changes.
- **Multi-user / social prediction features** — single-operator use only.

---

## 4. Success Metrics

| # | Metric | Target |
|---|---|---|
| M1 | Top-bets agent produces ≥ 5 recommendations per day with `confidence_score ≥ 70` within 7 days of deployment | 100% of days |
| M2 | User accepts or rejects a recommendation within the dashboard (no console intervention needed) | Accept/Reject action works end-to-end for 100% of recommendations |
| M3 | Chat tab returns a non-empty, contextually relevant response to any free-text query within 10 seconds (p95) | p95 latency < 10 s |
| M4 | Logs tab shows agent last-heartbeat timestamp ≤ 60 seconds stale at all times while agent is running | Heartbeat freshness ≤ 60 s |
| M5 | Auto-research loop completes nightly run and writes ≥ 1 new entry to `pm_strategy_research_log` per week | ≥ 1 entry/week |
| M6 | Zero support tickets or user confusion attributable to the jurisdiction banner after copy update | 0 tickets |
| M7 | LLM scorer Brier score vs heuristic baseline | LLM Brier score ≤ heuristic Brier score |
| M8 | Historical markets ingested on first activation | ≥ 100 resolved markets across all venues |
| M9 | % of TopBet recommendations with LLM reasoning populated | ≥ 90% when LLM is available and reachable |
| M10 | Robinhood Prediction Markets scanned per cycle | ≥ 20 active markets per scan cycle |

---

## 5. Feature Details, User Stories & Acceptance Criteria

---

### F15-A: Top Bets Agent — 24/7 High-Confidence Bet Scanner

**Description:**  
A new OpenClaw agent (`agents/polymarket/top_bets/`) runs continuously as a background service. It scans all active markets across configured venues (Robinhood primary, Polymarket secondary), scores each for "high-confidence tradeability" using a composite signal (heuristic baseline in v1.0, LLM RAG scorer from F15-F in v1.1+), and emits a daily ranked shortlist. Results are stored in a new `pm_top_bets` table and surfaced via a new API endpoint. The user accepts or rejects each recommendation from the UI; accepted bets auto-route to the appropriate paper-mode strategy as a pending order.

**Scoring Signals (composite, agent-internal):**
- F9 resolution-risk score (must be `tradeable=true`; higher final_score = higher confidence)
- Volume / liquidity threshold (must meet configurable `min_liquidity_usd` from strategy config)
- Price inefficiency vs. estimated fair value (edge in basis points)
- Time-to-resolution (prefer markets resolving within 7–90 days; avoid < 24 h or > 180 d)
- Category weight (sports and macro events weighted higher; obscure/novelty bets weighted lower)
- **LLM RAG score** (when F15-F is active): replaces heuristic fair-value estimate; see F15-F3

**TopBetCard Specification (updated v2.0):**  
Each recommendation card must display all of the following:
- **Venue badge**: `"ROBINHOOD"` in green or `"POLYMARKET"` in purple (reflecting the `venue` field)
- **Market question** (full text)
- **Outcomes panel**: for binary markets, YES% and NO% confidence side-by-side; for multi-outcome markets, percentage for each option (up to 4 options shown, remaining collapsed)
- **Recommended side** badge (YES / NO / outcome label)
- **Confidence score** (0–100 with progress bar)
- **Edge in basis points**
- **AI Reasoning** expandable section (from F15-F3): 2–3 sentences of LLM explanation; hidden if LLM scorer unavailable
- **Similar Markets** accordion: top-3 similar historical markets with their outcome and peak YES price (populated from F15-F EmbeddingStore results; hidden if embedding store empty)
- **Accept / Reject** action buttons

**User Stories:**

| ID | Story | Priority |
|---|---|---|
| US-A1 | As a trader, I want to see a daily ranked list of the top 5–10 bets the agent identified, so I can quickly decide what to trade without scanning markets myself. | P0 |
| US-A2 | As a trader, I want to see for each bet: the market question, current YES/NO prices, recommended side, confidence score, estimated edge (bps), venue badge, and a 2–3 sentence reasoning, so I can make an informed decision. | P0 |
| US-A3 | As a trader, I want to click "Accept" on a recommendation and have it automatically routed as a paper trade in the correct strategy, so I don't have to manually create an order. | P0 |
| US-A4 | As a trader, I want to click "Reject" on a recommendation so the agent learns this type of bet is not to my taste and stops surfacing similar ones. | P1 |
| US-A5 | As a trader, I want to filter the top-bets list by minimum confidence score and category, so I can focus on what matters most to me. | P1 |
| US-A6 | As a trader, I want to see a "stale" indicator if the agent has not refreshed the top-bets list in more than 6 hours, so I know if something is wrong. | P1 |

**Acceptance Criteria — US-A1 / US-A2:**
- **Given** the top-bets agent has completed a scan cycle,  
  **When** the user opens the Prediction Markets page (any tab),  
  **Then** a "Top Bets" card or panel is visible showing ≥ 1 and ≤ 10 recommendations with all required fields (question, YES price, NO price, side, confidence_score, edge_bps, reasoning, venue badge).

**Acceptance Criteria — US-A3:**
- **Given** a recommendation exists with `status = pending`,  
  **When** the user clicks "Accept",  
  **Then** a paper order is created in `pm_orders` linked to the correct `pm_strategy_id`, the recommendation's `status` in `pm_top_bets` is set to `accepted`, and a success toast is shown.

**Acceptance Criteria — US-A4:**
- **Given** a recommendation exists with `status = pending`,  
  **When** the user clicks "Reject",  
  **Then** `pm_top_bets.status` is set to `rejected`, the recommendation is hidden from the active list, and a `rejected_reason` (optional free-text) is stored.

**Acceptance Criteria — US-A5:**
- **Given** the top-bets panel is visible,  
  **When** the user sets `min_confidence = 80` and `category = sports`,  
  **Then** only bets matching both filters are shown; the filter state persists within the session.

**Acceptance Criteria — US-A6:**
- **Given** the most recent `pm_top_bets` row for today has `created_at` > 6 hours ago,  
  **When** the user views the top-bets panel,  
  **Then** an amber "Data may be stale — last updated X hours ago" indicator is shown.

---

### F15-B: Chat Tab — Prediction Markets Agent Conversational Interface

**Description:**  
A new **"Chat"** tab is added to the Prediction Markets page `TabsList`, immediately after "Risk" (making it the 8th tab). It provides a conversational interface backed by an OpenClaw agent session that has access to the current top-bets state, market data across all venues, F9 scores, and the user's existing positions. Responses can include inline "Accept bet" action buttons when the agent recommends a trade. Chat history is persisted in `pm_chat_messages`.

**Example user queries the system must handle:**
- "Is there a bet on an Iran-Trump ceasefire?"
- "What's the best election bet right now?"
- "Show me sports bets with > 80% confidence."
- "What's the Kelly fraction for market X?"
- "How much of my bankroll should I put on this?"
- "Explain why you gave that market a low F9 score."
- "Show me Robinhood markets in the economics category."

**User Stories:**

| ID | Story | Priority |
|---|---|---|
| US-B1 | As a trader, I want to type a natural-language question about prediction market bets and receive a helpful, context-aware answer from the agent. | P0 |
| US-B2 | As a trader, I want to see the agent's response include an inline "Accept bet" button when it recommends a specific trade, so I can act without leaving the chat. | P0 |
| US-B3 | As a trader, I want the chat history to persist between sessions so I can refer back to past recommendations and reasoning. | P1 |
| US-B4 | As a trader, I want to see a "typing…" indicator while the agent is generating a response, so I know the system is working. | P1 |
| US-B5 | As a trader, I want to clear the chat history with a single button, so I can start a fresh conversation. | P2 |

**Acceptance Criteria — US-B1:**
- **Given** the Chat tab is open,  
  **When** the user types "What's the best sports bet right now?" and presses send,  
  **Then** the agent returns a response within 10 seconds (p95) referencing at least one market by name with a recommendation.

**Acceptance Criteria — US-B2:**
- **Given** the agent response contains a trade recommendation,  
  **When** the response is rendered,  
  **Then** an "Accept bet" button is present inline; clicking it triggers the same accept flow as F15-A (paper order created, `pm_top_bets.status` updated, success toast).

**Acceptance Criteria — US-B3:**
- **Given** the user had a previous chat session,  
  **When** they navigate away and return to the Chat tab,  
  **Then** the last 50 messages (configurable) are loaded from `pm_chat_messages` in chronological order.

**Acceptance Criteria — US-B4:**
- **Given** the user has submitted a message,  
  **When** the agent has not yet responded,  
  **Then** a "typing…" / loading indicator is visible in the agent message area.

---

### F15-C: Logs Tab — Agent Activity Monitor

**Description:**  
A new **"Logs"** tab is added after "Chat" (making it the 9th tab). It shows a real-time activity feed of all PM agent actions, health status cards per agent, and a "Research" sub-panel displaying the latest auto-research findings from F15-D. The feed is polled from a new `/api/polymarket/agents/activity` endpoint backed by a new `pm_agent_activity_log` table and existing Redis Streams.

**User Stories:**

| ID | Story | Priority |
|---|---|---|
| US-C1 | As a trader, I want to see a real-time feed of what the PM agents are doing (markets scanned, bets scored, recommendations generated, orders placed), so I am confident they are working 24/7. | P0 |
| US-C2 | As a trader, I want to see a health card per agent (top_bets, sum_to_one_arb, cross_venue_arb) showing: running/stopped, last heartbeat, markets scanned today, bets/recommendations generated today. | P0 |
| US-C3 | As a trader, I want to filter the log feed by agent, severity (info / warn / error), and time range, so I can quickly find errors or focus on one agent. | P1 |
| US-C4 | As a trader, I want error-level log entries to be visually distinct (red) so they immediately catch my eye. | P1 |
| US-C5 | As a trader, I want a "Research" sub-panel inside the Logs tab that shows the latest auto-research findings (what strategies were discovered, what config changes were applied). | P1 |

**Acceptance Criteria — US-C1:**
- **Given** the Logs tab is open,  
  **When** the top-bets agent completes a scan cycle,  
  **Then** a new `info`-severity log entry appears in the feed within 30 seconds, showing agent name, timestamp, action type, and a brief description.

**Acceptance Criteria — US-C2:**
- **Given** the Logs tab is open,  
  **When** an agent's heartbeat has not been received for > 60 seconds,  
  **Then** its health card shows a red "OFFLINE" badge; otherwise it shows a green "RUNNING" badge with a human-readable last-seen timestamp.

**Acceptance Criteria — US-C3:**
- **Given** the Logs tab is open with > 20 entries,  
  **When** the user selects `agent = top_bets` and `severity = error`,  
  **Then** only entries matching both filters are shown; other agents' entries and non-error entries are hidden.

**Acceptance Criteria — US-C4:**
- **Given** an error-level log entry exists in the feed,  
  **When** it renders,  
  **Then** it has a red background tint or red left-border, and the severity label reads "ERROR" in red text.

**Acceptance Criteria — US-C5:**
- **Given** at least one auto-research run has completed (F15-D),  
  **When** the user clicks the "Research" sub-tab inside Logs,  
  **Then** a list of `pm_strategy_research_log` entries is shown, each with: date, source summary, strategy adjustments made (if any), and a link to the full finding text.

---

### F15-D: Auto-Research Integration

**Description:**  
The top-bets agent gains a nightly background research loop that runs through the existing AutoResearch scheduler. The loop uses an LLM + web-search tool to query public sources for winning Polymarket strategies, community alpha, and edge-finding techniques. Findings are distilled into structured strategy config deltas (adjustments to `min_edge_bps`, `kelly_cap`, category weights, confidence thresholds) which are stored in `pm_strategy_research_log` and optionally applied to `pm_strategies` after user review. A weekly digest is injected into the Morning Briefing PM section.

**User Stories:**

| ID | Story | Priority |
|---|---|---|
| US-D1 | As a trader, I want the agent to automatically research how people make money on Polymarket and incorporate those strategies, so my edge improves over time without manual effort. | P0 |
| US-D2 | As a trader, I want to see what the auto-research found this week in the Logs > Research panel, so I understand how the agent is evolving. | P1 |
| US-D3 | As a trader, I want the Weekly Briefing to include a "PM Research Digest" section summarising the top strategy insight from the past week, so I stay informed at a glance. | P1 |
| US-D4 | As a trader, I want proposed strategy config changes from research to require my explicit approval before they are applied to live strategies, so I remain in control. | P1 |

**Acceptance Criteria — US-D1:**
- **Given** the AutoResearch scheduler runs at its configured nightly time,  
  **When** the PM research sub-task is triggered,  
  **Then** it writes ≥ 1 row to `pm_strategy_research_log` with: `run_at`, `sources_queried` (JSON list of URLs/queries), `raw_findings` (text), `proposed_config_delta` (JSON), `applied` (bool, default false).

**Acceptance Criteria — US-D4:**
- **Given** a `pm_strategy_research_log` row has `proposed_config_delta` not null and `applied = false`,  
  **When** the user views it in the Research panel and clicks "Apply",  
  **Then** the relevant `pm_strategies` row is updated with the delta, `applied` is set to `true`, and a `pm_promotion_audit`-style record is written with `action = research_config_update`.

---

### Jurisdiction Banner Fix (non-feature, compliance copy update)

**Description:**  
The existing `JurisdictionBanner` component in `apps/dashboard/src/pages/polymarket/index.tsx` currently displays yellow/warning styling and copy that implies Polymarket is fully geo-blocked in the US. This is outdated as of 2024: sports and entertainment markets are accessible to US users; only political prediction markets retain restrictions. Additionally, with Robinhood Prediction Markets now the primary venue, the banner must explicitly confirm that Robinhood markets are fully available to US users. The banner should be updated to accurate, informational copy in blue/neutral styling. The attestation flow itself remains intact.

**Current copy (to be replaced):**
> "Polymarket is geo-blocked in the United States. Live trading is physically blocked until you record a current jurisdiction attestation. You are solely responsible for compliance with applicable law (see LEGAL.md)."  
> Color: `border-yellow-500/40`, `bg-yellow-500/10`, icon `text-yellow-400`

**New copy:**
> "Prediction Markets requires a jurisdiction attestation for Polymarket access. **Robinhood Prediction Markets are fully available to US users with no restrictions. US users can also trade Polymarket sports and entertainment markets freely; political prediction markets may have restrictions in your jurisdiction.** You are solely responsible for compliance with applicable law (see LEGAL.md)."  
> Color: `border-blue-500/40`, `bg-blue-500/10`, icon `text-blue-400` (use `Info` icon from lucide-react, not `AlertTriangle`)

**Acceptance Criteria:**
- **Given** a US user has not yet attested,  
  **When** they view the Prediction Markets page,  
  **Then** the banner displays the new blue informational styling and updated copy.
- **Given** a user has already attested (valid attestation on record),  
  **When** they view the Prediction Markets page,  
  **Then** the banner does not render (existing logic: `if data?.valid return null` — unchanged).
- The attestation dialog content and POST `/api/polymarket/jurisdiction/attest` flow are **not changed**.

---

### F15-E: "Prediction Markets" Tab Rename + Robinhood Venue

**Description:**  
The sidebar/nav tab currently labelled "Polymarket" is renamed to **"Prediction Markets"**. The page gains a venue selector pill row below the H1 header, and a new `RobinhoodPredictionsVenue` class is added implementing the existing `MarketVenue` ABC (same `scan()` / `aclose()` interface). A corresponding `RobinhoodPredictionsAdapter` broker is created for order routing. Robinhood operates in paper mode only for Phase 15.

**Robinhood Prediction Markets background (confirmed):**
- Launched 2024 under Robinhood Derivatives LLC; CFTC-regulated
- Covers sports, economics, elections, and entertainment events
- Fully US-accessible; no geo-block restrictions for US users
- API authentication: OAuth2 + device token (reuses user's existing Robinhood credentials)
- Prediction market endpoints under `/predictions/` namespace

**Architecture mapping:**
- `RobinhoodPredictionsVenue` → extends `MarketVenue` ABC (`services/connector-manager/src/venues/base.py`); `name = "robinhood_predictions"`; `scan()` yields `MarketRow` items with `venue="robinhood_predictions"`
- `RobinhoodPredictionsAdapter` → extends `BaseBroker`; lives in `services/connector-manager/src/brokers/robinhood_predictions/adapter.py`; follows pattern of `PolymarketBroker` (Phase 2)
- All existing `pm_*` tables already carry a `venue` VARCHAR field — no schema changes needed for venue routing
- `DiscoveryScanner` skips `RobinhoodPredictionsVenue` with `NotConfiguredError` if credentials are absent (same pattern as `KalshiVenue`)

**UI — Venue selector:**
```
[Prediction Markets]
[● Robinhood]  [○ Polymarket]  [○ Kalshi*]
                                            * coming soon
```
- ● = active/enabled (has credentials, scan results available)
- ○ = disabled/stub (no credentials or not yet implemented)
- Selecting a pill filters the Top Bets, Markets, Orders, and Positions tabs to that venue's data
- Default active: Robinhood (if credentials present); falls back to Polymarket

**User Stories:**

| ID | Story | Priority |
|---|---|---|
| US-E1 | As a user, I see a tab called "Prediction Markets" in the sidebar, not "Polymarket". | P0 |
| US-E2 | As a user, I can toggle which venue's markets the scanner uses (Robinhood primary, Polymarket secondary). | P0 |
| US-E3 | As a user, when I accept a bet from a Robinhood market, the order is placed on Robinhood (not Polymarket CLOB). | P0 |
| US-E4 | As a user, the Top Bets panel shows which venue each bet is from (Robinhood vs Polymarket badge). | P0 |
| US-E5 | As a user, I see an informational note that Robinhood bets are paper-mode only in this phase. | P1 |

**Acceptance Criteria — US-E1:**
- **Given** the dashboard is loaded,  
  **When** the user looks at the sidebar navigation,  
  **Then** the nav item reads "Prediction Markets" and `AppShell.tsx` no longer contains the label "Polymarket" in the nav.

**Acceptance Criteria — US-E2:**
- **Given** the Prediction Markets page is open,  
  **When** the user selects the "Polymarket" venue pill,  
  **Then** all market lists, top bets, and scanning activity filter to `venue = "polymarket"` records.
- **Given** the user returns to the "Robinhood" venue pill,  
  **Then** all market lists filter to `venue = "robinhood_predictions"` records.

**Acceptance Criteria — US-E3:**
- **Given** a top-bet recommendation has `venue = "robinhood_predictions"`,  
  **When** the user clicks "Accept",  
  **Then** the order is routed to `RobinhoodPredictionsAdapter.place_order()`, **not** the Polymarket CLOB; the order row in `pm_orders` has `venue = "robinhood_predictions"`.

**Acceptance Criteria — US-E4:**
- **Given** the Top Bets panel is visible with mixed-venue recommendations,  
  **When** the panel renders,  
  **Then** each `TopBetCard` displays a venue badge: green `"RHPD"` for Robinhood, purple `"PM"` for Polymarket. The Markets table gains a "Venue" badge column with the same badge styles.

**Acceptance Criteria — US-E5:**
- **Given** the user has selected Robinhood as the active venue,  
  **When** they view the Top Bets panel or attempt to accept a bet,  
  **Then** a visible "(Paper mode — live execution coming in Phase 16)" label or tooltip is shown on Robinhood bets.

---

### F15-F: LLM Inference Pipeline for Prediction Market Scoring

**Description:**  
The intelligence core upgrade for Phase 15. Instead of relying solely on the heuristic `TopBetScorer` (price math + F9 score), the system ingests historical resolved prediction markets, embeds them in a vector store, and uses an LLM RAG pattern to score new candidate markets by analogy to similar past events. The heuristic scorer remains as an automatic fallback when the LLM is unavailable or the embedding store is empty.

---

#### F15-F1: Historical Data Ingestion

**Description:**  
On first activation of the "Enable Prediction Markets" toggle in Settings, a one-time historical data pull runs as a background job. Subsequent manual re-ingests can be triggered via API.

**Sources:**
- Robinhood Prediction Markets: all past resolved events, outcomes, prices at resolution, final YES/NO price history
- Kalshi historical markets API: publicly available past market data
- Polymarket Gamma REST: historical resolved markets (extending existing `polymarket_loader.py` pattern)

**Implementation path:**  
New loader: `services/backtest-runner/src/loaders/robinhood_predictions_loader.py` — follows exact pattern of existing `polymarket_loader.py`.

**User Stories:**

| ID | Story | Priority |
|---|---|---|
| US-F1 | As a user, when I first enable Prediction Markets, historical data is pulled automatically in the background without blocking the UI. | P0 |
| US-F2 | As a user, I can see ingestion progress (markets loaded, % complete) in Settings. | P1 |

**Acceptance Criteria — US-F1:**
- **Given** the user enables the "Enable Prediction Markets" toggle for the first time,  
  **When** the toggle is saved,  
  **Then** a background job starts and `pm_historical_markets` is populated with ≥ 50 resolved markets within 5 minutes; a progress indicator is visible in Settings.

---

#### F15-F2: Embedding + Vector Store

**Description:**  
After ingestion, each historical market is embedded using the existing LLM client (`shared/llm/`) with a structured text representation. Embeddings are stored in `pm_market_embeddings`. If the pgvector extension is present, the `embedding` column uses `vector(1536)`; otherwise it falls back to JSONB array with Python-side cosine similarity.

**Text template for embedding:**
```
{question}
Category: {category}
Outcome: {winning_outcome}
Key factors: {community_discussion_summary}
```

**New utility:** `shared/polymarket/embedding_store.py` — `EmbeddingStore` class with:
- `upsert(market_id: UUID, text: str) -> None`
- `search(query_text: str, k: int = 10) -> list[SimilarMarket]`
- `SimilarMarket` dataclass: `historical_market_id`, `question`, `winning_outcome`, `peak_yes_price`, `similarity_score`

**Acceptance Criteria:**
- **Given** `pm_historical_markets` has ≥ 1 record,  
  **When** the embedding job runs,  
  **Then** `pm_market_embeddings` has a corresponding row with a non-null `embedding` field.
- **Given** `EmbeddingStore.search("Will the Fed cut rates in 2025?", k=10)` is called,  
  **When** the store has ≥ 10 historical markets,  
  **Then** 10 `SimilarMarket` items are returned ordered by cosine similarity descending.

---

#### F15-F3: LLM Inference Scoring

**Description:**  
New class `LLMPredictionScorer` in `agents/polymarket/top_bets/llm_scorer.py` replaces the heuristic `TopBetScorer` as the primary scoring method. Falls back to heuristic automatically. Config flag `use_llm_scorer: true` in `agents/polymarket/top_bets/config.yaml`.

**Scoring algorithm per candidate market:**
1. Build query text: `"{question}\nCategory: {category}\nCurrent YES price: {yes_price}\nTime to resolution: {days} days"`
2. Retrieve top-10 similar historical markets via `EmbeddingStore.search(query_text, k=10)`
3. Format few-shot examples: `"Similar past market: '{question}' → Outcome: {winning_outcome}, Peak YES price: {peak_price}"`
4. Send to LLM with structured prompt (see below)
5. Parse JSON response; compute `edge_bps = abs(yes_probability - yes_price) * 10000`

**LLM prompt template:**
```
You are a prediction market analyst. Based on these similar historical markets and their outcomes,
score the probability that the following market resolves YES.

Historical examples:
{similar_markets_formatted}

Market to score: {query_text}

Return JSON: {"yes_probability": 0.0-1.0, "confidence": 0-100, "reasoning": "2-3 sentences", "edge_bps": int}
```

**User Stories:**

| ID | Story | Priority |
|---|---|---|
| US-F3 | As a user, the Top Bets agent uses LLM reasoning — not just price math — to score and rank markets. | P0 |
| US-F4 | As a user, each top-bet card shows the AI reasoning (2–3 sentences) explaining why it was recommended. | P0 |
| US-F5 | As a user, each top-bet card shows up to 3 similar historical markets that informed the AI recommendation (expandable). | P1 |
| US-F6 | As a user, when the LLM is unavailable, the system automatically falls back to the heuristic scorer and logs a warning. | P0 |

**Acceptance Criteria — US-F3 / US-F4:**
- **Given** the embedding store has ≥ 10 records and the LLM is reachable,  
  **When** the top-bets agent scores a candidate market,  
  **Then** `LLMPredictionScorer` is invoked; the resulting `pm_top_bets` row has a non-null `reasoning` field containing 2–3 sentences.

**Acceptance Criteria — US-F5:**
- **Given** a top-bet card is rendered in the UI,  
  **When** the user clicks "AI Reasoning",  
  **Then** an expandable section shows the LLM reasoning text and an accordion with up to 3 `SimilarMarket` items (question, outcome, peak YES price).

**Acceptance Criteria — US-F6:**
- **Given** the LLM client returns an error or times out,  
  **When** the top-bets agent scores a market,  
  **Then** `TopBetScorer` (heuristic) is used instead; a `warn`-severity row is written to `pm_agent_activity_log` with `action = "llm_scorer_fallback"`.

---

#### F15-F4: Model Evaluation + Best-Model Selection

**Description:**  
The system periodically evaluates the LLM scorer retrospectively against a held-out set of resolved historical markets. Brier scores are computed and stored. The admin can view comparative scores and manually activate the preferred model. The Logs tab shows a "Model Performance" card.

**Brier score**: `(1/N) * Σ (forecast_probability - outcome)²` where `outcome ∈ {0, 1}`.

**User Stories:**

| ID | Story | Priority |
|---|---|---|
| US-F7 | As a user, I can see the current model's Brier score compared to the heuristic baseline in the Logs tab. | P1 |
| US-F8 | As a user (admin), I can activate a preferred scoring model from the Logs > Model Performance card. | P2 |

**Acceptance Criteria — US-F7:**
- **Given** at least one model evaluation has been run,  
  **When** the user opens the Logs tab,  
  **Then** a "Model Performance" card shows: active model type (`llm_rag` or `heuristic`), Brier score, accuracy %, and last evaluation date.
- **Given** both model types have been evaluated,  
  **When** the card renders,  
  **Then** both rows are shown side-by-side for comparison.

**Acceptance Criteria — US-F8:**
- **Given** two model evaluations exist (`llm_rag` and `heuristic`),  
  **When** the admin calls `POST /api/polymarket/model-evaluations/activate` with `{"model_type": "llm_rag"}`,  
  **Then** the specified model's `is_active` is set to `true` in `pm_model_evaluations` and all others set to `false`; subsequent top-bets scoring cycles use the activated model.

---

## 6. Constraints (from user)

| Constraint | Detail |
|---|---|
| Conservative bet sizing | The agent should prefer **a few high-confidence bets** (2–5) over many mediocre ones. Volume over quantity is an anti-goal. |
| Manual-first flow | Phase 15 is Accept/Reject manual. Full automation is explicitly deferred. |
| 24/7 agent uptime | The top-bets scanning agent must run continuously, not on a fixed cron schedule only. |
| Robinhood is primary venue | Robinhood Prediction Markets are the default active venue; Polymarket is secondary. |
| Robinhood paper mode only | Robinhood order placement is paper mode in Phase 15; live execution is Phase 16. |
| Build on existing tabs | Two new tabs (Chat, Logs) appended after Risk — do not reorganize existing tabs. |
| Auto-research is default-on | The nightly research loop should be enabled by default for PM agents, not opt-in. |
| LLM scorer is default-on | When the embedding store has ≥ 10 records, `use_llm_scorer` defaults to `true` in config; heuristic fallback is automatic. |
| JSONB embeddings for v1.0 | Do not require pgvector extension in Phase 15; use JSONB + Python cosine similarity. pgvector upgrade is documented for v1.2. |
| No fine-tuning | RAG-only LLM inference; no gradient updates or weight modifications to any model. |

---

## 7. Open Questions

*None remain from user — the request was explicit. The following are flagged for Atlas to resolve during architecture:*

1. **Chat transport**: SSE (server-sent events) vs. long-poll vs. chunked HTTP — the PRD calls for HTTP; Atlas to decide exact mechanism.
2. **Agent scheduler**: The top-bets agent runs "24/7" — Atlas to determine whether this is a long-running asyncio loop inside the OpenClaw worker or a high-frequency cron (e.g., every 15 min). The PRD is agnostic.
3. **Reject feedback loop**: How rejected bets influence future scoring is left to Atlas/Devin — the PRD only requires the `rejected_reason` is stored; behavioral adaptation is a future phase.
4. **Auto-research config apply safety**: Atlas to define whether config deltas are applied per-strategy or globally, and what validation guards exist.
5. **Robinhood API credential storage**: Atlas to determine how Robinhood OAuth2 + device tokens are stored and refreshed (likely alongside existing broker credential pattern in connector-manager config).
6. **Embedding job scheduling**: Atlas to decide whether embedding generation runs immediately after ingestion, on a nightly schedule, or on-demand. The PRD requires only that embeddings exist before the LLM scorer first runs.
7. **Brier score evaluation cadence**: Atlas to set how often retrospective model evaluation runs (suggested: weekly or after each batch ingestion).

---

## 8. Dependencies on Existing Phases

| Existing Asset | How Phase 15 Uses It |
|---|---|
| `agents/polymarket/` | New `top_bets/` sub-agent added alongside `sum_to_one_arb/` and `cross_venue_arb/` |
| `shared/polymarket/resolution_risk.py` | Top-bets agent calls `score_market()` for each candidate; `tradeable=false` markets are excluded |
| `shared/polymarket/promotion_gate.py` | Accepted bets that pass paper → live promotion use existing gate; no changes required |
| `services/connector-manager/src/venues/base.py` | `RobinhoodPredictionsVenue` extends `MarketVenue` ABC; `name = "robinhood_predictions"`; same `scan()` / `aclose()` interface |
| `services/connector-manager/src/venues/kalshi_venue.py` | Pattern reference for `RobinhoodPredictionsVenue` stub (raises `NotConfiguredError` if credentials absent) |
| `services/connector-manager/src/brokers/polymarket/adapter.py` | Pattern reference for `RobinhoodPredictionsAdapter` broker (same `BaseBroker` interface) |
| `services/connector-manager/src/brokers/polymarket/` | Top-bets agent reads market data via existing Gamma REST adapter; does not add new connector code |
| `services/message-ingestion/src/collectors/polymarket/` | Top-bets agent subscribes to existing Redis Streams for real-time price signals; no new collectors |
| `services/backtest-runner/src/loaders/polymarket_loader.py` | Pattern reference for `robinhood_predictions_loader.py` (historical data ingestion) |
| `shared/llm/` | `EmbeddingStore` and `LLMPredictionScorer` use the existing LLM client for both embedding generation and inference |
| `apps/api/src/routes/polymarket.py` | New endpoints appended to existing router; file is extended, not replaced |
| `shared/db/models/polymarket.py` | New ORM models appended; migration `032_pm_phase15.py` created |
| `apps/dashboard/src/pages/polymarket/index.tsx` | Renamed to Prediction Markets; 2 new tab components + venue selector + updated `JurisdictionBanner`; file is extended |
| `apps/dashboard/src/components/AppShell.tsx` | Nav item "Polymarket" → "Prediction Markets" |
| `apps/dashboard/src/pages/AutoResearch.tsx` | No changes; top-bets research loop registers with the existing AutoResearch scheduler via its existing task-registration API |
| `apps/api/src/routes/polymarket.py` (briefing) | `GET /api/polymarket/briefing/section` extended to include PM research digest in its payload |

---

## 9. DB Schema Additions (Phase 15 only)

> Migration file: `shared/db/migrations/032_pm_phase15.py`

### `pm_top_bets`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `market_id` | UUID FK → pm_markets.id RESTRICT | |
| `recommendation_date` | DATE NOT NULL | Date the recommendation was generated (UTC) |
| `side` | VARCHAR(4) NOT NULL | `YES` or `NO` |
| `confidence_score` | SMALLINT NOT NULL | 0–100 |
| `edge_bps` | SMALLINT NOT NULL | Estimated edge in basis points |
| `reasoning` | TEXT NOT NULL | 2–3 sentences; populated by LLM scorer or heuristic |
| `scorer_type` | VARCHAR(16) NOT NULL DEFAULT `heuristic` | `llm_rag` or `heuristic` — which scorer produced this recommendation |
| `similar_markets_json` | JSONB | Top-3 similar historical markets used by LLM scorer; null if heuristic |
| `status` | VARCHAR(16) NOT NULL DEFAULT `pending` | `pending` / `accepted` / `rejected` / `expired` |
| `rejected_reason` | TEXT | Optional; populated on reject |
| `accepted_order_id` | UUID FK → pm_orders.id SET NULL | Populated when accepted |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| `updated_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

*Index:* `(recommendation_date, status)`, `(market_id, recommendation_date)`

---

### `pm_chat_messages`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `session_id` | UUID NOT NULL | Groups messages into a conversation session |
| `role` | VARCHAR(16) NOT NULL | `user` or `assistant` |
| `content` | TEXT NOT NULL | Raw message text |
| `bet_recommendation` | JSONB | Populated when agent recommends a trade (market_id, side, confidence_score, edge_bps) |
| `accepted_order_id` | UUID FK → pm_orders.id SET NULL | Populated if user accepts inline |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

*Index:* `(session_id, created_at DESC)`

---

### `pm_agent_activity_log`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `agent_type` | VARCHAR(32) NOT NULL | `top_bets` / `sum_to_one_arb` / `cross_venue_arb` |
| `severity` | VARCHAR(8) NOT NULL | `info` / `warn` / `error` |
| `action` | VARCHAR(64) NOT NULL | e.g., `scan_started`, `market_scored`, `recommendation_generated`, `heartbeat` |
| `detail` | JSONB | Arbitrary structured payload |
| `markets_scanned_today` | INTEGER | Snapshot at time of log entry (for heartbeat rows) |
| `bets_generated_today` | INTEGER | Snapshot at time of log entry (for heartbeat rows) |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

*Index:* `(agent_type, created_at DESC)`, `(severity, created_at DESC)`  
*Retention:* Rows older than 30 days can be archived; this is an ops concern for Atlas.

---

### `pm_strategy_research_log`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `run_at` | TIMESTAMPTZ NOT NULL | When the research run executed |
| `sources_queried` | JSONB NOT NULL | List of URLs / search queries used |
| `raw_findings` | TEXT NOT NULL | Full LLM-distilled text of discovered strategies |
| `proposed_config_delta` | JSONB | Structured delta: `{min_edge_bps: +5, kelly_cap: -0.05, ...}` |
| `applied` | BOOLEAN NOT NULL DEFAULT false | |
| `applied_at` | TIMESTAMPTZ | |
| `applied_by_user_id` | UUID FK → users.id SET NULL | |
| `notes` | TEXT | Optional operator annotation |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

*Index:* `(run_at DESC)`, `(applied, run_at DESC)`

---

### `pm_historical_markets` *(new — F15-F1)*

> Stores resolved historical prediction markets ingested from all venues for RAG embedding and model evaluation.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `venue` | VARCHAR(32) NOT NULL | `robinhood_predictions` / `polymarket` / `kalshi` |
| `venue_market_id` | VARCHAR(255) NOT NULL | Venue's own market identifier |
| `question` | TEXT NOT NULL | Full market question text |
| `category` | VARCHAR(64) | e.g., `sports`, `economics`, `elections`, `entertainment` |
| `description` | TEXT | Optional extended description |
| `outcomes_json` | JSONB | `[{label: str, winning: bool}]` — all outcome options |
| `winning_outcome` | VARCHAR(255) | Label of the outcome that resolved true |
| `resolution_date` | DATE | UTC date of resolution |
| `price_history_json` | JSONB | `[{ts: ISO8601, yes_price: float, no_price: float}]` |
| `community_discussion_summary` | TEXT | LLM-generated summary of community reasoning; generated during ingestion |
| `volume_usd` | FLOAT | Total trading volume in USD |
| `liquidity_peak_usd` | FLOAT | Peak liquidity depth in USD |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| `updated_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

*Unique constraint:* `(venue, venue_market_id)`  
*Index:* `(venue, category)`, `(resolution_date DESC)`

---

### `pm_market_embeddings` *(new — F15-F2)*

> Stores embedding vectors for historical markets. Supports pgvector upgrade in v1.2; v1.0 uses JSONB.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `historical_market_id` | UUID FK → pm_historical_markets.id ON DELETE CASCADE | |
| `embedding` | JSONB NOT NULL | List of floats (1536-dim for OpenAI ada-002); pgvector upgrade path: `vector(1536)` in v1.2 |
| `model_used` | VARCHAR(64) NOT NULL | e.g., `text-embedding-ada-002` |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

*Index:* `(historical_market_id)` (unique), `(model_used, created_at DESC)`

---

### `pm_model_evaluations` *(new — F15-F4)*

> Stores Brier scores and accuracy metrics for each model type evaluated against held-out historical markets.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `model_type` | VARCHAR(32) NOT NULL | `llm_rag` or `heuristic` |
| `brier_score` | FLOAT | `(1/N) * Σ(forecast - outcome)²`; lower is better |
| `accuracy` | FLOAT | % of markets where model's top probability matched actual outcome |
| `sharpe_proxy` | FLOAT | Simulated return / std-dev of returns on held-out set |
| `num_markets_tested` | INT | Number of resolved markets in evaluation set |
| `is_active` | BOOLEAN NOT NULL DEFAULT false | True for the currently-used scoring model |
| `evaluated_at` | TIMESTAMPTZ NOT NULL | When evaluation ran |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

*Index:* `(model_type, evaluated_at DESC)`, `(is_active)`  
*Constraint:* At most one row with `is_active = true` per `model_type` (enforced in application layer).

---

## 10. API Additions (Phase 15 only)

All new endpoints are appended to `apps/api/src/routes/polymarket.py` under the existing `/api/polymarket` router prefix.

```
# F15-A: Top Bets
GET  /api/polymarket/top-bets
     ?date=today|<YYYY-MM-DD>
     &min_confidence=<int 0-100, default 60>
     &category=<string, optional>
     &venue=<robinhood_predictions|polymarket|all, default all>
     &limit=<int, default 10, max 25>
     → list[PMTopBetOut]

POST /api/polymarket/top-bets/{bet_id}/accept
     body: {} (no payload required)
     → { order_id: UUID, status: "accepted" }

POST /api/polymarket/top-bets/{bet_id}/reject
     body: { rejected_reason?: string }
     → { status: "rejected" }

GET  /api/polymarket/top-bets/{bet_id}/reasoning
     → { reasoning: string, scorer_type: str, similar_markets: list[SimilarMarket] }
     # Full LLM reasoning + similar historical markets used for this recommendation

# F15-B: Chat
POST /api/polymarket/chat
     body: { session_id: UUID, message: string }
     → { session_id: UUID, message_id: UUID, response: string, bet_recommendation?: BetRecommendation }
     (streaming response via SSE or chunked — Atlas to decide mechanism)

GET  /api/polymarket/chat/history
     ?session_id=<UUID>
     &limit=<int, default 50>
     → list[PMChatMessageOut]

DELETE /api/polymarket/chat/history
     body: { session_id: UUID }
     → { deleted: int }

# F15-C: Logs
GET  /api/polymarket/agents/activity
     ?agent=<top_bets|sum_to_one_arb|cross_venue_arb|all>
     &severity=<info|warn|error|all>
     &since=<ISO-8601 timestamp>
     &limit=<int, default 100, max 500>
     → list[PMAgentActivityOut]

GET  /api/polymarket/agents/health
     → list[PMAgentHealthOut]
     (one record per agent: agent_type, is_running, last_heartbeat_at, markets_scanned_today, bets_generated_today)

# F15-D: Auto-Research
GET  /api/polymarket/research
     ?limit=<int, default 20>
     &applied=<true|false|all>
     → list[PMStrategyResearchLogOut]

POST /api/polymarket/research/{log_id}/apply
     body: {}
     → { applied: true, strategies_updated: int }

# F15-E: Venue management
GET  /api/polymarket/venues
     → list[VenueStatusOut]  # { venue, display_name, is_enabled, is_configured, market_count }

POST /api/polymarket/venues/{venue}/enable
     body: {}
     → { venue: str, is_enabled: true }

POST /api/polymarket/venues/{venue}/disable
     body: {}
     → { venue: str, is_enabled: false }

# F15-F: LLM Inference Pipeline
GET  /api/polymarket/historical-markets
     ?venue=<robinhood_predictions|polymarket|kalshi|all>
     &category=<string, optional>
     &limit=<int, default 50, max 500>
     → list[PMHistoricalMarketOut]

POST /api/polymarket/historical-markets/ingest
     body: { venue?: str }  # omit for all venues
     → { job_id: UUID, status: "started" }

GET  /api/polymarket/model-evaluations
     → list[PMModelEvaluationOut]  # all rows ordered by evaluated_at DESC

POST /api/polymarket/model-evaluations/activate
     body: { model_type: str }  # "llm_rag" or "heuristic"
     → { model_type: str, is_active: true }
```

---

## 11. UI Additions (Phase 15 only)

### Tab + Page Rename (F15-E)

| Location | Old Label | New Label | File |
|---|---|---|---|
| Sidebar nav item | "Polymarket" | "Prediction Markets" | `apps/dashboard/src/components/AppShell.tsx` |
| Page H1 | "Polymarket" | "Prediction Markets" | `apps/dashboard/src/pages/polymarket/index.tsx` |
| Page subtitle | (existing) | (updated to reflect multi-venue) | same |
| Browser `<title>` | "Polymarket" | "Prediction Markets" | same |

### Venue Selector (F15-E)

Placed **below the H1 header** and **above the `JurisdictionBanner`**.  

```
[Prediction Markets]
──────────────────────────────────────────────────────
[● Robinhood]   [○ Polymarket]   [○ Kalshi *]
                                       * coming soon
──────────────────────────────────────────────────────
[JurisdictionBanner]
```

- `VenueSelectorPills` component in `apps/dashboard/src/pages/polymarket/components/VenueSelectorPills.tsx`
- ● = enabled (has credentials, green ring), ○ = disabled (grey), * = coming-soon badge
- Selecting a pill calls `POST /api/polymarket/venues/{venue}/enable` and sets a `activeVenue` context value consumed by all sub-tabs
- Default pill: Robinhood if configured, else Polymarket

### New Tabs (in `apps/dashboard/src/pages/polymarket/index.tsx`)

| Tab | Position | Component |
|---|---|---|
| **Chat** | 8th (after Risk) | `ChatTab` |
| **Logs** | 9th (after Chat) | `LogsTab` |

The `TabsList` in `PredictionMarketsPage` gains two new `TabsTrigger` entries; the `TabsContent` section gains two corresponding `TabsContent` blocks. No existing tabs are moved or removed.

### New Components

| Component | Location | Purpose |
|---|---|---|
| `VenueSelectorPills` | Page header, above banner | Three-pill venue selector; controls `activeVenue` context |
| `TopBetsPanel` | Top of Prediction Markets page (all tabs see it) | Shows ranked top-bets list with Accept/Reject actions; filters by `activeVenue` |
| `TopBetCard` | Child of `TopBetsPanel` | Full card: venue badge (RHPD/PM), question, YES%/NO% or multi-outcome percentages, side badge, confidence bar, edge, "AI Reasoning" expandable, "Similar Markets" accordion, Accept/Reject buttons, paper-mode label (Robinhood only) |
| `VenueBadge` | Child of `TopBetCard`, `MarketsTable` | `"RHPD"` in green / `"PM"` in purple / `"KAL"` in blue |
| `AIReasoningSection` | Child of `TopBetCard` | Expandable section: LLM reasoning text + `SimilarMarketsAccordion` |
| `SimilarMarketsAccordion` | Child of `AIReasoningSection` | Shows top-3 similar historical markets: question, outcome, peak YES price |
| `ChatTab` | New tab component | Full-height chat window: message list + input box + send button |
| `ChatBubble` | Child of `ChatTab` | Single message bubble (user = right-aligned, agent = left-aligned); agent bubbles may contain `AcceptBetButton` |
| `AcceptBetButton` | Child of `ChatBubble` | Inline action button; calls `POST /top-bets/:id/accept` (or creates order directly if message contains recommendation JSON) |
| `LogsTab` | New tab component | Agent health cards + activity feed + Research sub-tab + Model Performance card |
| `AgentHealthCard` | Child of `LogsTab` | Health card per agent: status badge, last heartbeat, scan count, bet count |
| `ActivityFeedRow` | Child of `LogsTab` | Single log entry with severity color coding |
| `ResearchSubPanel` | Sub-tab inside `LogsTab` | List of `pm_strategy_research_log` entries with Apply action |
| `ModelPerformanceCard` | Child of `LogsTab` | Shows Brier scores + accuracy per model type; "Activate" button per row |

### `JurisdictionBanner` Update
- Replace `AlertTriangle` icon with `Info` from `lucide-react`
- Replace all `yellow-*` Tailwind classes with `blue-*` equivalents
- Update copy as specified in the jurisdiction fix section above
- No changes to the attestation dialog or the POST endpoint

### `MarketsTab` Update
- Add "Venue" badge column to the markets table showing `VenueBadge` for each row
- Column header: "Venue"; sortable

### Settings Page Addition (F15-F)
- New toggle: **"Enable Prediction Markets"** — when first toggled ON, triggers `POST /api/polymarket/historical-markets/ingest`
- Progress indicator below toggle shows ingestion job status (`job_id` polled via `GET /api/polymarket/historical-markets?limit=1`)

---

## 12. Research & Sources

The following sources were reviewed to inform the strategy direction, jurisdiction status, and Robinhood venue sections of this PRD:

1. **Polymarket US Access Status (2024)** — Multiple community posts and Polymarket blog updates confirm sports/entertainment markets opened to US users in 2024 while political markets retained restrictions.  
   *Source:* General knowledge of Polymarket's public announcement history; to be verified by Atlas/Devin against Polymarket's current Terms of Service at `https://polymarket.com/tos` before banner copy is finalised.

2. **Robinhood Prediction Markets launch (2024)** — Robinhood launched prediction markets under Robinhood Derivatives LLC, CFTC-regulated, covering sports, economics, elections, and entertainment. Fully US-accessible with no geo-block restrictions. Authentication uses OAuth2 + device token (existing Robinhood credential flow). API endpoints under `/predictions/` namespace.  
   *Source:* Confirmed by user (PM conversation); public Robinhood product announcement coverage. Atlas/Devin to verify current API namespace and auth flow against Robinhood developer docs before implementing `RobinhoodPredictionsAdapter`.

3. **RAG-based prediction scoring prior art** — Using historical resolved market data as few-shot retrieval context for LLM probability estimation is a recognized approach in forecasting research. Brier score is the standard calibration metric for probabilistic forecasters.  
   *Source:* Derived from existing forecasting literature; the composite signal architecture in F15-A already contains the embedding-retrieval pattern implicitly. EmbeddingStore design follows patterns in `shared/llm/` (confirmed in codebase recon).

4. **Winning prediction market strategies (community alpha)** — The auto-research agent (F15-D) is designed to continuously harvest these. Common strategies documented in forums include: (a) liquidity-provision on high-volume markets, (b) calibrated probability scoring vs. market consensus, (c) latency-sensitive resolution-news arbitrage, (d) Kelly-sized positions on low-liquidity mispriced markets. These inform the composite scoring signals in F15-A.  
   *Source:* Derived from the existing agent archetype names (`sum_to_one_arb`, `cross_venue_arb`) and the F9 resolution-risk scorer already in the codebase — indicating prior architectural alignment with these strategies.

5. **AutoResearch scheduler** — Confirmed in `apps/dashboard/src/pages/AutoResearch.tsx`: scheduler runs nightly, exposes `triggerSupervisor()` and `triggerEodAnalysis()` hooks; F15-D plugs into this pattern.

6. **Existing DB models and API endpoints** — Confirmed via codebase recon (8 `pm_*` tables, 18 endpoints, 3 migrations). Phase 15 v2.0 adds 7 new tables and ~20 new endpoints without modifying existing ones.

7. **`MarketVenue` ABC and `KalshiVenue` stub pattern** — Confirmed in `services/connector-manager/src/venues/base.py` and `kalshi_venue.py`. `RobinhoodPredictionsVenue` follows the same stub/real implementation pattern: raises `NotConfiguredError` if credentials absent; implements `scan()` as async generator yielding `MarketRow` with `venue="robinhood_predictions"`.

8. **`SumToOneArbAgent` pattern** — Confirmed in `agents/polymarket/sum_to_one_arb/agent.py`. All new F15 agents follow the same protocol-injection, `run_cycle()`, and kill-switch pattern. `LLMPredictionScorer` is injected as a collaborator (not subclassed) to maintain testability.

---

*End of PRD: Prediction Markets Phase 15 (v2.0)*
