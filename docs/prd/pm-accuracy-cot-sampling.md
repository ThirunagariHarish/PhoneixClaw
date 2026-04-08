# PRD: CoT Self-Consistency Sampling (F-ACC-2)

**Feature ID:** F-ACC-2  
**Version:** 1.0  
**Status:** Draft  
**Author:** Nova (PM)  
**Date:** 2025-07-14  
**Parent PRD:** `docs/prd/polymarket-phase15.md` (Phase 15 — LLM Inference Pipeline)  
**Depends on:** F15-F3 (`LLMPredictionScorer` in `agents/polymarket/top_bets/llm_scorer.py`)  
**Superseded by:** None  

---

## 1. Problem

Phase 15 (F15-F3) establishes `LLMPredictionScorer.score(market)` as the primary scoring method for `pm_top_bets` recommendations. The current implementation makes **a single LLM call at `temperature=0`** (or whatever the default temperature is) and returns one `yes_probability` value. This has two structural weaknesses:

1. **Single-pass variance is unquantified.** A single sample from a stochastic process (an LLM) gives no signal about whether the model would agree with itself if asked again. A probability of `0.72` returned once could be a lucky draw from a distribution with high spread (`[0.45, 0.72, 0.91, 0.68, 0.55]`) or a stable consensus (`[0.71, 0.72, 0.70, 0.73, 0.71]`). The caller cannot tell the difference.

2. **The `confidence_score` is not calibrated to model uncertainty.** Phase 15's `confidence_score` (0–100) is a composite heuristic that incorporates the LLM's own self-reported `"confidence"` JSON field. Self-reported LLM confidence is notoriously poorly calibrated — models systematically over-report certainty. There is no mechanism to detect when the model is genuinely unsure vs. confidently wrong.

The consequence: traders see a `confidence_score` of `82` on a bet where the underlying LLM would have returned probabilities ranging from `0.41` to `0.91` across five calls, and they have no warning that the model is highly uncertain. This is worse than no confidence score — it is false precision.

**Wang et al. (2022)** showed that sampling multiple chain-of-thought reasoning paths and marginalizing over them reduces variance by ~25–35% on complex reasoning tasks and improves calibration. The mechanism — called Self-Consistency — is directly applicable here: run the same scoring prompt N times with `temperature > 0`, collect the probability distribution, discard outliers, and use the trimmed mean as the final estimate. The spread of the retained samples is a free, calibration-quality signal of model uncertainty.

This feature wraps the existing single `LLMPredictionScorer.score()` call with a 5-sample self-consistency loop, adds outlier trimming, computes a consensus spread, and uses the spread to adjust the final `confidence_score` up or down — making the score honest about when the LLM agrees with itself and when it does not.

**Sources:**
- Wang et al. (2022). "Self-Consistency Improves Chain of Thought Reasoning in Language Models." *arXiv:2203.11171*. https://arxiv.org/abs/2203.11171
- Kadavath et al. (2022). "Language Models (Mostly) Know What They Know." *arXiv:2207.05221*. https://arxiv.org/abs/2207.05221 (on LLM self-reported confidence calibration)

---

## 2. Target Users & Jobs-to-Be-Done

| User Segment | Job-to-Be-Done |
|---|---|
| **Solo discretionary trader (primary)** | "When I look at a Top Bet card with `confidence_score = 82`, I want to know whether the AI genuinely agrees with itself or is randomly guessing — so I can weight my position sizing accordingly." |
| **Evidence-based trader** | "Show me an 'Agreement' signal on each recommendation so I can deprioritize bets where the AI is uncertain without reading the raw probability number." |
| **Strategy improver / back-tester** | "Store all N raw probability samples so I can analyse whether high-spread bets outperform or underperform low-spread bets over time, and tune the spread thresholds." |

---

## 3. Goals & Non-Goals

### Goals
- Wrap `LLMPredictionScorer.score()` to run N=5 parallel LLM calls with `temperature=0.7`.
- Compute a trimmed mean (discard min + max) as the final `yes_probability`.
- Compute a **consensus spread** (max − min of retained samples) as a calibration signal.
- Adjust `confidence_score` upward when spread is low (model self-agreement) and downward when spread is high (model uncertainty).
- Store all N raw samples in `pm_top_bets.sample_probabilities` (JSONB) for auditability and future analysis.
- Store `consensus_spread` (FLOAT) in `pm_top_bets` for filtering and display.
- Expose `sample_probabilities` and `consensus_spread` in the `GET /api/polymarket/top-bets` response.
- Show an "Agreement" indicator on each `TopBetCard` in the dashboard with color-coded severity.
- Keep latency ≤ 15 s p95 for the full N=5 sampling loop by running all calls with `asyncio.gather`.
- Allow N=1 as a config option to disable self-consistency and revert to single-pass behavior.

### Non-Goals
- **Streaming individual sample results to the UI** — only the final aggregated result is surfaced.
- **Adaptive N** — N is always the configured constant (default 5); dynamic sample count is a future concern.
- **Cross-model sampling** — all N samples use the same configured LLM; multi-model ensembling is F-ACC-3's domain.
- **Re-running sampling on user demand** — samples are computed once per scoring cycle; re-score-on-demand is a future phase.
- **Changing the underlying LLM prompt** — this feature uses the identical prompt from F15-F3; prompt engineering is separate.
- **UI redesign of TopBetCard** — only the "Agreement" sub-indicator is added; no other card layout changes.
- **Changing how Bull/Bear steps in F-ACC-1 (Debate Pipeline) are sampled** — if the Debate Pipeline is active, sampling runs on the Judge step only.

---

## 4. Success Metrics

| # | Metric | Target | How Measured |
|---|---|---|---|
| M1 | Consensus spread < 0.10 for ≥ 80% of scored markets | ≥ 80% of `pm_top_bets` rows where `scorer_type = 'llm_rag'` have `consensus_spread < 0.10` | DB query against `pm_top_bets` |
| M2 | Brier score improvement vs single-pass on held-out test set | ≥ 5% reduction in Brier score vs single-pass baseline | `pm_model_evaluations` rows comparing `llm_rag_single` vs `llm_rag_sampled` |
| M3 | Latency for N=5 parallel calls | p95 ≤ 15 s | API response timing on `POST /api/polymarket/top-bets/score` or agent activity log |
| M4 | `sample_probabilities` populated on all LLM-scored bets | 100% of `pm_top_bets` rows with `scorer_type = 'llm_rag'` have non-null `sample_probabilities` | DB null-check |
| M5 | `confidence_score` adjustments applied correctly | 100% of rows with `consensus_spread < 0.05` show `confidence_score` boosted; 100% of rows with `consensus_spread > 0.20` show `confidence_score` penalised | DB validation query |

---

## 5. User Stories

| ID | Story | Priority |
|---|---|---|
| US-ACC2-1 | As a trader, I want the AI's probability estimate to be based on multiple reasoning attempts — not a single guess — so that the number I see reflects genuine model consensus rather than a lucky draw. | P0 |
| US-ACC2-2 | As a trader, I want to see an "Agreement" indicator on each bet card (High / Moderate / Low) so I can quickly identify bets where the AI is uncertain without reading raw numbers. | P0 |
| US-ACC2-3 | As a trader, I want the confidence score to be automatically penalised when the AI's five attempts disagree significantly, so I am not misled by false precision on uncertain markets. | P0 |
| US-ACC2-4 | As a trader, I want to hover over the Agreement indicator and see the raw probability samples, so I can judge the spread myself if I want deeper insight. | P1 |
| US-ACC2-5 | As an operator, I want to configure N, temperature, and the spread thresholds in `config.yaml` — and be able to set N=1 to disable sampling entirely — without touching application code. | P1 |

---

## 6. Acceptance Criteria

### AC-1 — Multi-sample scoring loop (US-ACC2-1)
- **Given** `n_samples = 5` and `sample_temperature = 0.7` are set in `agents/polymarket/top_bets/config.yaml`,  
  **When** `LLMPredictionScorer.score(market)` is invoked,  
  **Then** exactly 5 concurrent LLM calls are made using `asyncio.gather`; each call uses the same prompt from F15-F3 with `temperature = 0.7`; the scorer does **not** block on each call sequentially.

### AC-2 — Trimmed mean computation (US-ACC2-1)
- **Given** the 5 calls return `yes_probability` values, e.g. `[0.72, 0.68, 0.75, 0.71, 0.41]`,  
  **When** `trim_outliers = true` in config,  
  **Then** the single highest value (`0.75`) and single lowest value (`0.41`) are discarded; the final `yes_probability` is the mean of the remaining 3 values (`0.72 + 0.68 + 0.71) / 3 = 0.703`); this value is stored in `pm_top_bets.yes_probability`.  
  *(Note: yes_probability maps to the `edge_bps` derived field in Phase 15 — Atlas to confirm column name if it differs.)*

### AC-3 — Consensus spread computation (US-ACC2-1, US-ACC2-3)
- **Given** the retained (non-trimmed) probability values are `[0.72, 0.68, 0.71]`,  
  **When** the scorer finalises,  
  **Then** `consensus_spread = max(retained) - min(retained) = 0.72 - 0.68 = 0.04`; this value is stored in `pm_top_bets.consensus_spread`.

### AC-4 — Spread-based confidence adjustment (US-ACC2-3)
- **Given** `spread_boost_threshold = 0.05` and `spread_penalty_threshold = 0.20` in config,  
  **When** `consensus_spread < 0.05`,  
  **Then** `confidence_score` is increased by `+5` (capped at 100) before persisting the row.  
  **When** `consensus_spread > 0.20`,  
  **Then** `confidence_score` is decreased by `15` (floored at 0) before persisting the row.  
  **When** `0.05 ≤ consensus_spread ≤ 0.20`,  
  **Then** `confidence_score` is unchanged.

### AC-5 — Raw samples persisted (US-ACC2-4)
- **Given** the 5 raw probability values are `[0.72, 0.68, 0.75, 0.71, 0.41]`,  
  **When** the `pm_top_bets` row is inserted or updated,  
  **Then** `sample_probabilities` JSONB column contains the full list of all N raw values (including the trimmed outliers) in call order: `[0.72, 0.68, 0.75, 0.71, 0.41]`; the trimmed outliers are **not** removed from this stored list.

### AC-6 — API response fields (US-ACC2-4)
- **Given** `pm_top_bets` rows with `sample_probabilities` and `consensus_spread` populated,  
  **When** `GET /api/polymarket/top-bets` is called,  
  **Then** each item in the response includes:  
  - `sample_probabilities: [float]` — the full N raw samples (order preserved)  
  - `consensus_spread: float` — max minus min of retained samples  
  Both fields are non-null for rows scored by `scorer_type = 'llm_rag'`; both fields are `null` for rows scored by `scorer_type = 'heuristic'`.

### AC-7 — Agreement indicator in UI (US-ACC2-2, US-ACC2-4)
- **Given** a `TopBetCard` renders a bet with `consensus_spread` populated,  
  **When** the card renders,  
  **Then** an "Agreement" sub-row is shown immediately below the confidence bar, displaying:  
  - `consensus_spread < 0.05`: green filled circle icon + label **"High agreement"**  
  - `0.05 ≤ consensus_spread ≤ 0.20`: yellow filled circle icon + label **"Moderate agreement"**  
  - `consensus_spread > 0.20`: red filled circle icon + label **"Low agreement — treat with caution"**  
  **When** the user hovers over the Agreement indicator,  
  **Then** a tooltip renders showing all raw `sample_probabilities` values as a comma-separated list (e.g. `Samples: 0.72, 0.68, 0.75, 0.71, 0.41`).  
  **When** `consensus_spread` is `null` (heuristic-scored bet),  
  **Then** no Agreement indicator is shown.

### AC-8 — N=1 disables sampling (US-ACC2-5)
- **Given** `n_samples = 1` in `config.yaml`,  
  **When** `LLMPredictionScorer.score(market)` is invoked,  
  **Then** exactly 1 LLM call is made (same behaviour as Phase 15 baseline); `sample_probabilities` stores a single-element array; `consensus_spread` is stored as `0.0`; no trimming is applied; confidence adjustment is not applied.

---

## 7. DB Changes

> These columns are **additive** to the `pm_top_bets` table defined in Phase 15 (migration `032_pm_phase15.py`). A new migration file is required.

**Migration file:** `shared/db/migrations/033_pm_acc2_cot_sampling.py`

### `pm_top_bets` — new columns

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `sample_probabilities` | JSONB | YES | NULL | All N raw `yes_probability` values from each LLM call, in call order. E.g. `[0.72, 0.68, 0.75, 0.71, 0.41]`. Null for heuristic-scored rows. |
| `consensus_spread` | FLOAT | YES | NULL | `max(retained) - min(retained)` after trimming. Null for heuristic-scored rows. `0.0` when `n_samples = 1`. |

**No new tables.** No changes to any other table.

**Index:** `(consensus_spread)` — partial index `WHERE consensus_spread IS NOT NULL` to support dashboard filtering by agreement level.

---

## 8. API Changes

> All changes are additive to existing endpoints defined in Phase 15. No endpoint is renamed or removed.

### `GET /api/polymarket/top-bets`

**Response shape change (additive):**  
Each object in the `bets[]` array gains two new optional fields:

```jsonc
{
  // ... all existing Phase 15 fields ...
  "sample_probabilities": [0.72, 0.68, 0.75, 0.71, 0.41],  // null if heuristic
  "consensus_spread": 0.04                                   // null if heuristic
}
```

No new endpoints are introduced. No existing field names or types are changed.

---

## 9. UI Changes

> All changes are confined to the `TopBetCard` component. No other UI components are modified.

**File:** `apps/dashboard/src/components/polymarket/TopBetCard.tsx`

### Agreement indicator sub-row

Inserted immediately below the `confidence_score` progress bar, above the "AI Reasoning" expandable section.

**Render logic (pseudocode — for product clarity, not implementation):**
```
if consensus_spread is null → render nothing
else if consensus_spread < 0.05  → green dot + "High agreement"
else if consensus_spread ≤ 0.20  → yellow dot + "Moderate agreement"
else                              → red dot + "Low agreement — treat with caution"
```

**Tooltip on hover:**  
Shows the raw sample list: `Samples: 0.72, 0.68, 0.75, 0.71, 0.41`  
Format: values rounded to 2 decimal places, comma-separated.

**Visual spec:**
- Dot icon: 8 px filled circle using Tailwind `text-green-400` / `text-yellow-400` / `text-red-400`
- Label: `text-xs` weight `font-medium`
- Tooltip: standard dashboard tooltip component (shadcn/ui `Tooltip`); no new tooltip component needed

---

## 10. Configuration

> All parameters live in `agents/polymarket/top_bets/config.yaml` under a new `cot_sampling:` key.

```yaml
cot_sampling:
  n_samples: 5                    # Number of LLM calls per market. Set to 1 to disable sampling.
  sample_temperature: 0.7         # Temperature for each sampling call. Must be > 0 for variance.
  trim_outliers: true             # If true, discard single min and single max before computing mean.
  spread_boost_threshold: 0.05    # Boost confidence_score +5 if consensus_spread below this.
  spread_penalty_threshold: 0.20  # Penalise confidence_score -15 if consensus_spread above this.
```

**Validation rules (enforced at agent startup):**
- `n_samples` must be ≥ 1. If `n_samples < 3`, `trim_outliers` is automatically coerced to `false` (cannot trim from fewer than 3 values).
- `sample_temperature` must be in range `(0.0, 2.0]`. A value of `0.0` is rejected at startup with an error — use `n_samples: 1` to revert to deterministic single-pass.
- `spread_boost_threshold` must be < `spread_penalty_threshold`.

---

## 11. Integration Notes

### Integration with F15-F3 (`LLMPredictionScorer`)
- **Minimal invasive change.** The existing `score(market)` method body is wrapped: instead of calling `_call_llm(prompt)` once, it calls `asyncio.gather(*[_call_llm(prompt) for _ in range(n_samples)])`.
- The `_call_llm` helper must accept a `temperature` override parameter. If the existing helper does not, it requires a one-line signature change — no logic change.
- The rest of the `score()` method (building the prompt, retrieving similar markets from `EmbeddingStore`, parsing the JSON response) is **unchanged**.

### Integration with F-ACC-1 (Debate Pipeline Scorer) — if both features are active
- F-ACC-1 introduces a three-step pipeline: Bull → Bear → Judge.
- Self-consistency sampling **applies to the Judge step only** (the step that emits `yes_probability`).
- Bull and Bear steps are deterministic single-calls — running N=5 on them would triple latency for no probability-estimation benefit.
- If F-ACC-1 is not active, self-consistency sampling applies directly to the single `LLMPredictionScorer.score()` call.

### Integration with `pm_model_evaluations` (F15-F4)
- Phase 15 defines a `model_type` field in `pm_model_evaluations` as `VARCHAR(32)` with known values `llm_rag` and `heuristic`.
- F-ACC-2 introduces a new logical model variant: `llm_rag_sampled` (N=5, trimmed mean) vs. `llm_rag_single` (N=1 or pre-F-ACC-2 baseline).
- Atlas should consider whether `scorer_type` in `pm_top_bets` needs a new value `llm_rag_sampled` or whether this is tracked solely via `n_samples` in the evaluation metadata.

### Latency budget
- Phase 15 context: `LLMPredictionScorer` is assumed to complete within ~6 s single-call p95 (consistent with OpenAI GPT-4o typical response times for a ~400-token prompt).
- With `asyncio.gather`, all 5 calls are in-flight simultaneously. Wall-clock time ≈ the slowest single call, not 5×. Target: ≤ 15 s p95 for the full gather.
- If `asyncio.gather` wall-clock exceeds 15 s on ≥ 5% of calls, Atlas should implement a timeout per individual call (suggested: 12 s hard timeout per call; if a call times out, its slot is excluded from the sample set; the trimmed mean is computed from remaining returned values).

---

## 12. Open Questions

> These are product-level uncertainties that do not block PRD finalisation but should be resolved by Atlas during architecture or by the operator before deployment.

| # | Question | Owner | Impact |
|---|---|---|---|
| OQ-1 | If one or more of the 5 calls returns a parse error (malformed JSON from LLM), should that call be excluded from the sample set (degraded N) or should the whole scoring attempt retry? The PRD requires storing N raw samples — a parse error leaves a gap. | Atlas | Error handling spec for `_call_llm` |
| OQ-2 | `trim_outliers: true` removes 1 min and 1 max from N=5, leaving 3 retained values. Should the spread thresholds (`0.05` / `0.20`) be calibrated on the retained 3 values or the full 5? The PRD specifies retained values — but the product owner should validate this is the right reference set for the confidence adjustment. | Product owner | Threshold calibration |
| OQ-3 | When `n_samples = 1`, `consensus_spread` is stored as `0.0`. This means a single-pass bet will always show as "High agreement" if the spread indicator is rendered. Should the indicator be hidden entirely when `n_samples = 1` (treat it as `null`), or is "High agreement (single sample)" acceptable? | Product owner | UI agreement indicator rendering |
| OQ-4 | The `spread_boost_threshold` (+5 to confidence) and `spread_penalty_threshold` (−15 to confidence) are asymmetric — the penalty is 3× the boost. This is intentional (being wrong about confidence is more costly than being overly cautious) but should be validated against the Phase 15 `confidence_score` distribution before deployment. | Atlas / Devin (calibration test) | Config defaults |

---

## 13. Research & Sources

| Claim | Source |
|---|---|
| Self-consistency sampling reduces variance ~25–35% on reasoning tasks | Wang et al. (2022). "Self-Consistency Improves Chain of Thought Reasoning in Language Models." arXiv:2203.11171. https://arxiv.org/abs/2203.11171 |
| LLM self-reported confidence is poorly calibrated; models over-report certainty | Kadavath et al. (2022). "Language Models (Mostly) Know What They Know." arXiv:2207.05221. https://arxiv.org/abs/2207.05221 |
| Marginalizing over multiple CoT paths improves calibration in addition to accuracy | Wang et al. (2022) ibid., Section 4.3 (calibration experiments) |
| Trimmed mean is a standard robust estimator for removing outliers from small samples | NIST/SEMATECH e-Handbook of Statistical Methods. Section 6.3.2.1: Trimmed Mean. https://www.itl.nist.gov/div898/handbook/prc/section2/prc22.htm |
| Brier score as calibration metric for probabilistic forecasts | Brier, G.W. (1950). "Verification of Forecasts Expressed in Terms of Probability." *Monthly Weather Review*. (standard reference; widely cited in prediction market literature) |

---

*End of PRD: F-ACC-2 — CoT Self-Consistency Sampling*
