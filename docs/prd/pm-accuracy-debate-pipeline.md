# PRD: Bull/Bear/Judge Debate Pipeline (F-ACC-1)

**Feature ID:** F-ACC-1  
**Version:** 1.0  
**Status:** Draft  
**Author:** Nova (PM)  
**Parent PRD:** `docs/prd/polymarket-phase15.md` (Phase 15 — LLM Inference, F15-F3)  
**Phase target:** Post-Phase-15 accuracy enhancement  
**Date:** 2025-07-10  

---

## 1. Problem

Phase 15 introduces `LLMPredictionScorer` — a single-pass LLM call that, given a candidate prediction market and 10 similar historical markets, returns `{yes_probability, confidence, reasoning, edge_bps}`. While this is a significant leap over heuristic scoring, **single-pass LLM inference on ambiguous markets has a well-documented overconfidence bias**: the model anchors on its first framing of the question and rarely stress-tests its own reasoning before outputting a probability.

This failure mode is especially acute on:
- **Political/macro markets** where the "obvious" framing is often wrong (e.g., "Will X resign?" feels like a YES — but historical base rates say no).
- **Markets with a strong narrative pull** where media coverage inflates perceived YES probability.
- **Low-liquidity markets** where the current market price is itself a noisy prior the LLM may over-weight.

The result is that `LLMPredictionScorer`'s probability estimates, while better than heuristics, can systematically over-recommend confident YES bets and under-weigh the steelman case for NO. Users who accept these recommendations without scrutiny may be exposed to unmodelled downside risk.

**The gap:** There is no mechanism in the current pipeline that forces the model to articulate the strongest possible counter-argument before locking in a probability estimate.

---

## 2. Target Users & Jobs-to-Be-Done

| User Segment | Job-to-Be-Done |
|---|---|
| **Solo discretionary trader (primary)** | "Show me not just a probability, but *why someone smart might disagree* — I want to see both sides before I accept a bet." |
| **Evidence-based trader** | "I want AI recommendations that have been adversarially stress-tested, not just the first thing the model thought of." |
| **Cautious / risk-aware trader** | "I want to know how strong the bear case is before I commit money — a single bull summary isn't enough." |
| **Curious learner** | "I learn from reading the Bull vs Bear arguments even on bets I don't take — it teaches me how to think about markets." |

---

## 3. Goals & Non-Goals

### Goals
- Replace the single-pass `LLMPredictionScorer` call with a **3-agent sequential debate pipeline** (`DebatePipelineScorer`) that produces a richer, adversarially-grounded probability estimate.
- **Reduce overconfidence** on ambiguous/political markets by forcing a dedicated counter-argument pass before the final estimate.
- **Surface the debate** in the `TopBetCard` UI so the user can inspect Bull vs. Bear reasoning, not just the final verdict.
- Provide a **config flag** (`use_debate_pipeline`) so operators can opt out and fall back to single-pass scoring.
- Store debate artefacts in the database for auditability and future model evaluation.
- Expose the full debate transcript via a dedicated API endpoint for the Chat tab's "Show debate" feature.

### Non-Goals
- **Real-time streaming of the debate to the UI** — debate runs as a background job; the UI shows results once all three passes complete.
- **User-triggered re-debate** — users cannot request a fresh debate run on an already-scored market in this phase.
- **More than 3 agents** — Bull, Bear, Judge only; no additional specialist or domain-expert agents in this phase.
- **Fine-tuning any LLM** on debate quality — prompt engineering only; no weight updates.
- **Changing the `LLMPredictionScorer` interface** — `DebatePipelineScorer` is a **drop-in replacement** with the same external interface.
- **Debate for every market** — debate runs only on the top-20 candidates by heuristic pre-score; single-pass is used for the rest.
- **WebSocket streaming of debate steps** — not in scope; full WS upgrade is a future phase.
- **Multi-turn debate** (Bull rebuts Bear's rebuttal, etc.) — single exchange only; multi-round is a future phase.

---

## 4. Success Metrics

| # | Metric | Target | Measurement Method |
|---|---|---|---|
| M1 | Debate pipeline Brier score vs. single-pass LLM Brier score on held-out resolved markets | Debate Brier score ≤ single-pass Brier score | Retrospective evaluation against `pm_historical_markets`; see F15-F4 pattern |
| M2 | User "accept" rate on debate-scored bets vs. single-pass scored bets | Debate accept rate ≥ single-pass accept rate (proxy for user trust) | `pm_top_bets.status` aggregate by `scorer_type` |
| M3 | p95 latency for a full 3-pass debate cycle per market | ≤ 30 seconds | Agent activity log timestamp delta from debate start to Judge output |
| M4 | % of debate-scored `pm_top_bets` rows with all 5 debate fields populated (`bull_argument`, `bear_argument`, `debate_summary`, `bull_score`, `bear_score`) | ≥ 95% when debate pipeline is active and LLM is reachable | DB completeness query |
| M5 | % of `TopBetCard` renders that successfully expand the Debate section | ≥ 99% (no blank/empty debate panels when data is present) | Frontend error tracking |
| M6 | Debate pipeline does not increase daily token cost by more than 4× vs. single-pass, net of the top-20 candidate filter | ≤ 4× single-pass token spend | LLM API usage logs |

---

## 5. User Stories

| ID | Story | Priority |
|---|---|---|
| US-ACC1-1 | As a trader, I want each top-bet recommendation to include a Bull argument, a Bear argument, and a Judge verdict, so I can see both sides of the trade before deciding. | P0 |
| US-ACC1-2 | As a trader, I want the `TopBetCard` to show an expandable "Debate" section with the Bull case (green), Bear case (red), Judge summary, and Bull/Bear strength scores (0–10), so I can visually assess argument quality at a glance. | P0 |
| US-ACC1-3 | As a trader, I want the final probability estimate and confidence score to be produced by the Judge — who has read both sides — rather than a single-pass model, so I can trust it has been stress-tested. | P0 |
| US-ACC1-4 | As a trader using the Chat tab, I want to click a "Show debate" button on any bet the agent mentions, so I can read the full Bull/Bear/Judge debate transcript inline. | P1 |
| US-ACC1-5 | As an operator, I want to disable the debate pipeline via `use_debate_pipeline: false` in config and fall back transparently to single-pass `LLMPredictionScorer`, so I can reduce token costs when needed without breaking the scoring pipeline. | P1 |

---

## 6. Feature Description

### 6.1 Pipeline Overview

`DebatePipelineScorer` replaces `LLMPredictionScorer` as the active scorer inside `TopBetsAgent` when `use_debate_pipeline: true`. It runs three sequential LLM calls per market:

```
Candidate market
  + EmbeddingStore top-10 similar markets
       │
       ▼
 [Pass 1: Bull Agent]
   → Argue convincingly for YES resolution
   → Output: structured argument (3–5 bullet points, cited evidence)
       │
       ▼
 [Pass 2: Bear Agent]
   → Given Bull's argument, argue convincingly for NO resolution
   → Explicitly rebut each of Bull's bullet points
   → Output: structured counter-argument (3–5 bullet points)
       │
       ▼
 [Pass 3: Judge Agent]
   → Given market + similar historical markets + Bull argument + Bear argument
   → State which side made the stronger case and why
   → Produce final probability estimate
   → Output: {yes_probability, confidence, reasoning, bull_score, bear_score, debate_summary}
```

**Drop-in interface contract:** `DebatePipelineScorer` must implement the same `score(market, similar_markets) -> ScoringResult` method signature as `LLMPredictionScorer`. `TopBetsAgent` selects the active scorer from config and does not need to know which is running.

### 6.2 Agent Prompt Specifications

#### Bull Agent Prompt
```
You are a prediction market analyst making the strongest possible case for a YES resolution.
Your goal is not to be balanced — it is to argue as compellingly as possible for YES.

Market: {question}
Category: {category}
Current YES price: {yes_price}
Days to resolution: {days}

Similar historical markets that resolved YES:
{similar_yes_markets_formatted}

Argue for YES resolution in 3–5 bullet points. Each bullet must cite a specific piece
of evidence, base rate, or analogous historical market. Be concrete, not vague.

Return JSON: {"bull_argument": ["bullet 1", "bullet 2", ...]}
```

#### Bear Agent Prompt
```
You are a prediction market analyst making the strongest possible case for a NO resolution.
You have read the Bull argument below. Your goal is to rebut it point by point and
construct the most compelling case for NO.

Market: {question}
Category: {category}
Current YES price: {yes_price}

Bull's argument for YES:
{bull_argument_formatted}

Similar historical markets that resolved NO:
{similar_no_markets_formatted}

Rebut the Bull's case and argue for NO in 3–5 bullet points. Each bullet must either
directly refute a Bull point or introduce a counter-evidence item.

Return JSON: {"bear_argument": ["bullet 1", "bullet 2", ...]}
```

#### Judge Agent Prompt
```
You are an impartial prediction market judge. You have read both sides of a debate
about the following market. Your job is to evaluate argument quality and produce
a calibrated final probability estimate.

Market: {question}
Category: {category}
Current YES price: {yes_price}
Days to resolution: {days}

Historical base rate context (top-10 similar resolved markets):
{similar_markets_formatted}

Bull's case for YES:
{bull_argument_formatted}

Bear's case for NO:
{bear_argument_formatted}

Instructions:
1. Score each side's argument quality from 0–10 (10 = airtight, evidence-based; 0 = pure speculation).
2. State explicitly which side made the stronger case and the single most decisive factor.
3. Produce a calibrated YES probability that reflects both the argument quality and the historical base rates.

Return JSON: {
  "yes_probability": 0.0-1.0,
  "confidence": 0-100,
  "reasoning": "2–3 sentences explaining the final verdict",
  "bull_score": 0-10,
  "bear_score": 0-10,
  "debate_summary": "1–2 sentences: who won and why"
}
```

### 6.3 Token Cost Optimisation

- Debate pipeline only runs on the **top-20 candidates** by heuristic pre-score (same pre-filter as single-pass LLM today).
- Config: `skip_debate_if_confidence_threshold: 90` — markets where the heuristic scorer returns `confidence ≥ 90` skip the debate and use single-pass (high-confidence markets are unlikely to benefit from adversarial prompting).
- Bull and Bear passes use `debate_temperature: 0.7` (higher creativity); Judge uses `debate_temperature: 0.2` (lower, more deterministic).

### 6.4 Configuration (`agents/polymarket/top_bets/config.yaml` additions)

```yaml
debate_pipeline:
  use_debate_pipeline: true          # default: true; false = fall back to LLMPredictionScorer
  debate_temperature: 0.7            # temperature for Bull and Bear passes
  judge_temperature: 0.2             # temperature for Judge pass
  skip_debate_if_confidence_threshold: 90  # heuristic confidence score above which debate is skipped
  max_debate_candidates: 20          # only run debate on top-N candidates by heuristic pre-score
  timeout_seconds: 30                # abort debate and fall back to single-pass if total time exceeds this
```

### 6.5 Fallback Chain

```
DebatePipelineScorer
  → on timeout or LLM error: fall back to LLMPredictionScorer (single-pass)
      → on LLM unavailable: fall back to TopBetScorer (heuristic)
          → always succeeds (pure math)
```

Each fallback logs a `warn`-severity row to `pm_agent_activity_log` with the appropriate `action` value (`debate_timeout_fallback`, `llm_scorer_fallback`).

---

## 7. Acceptance Criteria

| AC # | Criterion |
|---|---|
| **AC-1** | **Given** `use_debate_pipeline: true` and the embedding store has ≥ 10 records and the LLM is reachable, **When** `TopBetsAgent` scores a candidate market, **Then** `DebatePipelineScorer` is invoked and the resulting `pm_top_bets` row has non-null values for all five debate columns: `bull_argument`, `bear_argument`, `debate_summary`, `bull_score`, `bear_score`. |
| **AC-2** | **Given** the debate has completed for a `pm_top_bets` row, **When** the `TopBetCard` is rendered, **Then** an expandable "Debate" section is present showing: Bull summary (green tint, 2–3 lines), Bear summary (red tint, 2–3 lines), Judge verdict summary (1–2 lines), and a score badge (e.g. "Bull: 7/10 · Bear: 4/10"). |
| **AC-3** | **Given** the debate pipeline is active, **When** a full 3-pass debate cycle completes for one market, **Then** the wall-clock time from start of Bull pass to Judge output is ≤ 30 seconds at p95. |
| **AC-4** | **Given** `use_debate_pipeline: false` in config, **When** `TopBetsAgent` scores a market, **Then** `LLMPredictionScorer` (single-pass) is used instead; no `bull_argument`, `bear_argument`, or related debate columns are written; the existing `reasoning` column is populated as before. |
| **AC-5** | **Given** the debate pipeline times out (> `timeout_seconds`) or the LLM returns an error on any pass, **When** the scorer handles the exception, **Then** it falls back to `LLMPredictionScorer`, a `warn` row is written to `pm_agent_activity_log` with `action = "debate_timeout_fallback"` or `"debate_llm_error_fallback"`, and the `pm_top_bets` row is still created (with null debate columns and `scorer_type = "llm_rag"`). |
| **AC-6** | **Given** a candidate market's heuristic pre-score has `confidence ≥ skip_debate_if_confidence_threshold` (default 90), **When** `DebatePipelineScorer.score()` is called, **Then** only a single-pass LLM call is made (no Bull/Bear passes); the `pm_top_bets` row has `scorer_type = "llm_rag"` and null debate columns; an `info` log entry records `action = "debate_skipped_high_confidence"`. |
| **AC-7** | **Given** a `pm_top_bets` row has non-null `bull_argument` and `bear_argument`, **When** the client calls `GET /api/polymarket/top-bets/{id}/debate`, **Then** the response returns HTTP 200 with a JSON body containing: `bull_argument` (array of strings), `bear_argument` (array of strings), `debate_summary` (string), `bull_score` (int 0–10), `bear_score` (int 0–10), `yes_probability` (float), and `scorer_type = "debate_pipeline"`. |
| **AC-8** | **Given** the user is in the Chat tab and asks about a bet that has a completed debate, **When** the agent response renders, **Then** a "Show debate" button is present; clicking it expands the full Bull/Bear/Judge transcript inline within the chat message. |

---

## 8. DB Schema Changes

> Extends migration `032_pm_phase15.py` — add columns to `pm_top_bets` via migration `033_pm_debate_pipeline.py`.

### `pm_top_bets` — new columns

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `bull_argument` | `TEXT` | YES | JSON-serialised array of 3–5 bullet-point strings; null if debate not run or fell back |
| `bear_argument` | `TEXT` | YES | JSON-serialised array of 3–5 bullet-point strings; null if debate not run or fell back |
| `debate_summary` | `TEXT` | YES | 1–2 sentence Judge summary of who won the debate and why; null if debate not run |
| `bull_score` | `SMALLINT` | YES | 0–10 Judge rating of Bull argument strength; null if debate not run |
| `bear_score` | `SMALLINT` | YES | 0–10 Judge rating of Bear argument strength; null if debate not run |

**`scorer_type` column extension** (already exists in Phase 15 schema):  
Add `"debate_pipeline"` as a valid value alongside existing `"llm_rag"` and `"heuristic"`. Constraint: `CHECK (scorer_type IN ('heuristic', 'llm_rag', 'debate_pipeline'))`.

**Index addition:** `CREATE INDEX idx_pm_top_bets_debate ON pm_top_bets (scorer_type) WHERE bull_score IS NOT NULL;` — supports model evaluation queries that compare debate vs. non-debate Brier scores.

---

## 9. API Changes

### New endpoint

**`GET /api/polymarket/top-bets/{id}/debate`**

Returns the full debate transcript for a scored bet.

**Path params:**  
- `id` — UUID of `pm_top_bets` row

**Response (HTTP 200):**
```json
{
  "id": "uuid",
  "market_question": "Will the Fed cut rates before July 2025?",
  "yes_probability": 0.62,
  "confidence": 74,
  "scorer_type": "debate_pipeline",
  "bull_score": 7,
  "bear_score": 5,
  "debate_summary": "Bull's case on historical Fed pivot timing was stronger; Bear's liquidity argument lacked specifics.",
  "bull_argument": [
    "The Fed cut rates in 3 of 4 similar inflationary cycles once CPI fell below 3.5% — current CPI is 3.1%.",
    "Fed futures market is pricing 73% probability of a cut by July — historically this level of pricing has been correct 68% of the time.",
    "...more bullets..."
  ],
  "bear_argument": [
    "All 3 of Bull's historical precedents occurred before the 2022 QT cycle — Fed balance sheet dynamics are structurally different now.",
    "Unemployment at 3.8% removes urgency for a cut; the Fed has explicitly said 'higher for longer' in the last 2 FOMC statements.",
    "...more bullets..."
  ],
  "scored_at": "2025-07-10T14:32:11Z"
}
```

**Response (HTTP 404):** Bet ID not found.  
**Response (HTTP 409):** Bet exists but was scored without the debate pipeline (debate columns null); body: `{"detail": "This bet was not scored with the debate pipeline."}`.

### Existing endpoint change

**`GET /api/polymarket/top-bets`** — response objects gain these optional fields (null when debate not run):

```json
{
  "...(existing fields)...",
  "bull_score": 7,
  "bear_score": 5,
  "debate_summary": "Bull's case on historical Fed pivot timing was stronger...",
  "has_debate": true
}
```

The `has_debate: bool` field is computed server-side as `bull_argument IS NOT NULL`.

---

## 10. UI Changes

### 10.1 `TopBetCard` — Debate expandable section

Each `TopBetCard` gains a new collapsible **"Debate"** section, rendered only when `has_debate = true`. It appears below the existing "AI Reasoning" section and above the Accept/Reject buttons.

**Collapsed state (default):**
```
[⚖ Debate  Bull: 7/10 · Bear: 5/10  ▾]
```
- Icon: `Scale` from lucide-react
- Score badge: "Bull: {bull_score}/10 · Bear: {bear_score}/10"
- Colour: bull score rendered in green text; bear score in red text
- If `bull_score > bear_score`: badge has a subtle green left-border (Bull won)
- If `bear_score ≥ bull_score`: badge has a subtle red left-border (Bear won or draw)

**Expanded state:**
```
┌─────────────────────────────────────────────┐
│ 🐂 Bull Case (7/10)              [green tint] │
│ • {bullet 1}                                  │
│ • {bullet 2}                                  │
│ • {bullet 3}                                  │
├─────────────────────────────────────────────┤
│ 🐻 Bear Case (5/10)              [red tint]   │
│ • {bullet 1}                                  │
│ • {bullet 2}                                  │
│ • {bullet 3}                                  │
├─────────────────────────────────────────────┤
│ ⚖ Judge Verdict                              │
│ {debate_summary — 1–2 sentences}              │
└─────────────────────────────────────────────┘
```
- Bull section: `bg-green-500/5 border-green-500/20` tint
- Bear section: `bg-red-500/5 border-red-500/20` tint
- Judge section: neutral card background
- Maximum 3 bullet points shown per side in the card; a "Show all" link reveals remaining bullets inline (no modal)

### 10.2 Chat Tab — "Show debate" button

When the Chat agent includes a bet recommendation in its response message:
- A **"Show debate"** button is rendered alongside the existing "Accept bet" button, but only when `has_debate = true` for the referenced bet.
- Clicking "Show debate" fetches `GET /api/polymarket/top-bets/{id}/debate` and expands a collapsible debate panel inline within the chat message bubble (same visual layout as the `TopBetCard` expanded state above).
- The button is greyed out / hidden when `has_debate = false`.

### 10.3 No changes to other tabs or components

The Markets, Strategies, Orders, Positions, Promotion, Briefing, Risk, and Logs tabs are **not modified** by this feature.

---

## 11. Integration Notes

### Relationship to Phase 15

| Phase 15 component | How F-ACC-1 interacts |
|---|---|
| `agents/polymarket/top_bets/llm_scorer.py` (`LLMPredictionScorer`) | `DebatePipelineScorer` is added to the **same file** as a second class. Both share the `ScoringResult` return type. `TopBetsAgent` imports and selects between them based on config. |
| `agents/polymarket/top_bets/config.yaml` | New `debate_pipeline:` block added. No existing keys modified. |
| `pm_top_bets` DB table (migration `032`) | Extended by migration `033`; five new nullable columns. Zero breaking changes to existing rows. |
| `EmbeddingStore` (`shared/polymarket/embedding_store.py`) | Reused as-is. `DebatePipelineScorer` calls `EmbeddingStore.search()` once and passes the results to all three passes. No changes to `EmbeddingStore`. |
| `shared/llm/` LLM client | Called three times per market instead of once. No interface changes. |
| `apps/api/src/routes/polymarket.py` | New `GET /top-bets/{id}/debate` endpoint appended. Existing `GET /top-bets` response extended with `has_debate`, `bull_score`, `bear_score`, `debate_summary`. |
| `apps/dashboard/src/components/TopBetCard.tsx` | Debate section added as a new collapsible below "AI Reasoning". No existing sections removed or reordered. |
| Chat tab (`apps/dashboard/src/pages/polymarket/ChatTab.tsx`) | "Show debate" button added to assistant messages that include a `bet_recommendation` payload with `has_debate = true`. |

### Scorer selection logic (pseudo-description, not code)

`TopBetsAgent` config resolution at startup:

1. If `use_debate_pipeline = false` → use `LLMPredictionScorer`
2. If `use_debate_pipeline = true` AND LLM client is reachable AND embedding store has ≥ 10 records → use `DebatePipelineScorer`
3. Otherwise → use `LLMPredictionScorer` as automatic degradation

Within `DebatePipelineScorer.score()`, per-market runtime decisions:

1. If heuristic pre-score confidence ≥ `skip_debate_if_confidence_threshold` → single-pass only (log `debate_skipped_high_confidence`)
2. If debate total time exceeds `timeout_seconds` → abort remaining passes, fall back to `LLMPredictionScorer` output (log `debate_timeout_fallback`)
3. If any LLM pass returns a parsing error → abort and fall back (log `debate_llm_error_fallback`)

---

## 12. Constraints (from user)

| Constraint | Detail |
|---|---|
| Drop-in replacement | `DebatePipelineScorer` must implement the same `score()` interface as `LLMPredictionScorer`. `TopBetsAgent` must not require a change to work with either scorer. |
| 3 agents maximum | Bull, Bear, Judge only. No additional specialist agents in this phase. |
| No streaming debate | Debate runs synchronously in the background; UI displays final results once all three passes complete. |
| No user-triggered re-debate | Users cannot re-run a debate on an already-scored market. |
| Debate on top-20 candidates only | The `max_debate_candidates: 20` cap is a hard constraint to manage token cost. |
| Config-controlled | `use_debate_pipeline: false` must disable the feature completely with zero side effects on the existing pipeline. |
| 30s p95 latency | Debate must complete within 30 seconds per market at p95. If the timeout fires, the fallback must produce a valid `pm_top_bets` row. |
| No fine-tuning | Prompt engineering only; no model weight updates. |

---

## 13. Open Questions

*The following are flagged for Atlas to resolve during architecture; no user input is needed:*

1. **Bull/Bear pass parallelism:** The spec calls for sequential passes (Bear reads Bull's output; Judge reads both). Atlas should confirm whether the Bear pass must strictly follow Bull, or whether a parallel Bull/Bear architecture with a subsequent Judge reconciliation pass would also satisfy the product intent. Parallel would halve latency at the cost of Bear not being able to rebut Bull point-by-point.

2. **Debate storage format:** `bull_argument` and `bear_argument` are specified as `TEXT` (JSON-serialised arrays). Atlas to decide whether to normalise these into a `pm_debate_arguments` child table for easier querying, or keep as JSONB columns on `pm_top_bets` (simpler, consistent with `similar_markets_json`).

3. **LLM model selection per pass:** The spec uses the same model for all three passes. Atlas to determine whether using a higher-capability model for the Judge pass (at higher cost) is worth the quality tradeoff, or whether a single model configured with different temperatures is sufficient.

4. **Debate transcript in Chat:** When the Chat agent is asked about a bet and the user clicks "Show debate", the transcript is fetched via `GET /top-bets/{id}/debate`. Atlas to confirm whether the Chat backend should include the debate transcript in the agent's context window (for the agent to reference in its response) or present it purely as a UI-level document viewer.

5. **Migration sequencing:** Migration `033` adds nullable columns to `pm_top_bets`. If Phase 15 has not yet deployed (migration `032` not yet applied), Atlas must decide whether to merge these into `032` or ship them as a separate migration with a hard dependency.

---

## 14. Research & Sources

> All claims about adversarial prompting, debate methods, and Brier scoring are based on published research and documentation.

1. **OpenAI Debate research (Irving et al., 2018)** — "AI Safety via Debate" — establishes that adversarial debate between AI agents is a viable mechanism for surfacing correct reasoning even when individual agents are limited: https://arxiv.org/abs/1805.00899

2. **Anthropic Constitutional AI (Bai et al., 2022)** — demonstrates that multi-pass self-critique (critique → revision → final output) reduces harmful and overconfident outputs: https://arxiv.org/abs/2212.08073

3. **Prediction market forecaster overconfidence** — Karger et al. (2023) "Forecasting Competitions" documents that single-point human and LLM forecasts overestimate confidence on political/macro markets by 8–15%: https://www.metaculus.com/notebooks/15392/

4. **Brier score as calibration metric** — the standard forecasting accuracy metric used by Metaculus, Good Judgment Project, and ForecastingResearch.org; lower is better (0 = perfect): https://en.wikipedia.org/wiki/Brier_score

5. **LLM multi-agent reasoning quality** — Du et al. (2023) "Improving Factuality and Reasoning in Language Models through Multiagent Debate" shows multi-agent debate reduces factual errors by 11–23% on contested questions vs. single-pass: https://arxiv.org/abs/2305.14325

---

*End of PRD: F-ACC-1 Bull/Bear/Judge Debate Pipeline*
