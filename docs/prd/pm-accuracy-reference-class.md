# PRD: Reference Class Forecasting Agent (F-ACC-3)

**Feature ID:** F-ACC-3  
**Version:** 1.0  
**Status:** Draft  
**Author:** Nova (PM)  
**Date:** 2025-07-09  
**Parent PRD:** `docs/prd/polymarket-phase15.md` (Phase 15 — Prediction Markets)  
**Accuracy Feature Series:** F-ACC-1 (Debate Pipeline) → F-ACC-2 (Chain-of-Thought Sampling) → **F-ACC-3 (Reference Class Forecasting Agent)** → F-ACC-4 (TBD)

---

## 1. Problem

The Phase 15 `LLMPredictionScorer` (F15-F3) uses semantic similarity to retrieve 10 historical markets and asks an LLM to estimate probability. This works well for *specific* event reasoning but has a known failure mode: **the LLM does not systematically account for the base rate of the reference class before adjusting for specific evidence.**

Without an explicit base rate anchor, the LLM:
- Over-weights vivid, specific evidence and under-weights prior probabilities (the *inside view* bias, documented in Tetlock & Gardner, "Superforecasting", Crown, 2015).
- Assigns inflated probabilities to novel or unlikely events because the context window contains compelling but cherry-picked similar markets.
- Produces confidence scores that diverge from historical resolution frequencies for common market categories (sports, elections, economic thresholds).

The **#1 calibration technique from Philip Tetlock's superforecaster research** is the *outside view*: begin every probability estimate by asking "What is the base rate for this *type* of event?" before adjusting for the specific case. This PRD specifies a dedicated `ReferenceClassAgent` that computes this statistical anchor from the real resolved-market history in `pm_historical_markets` and injects it into the LLM scorer's prompt as an explicit calibration prior.

This is a pure accuracy improvement — it does not change the user-visible workflow; it makes the reasoning the system already shows the user more trustworthy.

---

## 2. Target Users & Jobs-to-Be-Done

| User Segment | Job-to-Be-Done |
|---|---|
| **Evidence-based trader (primary)** | "I want the AI probability estimate to start from what has actually happened historically for this type of market, not just the LLM's internal priors." |
| **Skeptical adopter** | "Show me *why* the system thinks 70% — I want to see the base rate it used, how many similar markets it drew from, and whether the current price diverges from history." |
| **Strategy improver** | "As more markets resolve and enter the database, the base rates should automatically get more accurate — the system should improve itself over time." |
| **Dashboard operator (admin)** | "I want to see all reference classes the system has learned, their base rates, and sample sizes, so I can assess the quality of the statistical anchors." |

---

## 3. Goals & Non-Goals

### Goals

- Implement a `ReferenceClassAgent` that classifies every candidate prediction market into a reference class and computes a historical base-rate YES probability from `pm_historical_markets`.
- Inject the base rate as an explicit anchor sentence into the `LLMPredictionScorer` prompt, following the Tetlock outside-view technique.
- Store per-recommendation reference class metadata (`reference_class`, `base_rate_yes`, `base_rate_sample_size`, `base_rate_confidence`) in `pm_top_bets`.
- Surface the base rate on the `TopBetCard` UI with a divergence warning when market price deviates > 20 percentage points from the base rate.
- Provide a new "Reference Classes" sub-tab in the Logs tab listing all known classes with their base rates, sample sizes, and last-updated timestamp.
- Provide a new API endpoint `GET /api/polymarket/reference-classes` for dashboard consumption and operator inspection.
- Self-reinforce: as more markets resolve into `pm_historical_markets`, base rates automatically improve with no operator action required.

### Non-Goals

- **Manual user-defined reference classes** — operator cannot add or rename classes via the UI; classification is fully automated.
- **Real-time base rate updates within a single scan cycle** — base rates are computed at scan-start and held constant for the cycle; they do not update mid-scan.
- **Sub-classification by granular attributes** — no sport-specific win-rates by team, no election-specific rates by candidate type; class granularity is the top-level category only (v1.0).
- **Base-rate-only recommendations** — the base rate is an anchor/prior, not a standalone signal; the LLM scorer with full RAG context remains the primary scorer.
- **User-facing base rate editing** — base rates are read-only from the user's perspective; they reflect historical data only.
- **Historical backfill of `reference_class` for all existing markets** — a one-time migration job is sufficient; no UI progress indicator is required for the backfill.

---

## 4. Success Metrics

| # | Metric | Target | Measurement Method |
|---|---|---|---|
| M1 | Reference class assigned for scored markets | ≥ 70% of all markets scored per cycle receive a non-null `reference_class` | Query `pm_top_bets` where `recommendation_date >= now() - 7d`; compute pct non-null |
| M2 | Base rate anchor injected into LLM prompt | ≥ 50% of scored markets receive a base rate anchor (sample size ≥ 5) | Query `pm_top_bets` where `base_rate_sample_size >= 5`; pct over 7 days |
| M3 | Brier score improvement vs no-base-rate baseline | ≥ 8% improvement on high-volume reference classes (sports, elections) | Retrospective evaluation via `pm_model_evaluations`; compare `llm_rag_with_rcf` vs `llm_rag` |
| M4 | Reference classes discoverable via API | `GET /api/polymarket/reference-classes` returns ≥ 5 distinct classes after 2 weeks of scoring | Count distinct `reference_class` values in API response |
| M5 | TopBetCard divergence warning shown when appropriate | 100% of cards where `abs(base_rate_yes - market_yes_price) > 0.20` show ⚠️ divergence badge | Manual QA + Playwright assertion |
| M6 | No latency regression per scan cycle | Adding RCF agent does not increase `_scan_cycle()` wall-clock time by > 200 ms at p95 | APM trace comparison pre/post deploy |
| M7 | Low-sample fallback functioning | 100% of markets where `base_rate_sample_size < 5` show "Insufficient history" on card and omit anchor from prompt | Unit test + integration test |

---

## 5. User Stories

| ID | Story | Priority |
|---|---|---|
| US-RCF-1 | As a trader, I want each top-bet recommendation to show a historical base rate ("34% YES from 47 similar markets") so I can see whether the current market price is aligned with or diverging from historical frequency. | P0 |
| US-RCF-2 | As a trader, I want a yellow ⚠️ divergence warning when the market price differs from the base rate by more than 20 percentage points, so I am alerted to potentially mispriced markets before I accept. | P0 |
| US-RCF-3 | As a trader, I want the AI reasoning to explicitly state the reference class base rate as a starting anchor before discussing specific evidence, so I can evaluate whether the AI appropriately adjusted from the outside view. | P1 |
| US-RCF-4 | As an operator, I want a "Reference Classes" sub-tab in the Logs tab that lists all learned classes with their base rates, sample sizes, and last-updated timestamp, so I can assess the quality and breadth of historical coverage. | P1 |
| US-RCF-5 | As a trader, when there are fewer than 5 historical markets in a reference class, I want the card to show "Insufficient history" in gray (with no base rate figure), so I am not misled by statistically unreliable estimates. | P0 |

---

## 6. Acceptance Criteria

### AC-1: Market Classification (US-RCF-1, US-RCF-3)
- **Given** a candidate market question (e.g., "Will the Chiefs win Super Bowl LX?"),  
  **When** `ReferenceClassAgent.classify(market)` is called,  
  **Then** a `reference_class` string from the known taxonomy is returned (e.g., `team_wins`), and the result is cached in `pm_historical_markets.reference_class` for that market if it is historical.
- **Given** a market question that does not match any keyword pattern,  
  **When** `ReferenceClassAgent.classify(market)` is called,  
  **Then** a lightweight LLM call is made to classify into one of the known classes (or `other`), and the LLM call is logged at `info` severity in `pm_agent_activity_log`.

### AC-2: Base Rate Computation (US-RCF-1, US-RCF-5)
- **Given** `pm_historical_markets` has ≥ 5 resolved markets where `reference_class = 'team_wins'` and `resolution_date > NOW() - INTERVAL '2 years'`,  
  **When** `ReferenceClassAgent.get_base_rate(market)` is called for a `team_wins` market,  
  **Then** a dict is returned with `reference_class`, `base_rate_yes` (float 0–1), `base_rate_sample_size` (int ≥ 5), and `base_rate_confidence` (float 0–1).
- **Given** fewer than 5 matching historical markets exist for the assigned reference class,  
  **When** `ReferenceClassAgent.get_base_rate(market)` is called,  
  **Then** the returned dict has `base_rate_sample_size < 5` and `base_rate_confidence = 0.0`; no base rate anchor string is injected into the LLM prompt.

### AC-3: Prompt Injection (US-RCF-3)
- **Given** `base_rate_confidence >= 0.3` (sample size ≥ 5 maps to confidence ≥ 0.3),  
  **When** `LLMPredictionScorer.score(market, base_rate_context=base_rate)` is called,  
  **Then** the assembled LLM prompt contains the anchor sentence:  
  `"BASE RATE ANCHOR: Historically, {N} similar '{reference_class}' markets in the past 2 years resolved YES {base_rate_pct}% of the time. The current market prices YES at {market_price}. Start from this base rate and adjust based on specific evidence for THIS market."`
- **Given** `base_rate_confidence < 0.3` (insufficient history),  
  **When** `LLMPredictionScorer.score(market, base_rate_context=base_rate)` is called,  
  **Then** the prompt contains `"NOTE: Insufficient historical data for reference class '{reference_class}' — base rate anchor omitted."` and the scorer proceeds using semantic similarity only.

### AC-4: Data Persistence (US-RCF-1)
- **Given** the top-bets agent completes scoring for a market,  
  **When** the resulting `pm_top_bets` row is written,  
  **Then** `reference_class`, `base_rate_yes`, `base_rate_sample_size`, and `base_rate_confidence` are all populated (non-null for classified markets; null only if classification fails entirely).

### AC-5: TopBetCard UI — Base Rate Row (US-RCF-1, US-RCF-2, US-RCF-5)
- **Given** a `pm_top_bets` row has `base_rate_sample_size >= 5`,  
  **When** the `TopBetCard` is rendered,  
  **Then** a "Base Rate" row appears below the confidence score showing: `"Base rate: {base_rate_pct}% YES (from {N} similar markets)"` with a thin horizontal bar visualizing the base rate percentage.
- **Given** `abs(base_rate_yes - market_yes_price) > 0.20`,  
  **When** the `TopBetCard` is rendered,  
  **Then** a yellow ⚠️ badge reading `"Market prices differently from base rate"` is displayed adjacent to the base rate row.
- **Given** a `pm_top_bets` row has `base_rate_sample_size < 5`,  
  **When** the `TopBetCard` is rendered,  
  **Then** the base rate row shows `"Insufficient history"` in gray with no percentage or bar; no divergence badge is shown.

### AC-6: Reference Classes API (US-RCF-4)
- **Given** at least one market has been classified,  
  **When** `GET /api/polymarket/reference-classes` is called,  
  **Then** the response is HTTP 200 with a JSON array where each item contains: `reference_class` (string), `base_rate_yes` (float), `sample_size` (int), `last_updated` (ISO8601 timestamp), and `example_question` (string — the most recent market question in that class).

### AC-7: Logs Tab — Reference Classes Sub-Tab (US-RCF-4)
- **Given** the user opens the Logs tab,  
  **When** the "Reference Classes" sub-tab is selected,  
  **Then** a table is displayed with columns: Class, Base Rate (YES%), Sample Size, Last Updated; rows are sorted by sample size descending; the table refreshes on the same polling interval as other Logs tab cards.

### AC-8: Fallback Safety
- **Given** the `pm_historical_markets` table is empty (first-run or migration not yet complete),  
  **When** `ReferenceClassAgent.get_base_rate(market)` is called,  
  **Then** the agent returns a zero-confidence result, does not throw an exception, and logs a single `warn`-severity entry with `action = "rcf_no_history"` to `pm_agent_activity_log`; the `LLMPredictionScorer` proceeds normally without a base rate anchor.

---

## 7. Feature Description

### 7.1 ReferenceClassAgent Class

**Location:** `agents/polymarket/top_bets/reference_class.py`

The agent exposes two primary methods:

**`classify(market: CandidateMarket) → ClassificationResult`**

Classification proceeds in two stages to minimize LLM cost:

1. **Stage 1 — Keyword matching (fast path):** Regex patterns applied to the market question text:
   - `team_wins`: patterns matching team names + "win" / "beat" / "defeat" / "championship"
   - `candidate_wins`: patterns matching candidate names + "win" / "elected" / "become president/governor"
   - `economic_threshold`: patterns matching economic indicators (CPI, GDP, unemployment, Fed rate) + "exceed" / "above" / "below" / "reach"
   - `regulatory_outcome`: patterns matching regulatory verbs (approve, ban, fine, indict, charge, arrest) applied to named entities
   - `crypto_price`: patterns matching crypto tickers + price level language
   - `other`: catch-all when no pattern matches

2. **Stage 2 — LLM fallback (slow path, cache-first):** If Stage 1 returns `other` AND this question has not been classified before, make a single short LLM call:
   > *"Classify this prediction market question into exactly one of: team_wins, candidate_wins, economic_threshold, regulatory_outcome, crypto_price, other. Return only the class label. Market: {question}"*

   Result is cached in `pm_historical_markets.reference_class` (for historical markets) or in an in-memory LRU cache (for live markets not yet in history).

**`get_base_rate(market: CandidateMarket) → BaseRateResult`**

```
SQL:
SELECT
    COUNT(*) FILTER (WHERE winning_outcome = 'YES') AS yes_count,
    COUNT(*) AS total
FROM pm_historical_markets
WHERE reference_class = :reference_class
  AND resolution_date > NOW() - INTERVAL '2 years'
LIMIT 100
```

Computes:
- `base_rate_yes = yes_count / total` (0.0 if total = 0)
- `base_rate_sample_size = total`
- `base_rate_confidence`: Wilson score interval lower bound at 95% CI — naturally encodes both sample size and proportion stability. Returns 0.0 when total < 5.

### 7.2 Integration with TopBetsAgent Scan Cycle

`ReferenceClassAgent` is called **before** the `LLMPredictionScorer` in `TopBetsAgent._scan_cycle()`:

```
# Pseudocode — implementation by Atlas/Devin
for market in candidate_markets:
    base_rate = await self.reference_class_agent.get_base_rate(market)
    score = await self.llm_scorer.score(market, base_rate_context=base_rate)
    persist(score, base_rate)
```

The `base_rate_context` dict is passed directly into `LLMPredictionScorer.score()`. The scorer is responsible for injecting the anchor string into the prompt; the `ReferenceClassAgent` does not touch the prompt directly.

### 7.3 Market Classification Taxonomy (v1.0)

| Class | Description | Example |
|---|---|---|
| `team_wins` | Sports team wins a game, series, or championship | "Will the Lakers win the NBA Championship?" |
| `candidate_wins` | Political candidate wins an election or nomination | "Will Trump win the 2024 presidential election?" |
| `economic_threshold` | Economic indicator crosses a numeric threshold | "Will US inflation exceed 3% in Q3 2025?" |
| `regulatory_outcome` | Regulatory, legal, or governmental action taken on an entity | "Will the DOJ indict [person]?" |
| `crypto_price` | Cryptocurrency reaches a price level | "Will Bitcoin reach $100k before end of 2025?" |
| `other` | Does not fit any above class; falls back to semantic similarity only | "Will [obscure specific event] happen?" |

### 7.4 Base Rate Confidence Formula

Wilson score lower bound at 95% confidence interval:

```
p̂ = yes_count / total
z = 1.96  # 95% CI
lower_bound = (p̂ + z²/2n - z * sqrt(p̂(1-p̂)/n + z²/4n²)) / (1 + z²/n)
confidence = lower_bound  # ranges 0.0 → 1.0
```

Threshold for prompt injection: `confidence >= 0.3` (approximately 5+ samples with moderate base rate).

---

## 8. DB Changes

**Migration file:** `shared/db/migrations/033_pm_rcf.py`  
*(appended after migration `032_pm_phase15.py`)*

### 8.1 Modify `pm_historical_markets` — add `reference_class` column

```sql
ALTER TABLE pm_historical_markets
    ADD COLUMN reference_class VARCHAR(64);

-- One-time backfill: classification job populates existing rows
-- New index for base rate queries:
CREATE INDEX idx_pm_historical_markets_refclass_resolution
    ON pm_historical_markets (reference_class, resolution_date DESC);
```

### 8.2 Modify `pm_top_bets` — add reference class result columns

```sql
ALTER TABLE pm_top_bets
    ADD COLUMN reference_class       VARCHAR(64),
    ADD COLUMN base_rate_yes         FLOAT,
    ADD COLUMN base_rate_sample_size INT,
    ADD COLUMN base_rate_confidence  FLOAT;
```

*These columns are nullable; they are null only when classification fails entirely (e.g., table empty, LLM classification error).*

### 8.3 No new tables required

Reference class base rates are computed on-the-fly from `pm_historical_markets` at scan time; no separate materialized base-rate table is needed for v1.0. (Atlas may choose to add a materialized view for query performance if `pm_historical_markets` grows large — this is an implementation detail.)

---

## 9. API Changes

All new/modified routes appended to `apps/api/src/routes/polymarket.py`.

### 9.1 Existing endpoint modified

**`GET /api/polymarket/top-bets`** — response payload extended:

Each item in the `bets` array gains four new optional fields:

```jsonc
{
  "id": "uuid",
  "market_id": "uuid",
  // ... existing fields unchanged ...
  "reference_class": "team_wins",          // string | null
  "base_rate_yes": 0.34,                   // float 0–1 | null
  "base_rate_sample_size": 47,             // int | null
  "base_rate_confidence": 0.71             // float 0–1 | null
}
```

These fields are `null` when `base_rate_sample_size < 5` or classification failed.

### 9.2 New endpoint

**`GET /api/polymarket/reference-classes`**

Returns all known reference classes with their current base rate statistics.

**Response — HTTP 200:**
```jsonc
{
  "reference_classes": [
    {
      "reference_class": "team_wins",
      "base_rate_yes": 0.34,
      "sample_size": 147,
      "last_updated": "2025-07-09T12:00:00Z",
      "example_question": "Will the Chiefs win Super Bowl LX?"
    },
    {
      "reference_class": "candidate_wins",
      "base_rate_yes": 0.51,
      "sample_size": 63,
      "last_updated": "2025-07-08T18:30:00Z",
      "example_question": "Will Biden win the 2024 election?"
    }
    // ... one row per distinct reference_class in pm_historical_markets
  ],
  "generated_at": "2025-07-09T14:22:00Z"
}
```

**Error cases:**
- `pm_historical_markets` empty → HTTP 200 with `reference_classes: []` (not a 404).

---

## 10. UI Changes

All changes are additive; no existing UI components are modified beyond `TopBetCard`.

### 10.1 TopBetCard — Base Rate Row

**Location:** `apps/dashboard/src/components/polymarket/TopBetCard.tsx`

A new "Base Rate" row is inserted **below the Confidence Score row** and **above the AI Reasoning expandable**:

| Condition | Display |
|---|---|
| `base_rate_sample_size >= 5` | `"Base rate: {base_rate_pct}% YES (from {N} similar markets)"` + thin horizontal bar at `base_rate_pct%` width |
| `abs(base_rate_yes - market_yes_price) > 0.20` | Yellow ⚠️ badge: `"Market prices differently from base rate"` — displayed adjacent to the base rate value |
| `base_rate_sample_size < 5` OR null | `"Insufficient history"` in `text-muted` gray; no bar; no badge |

The horizontal bar uses the same visual style as the existing confidence score progress bar; fill color is neutral (`bg-slate-400`) to distinguish it from the confidence bar.

Tooltip on hover: `"Historical base rate computed from {N} resolved {reference_class} markets over the past 2 years."`

### 10.2 Logs Tab — Reference Classes Sub-Tab

**Location:** `apps/dashboard/src/pages/polymarket/LogsTab.tsx`

A new "Reference Classes" sub-tab is added as the last sub-tab in the Logs tab (after the existing "Activity", "Model Performance" sub-tabs if present).

**Table columns:**

| Column | Source | Format |
|---|---|---|
| Class | `reference_class` | Human-readable label (e.g., "Team Wins" from `team_wins`) |
| Base Rate (YES%) | `base_rate_yes * 100` | `"34.2%"` |
| Sample Size | `sample_size` | Integer; if < 5, show `"< 5 (insufficient)"` in muted style |
| Last Updated | `last_updated` | Relative time (e.g., "3 hours ago") with absolute on hover |

Rows are sorted by `sample_size` descending.

Polling interval: same as the "Activity" sub-tab (operator-configurable; default 30 s).

Empty state: `"No reference classes learned yet. Base rates will appear as markets are scored."` with a muted info icon.

---

## 11. Integration Notes

### 11.1 Position in the Accuracy Feature Pipeline

F-ACC-3 is the third agent in the accuracy improvement series for the `LLMPredictionScorer`. The three agents each add a distinct calibration layer to the same scoring event:

```
CandidateMarket
     │
     ▼
[F-ACC-3: ReferenceClassAgent]   ← THIS FEATURE
     │  Adds: base_rate_context dict
     │  When: BEFORE LLM call
     │
     ▼
[F15-F3: LLMPredictionScorer]    ← Phase 15 baseline
     │  Core: RAG retrieval + LLM inference
     │  Consumes: base_rate_context (F-ACC-3)
     │            debate_result (F-ACC-1)
     │            cot_samples (F-ACC-2)
     │
     ▼
[F-ACC-2: CoT Sampling Agent]    ← Chain-of-Thought multi-sample
     │  Adds: multiple reasoning traces sampled at T>0
     │  When: inside LLM scorer (wraps LLM call)
     │
     ▼
[F-ACC-1: Debate Pipeline Agent] ← Devil's advocate debate
     │  Adds: pro/con debate transcript
     │  When: post-scoring, pre-persist
     │
     ▼
pm_top_bets (persisted with all metadata)
```

**Sequencing constraints:**
- **F-ACC-3 runs first** — the base rate anchor must be available before the primary LLM inference call so it can be embedded in the prompt.
- **F-ACC-2 (CoT sampling)** wraps or replaces the single LLM call in `LLMPredictionScorer`; it consumes the same `base_rate_context` already embedded in the prompt.
- **F-ACC-1 (debate pipeline)** runs after an initial probability is produced; it challenges the initial estimate. The debate prompt should also receive the base rate anchor so the debate agent can reference the outside-view prior when constructing its devil's advocate argument.

### 11.2 Shared `base_rate_context` Contract

The dict returned by `ReferenceClassAgent.get_base_rate()` is passed unchanged through the scoring pipeline:

```python
# Canonical shape — all consumers must handle all fields
BaseRateResult = TypedDict("BaseRateResult", {
    "reference_class": str,           # e.g. "team_wins"
    "base_rate_yes": float,           # 0.0 – 1.0
    "base_rate_sample_size": int,     # raw count
    "base_rate_confidence": float,    # Wilson lower bound, 0.0 – 1.0
    "anchor_text": str | None,        # Pre-formatted anchor sentence for prompt injection;
                                      # None when confidence < 0.3
})
```

`LLMPredictionScorer` checks `anchor_text is not None` before injecting. F-ACC-1 and F-ACC-2 receive this same dict and may use `anchor_text` in their respective prompts.

### 11.3 Config Flag

New key in `agents/polymarket/top_bets/config.yaml`:

```yaml
use_reference_class_agent: true   # set false to disable RCF; LLM scorer proceeds without base rate
rcf_min_confidence: 0.3           # Wilson lower bound threshold for prompt injection
rcf_lookback_years: 2             # years of history to include in base rate SQL query
rcf_sample_limit: 100             # LIMIT clause for base rate SQL query
```

When `use_reference_class_agent: false`, `TopBetsAgent._scan_cycle()` skips the `ReferenceClassAgent` call entirely and passes `base_rate_context=None` to the scorer — zero latency impact when disabled.

---

## 12. Constraints (from Phase 15 parent)

| Constraint | Impact on F-ACC-3 |
|---|---|
| JSONB embeddings, no pgvector in v1.0 | No new embedding computation required; base rates use SQL COUNT, not vector ops |
| No fine-tuning | The LLM classification call in Stage 2 uses the existing model as-is; no weight updates |
| `use_llm_scorer: true` is default-on when embedding store has ≥ 10 records | F-ACC-3 activates automatically alongside the LLM scorer; no separate activation step |
| Manual-accept workflow only | F-ACC-3 adds metadata to recommendations; it does not alter the accept/reject flow |
| Robinhood is primary venue | Markets from both venues are classified using the same taxonomy; no venue-specific class changes |

---

## 13. Open Questions

> *These are flagged for Atlas to resolve during architecture. No user input is required.*

1. **LRU cache size for live-market classifications:** Stage 2 LLM classification results for live markets not yet in `pm_historical_markets` are cached in-memory. Atlas to define max cache size and TTL to avoid stale classifications as market questions evolve.

2. **Backfill job scheduling:** The one-time backfill of `reference_class` for existing `pm_historical_markets` rows runs at migration time. Atlas to determine whether this runs synchronously in the migration or as a background task dispatched post-migration.

3. **Multi-outcome markets:** The `base_rate_yes` convention assumes binary YES/NO resolution. Atlas to define how base rates are computed for multi-outcome markets (e.g., should `base_rate_yes` represent the probability the *recommended side* wins, regardless of binary framing?).

4. **`other` class base rate:** Markets classified as `other` have heterogeneous resolution patterns; a pooled base rate across all `other` markets is statistically meaningless. Atlas to decide whether to omit base rate injection for `other`-class markets entirely or compute it anyway.

5. **Wilson confidence threshold tuning:** The `rcf_min_confidence: 0.3` default is a suggested starting point. Atlas/Devin should validate this against the first 2 weeks of data; a post-deploy calibration task is recommended.

---

## 14. Research & Sources

1. **Tetlock, P. & Gardner, D. (2015). *Superforecasting: The Art and Science of Prediction.* Crown Publishers.**  
   Core source for reference class forecasting as the #1 calibration technique. Chapter 6 ("Superquants?") documents the outside-view technique and its superiority to the inside view in geopolitical and economic forecasting domains.

2. **Kahneman, D. & Lovallo, D. (1993). "Timid Choices and Bold Forecasts: A Cognitive Perspective on Risk Taking." *Management Science*, 39(1).**  
   Original academic framing of inside-view vs outside-view distinction; validates the base rate approach.

3. **Polymarket resolution data (public):** Polymarket publishes resolved market outcomes via their Gamma API. Base rates for common reference classes (elections, sports) are computable from their public dataset; 2-year historical windows cover multiple major election cycles and sports seasons.

4. **Kalshi public market data:** Kalshi's REST API provides resolved contract data for economic threshold events (FOMC decisions, CPI, unemployment). Directly feeds the `economic_threshold` reference class.

5. **Wilson, E.B. (1927). "Probable Inference, the Law of Succession, and Statistical Inference." *JASA*, 22(158), 209–212.**  
   Original derivation of the Wilson score interval used for `base_rate_confidence` calculation.

---

*Prepared by Nova (PM). For architecture and implementation, route to Atlas.*
