# PRD: Predictive Intelligence — Advanced Feature Engineering + Analyst-Aware Position Management

**Version:** 1.0
**Author:** Nova (PM Agent)
**Date:** 2026-04-11
**Status:** Draft — Pending Architecture Review
**Phoenix Version:** v1.15.3
**Stakeholder:** Harish Kumar (sole operator)

---

## 1. Problem

Phoenix's enrichment pipeline produces ~200 features across 8 categories, and its position monitors use a 4-indicator TA check to decide when to exit trades. Both systems have significant blind spots that leave money on the table and increase loss exposure:

### Enrichment Gaps (Feature Engineering)

**Hard-coded macro event dates.** FOMC, CPI, and NFP dates are static Python lists in `agents/backtesting/tools/enrich.py` (lines 693–736). They must be manually updated each year and contain no information about the *impact* of those events — only proximity. The system cannot answer "how did this stock react to the last CPI print?" or "was the last Fed decision hawkish or dovish?"

**No time series dynamics.** The feature set lacks regime awareness (bull/bear/sideways), trend persistence measures (autocorrelation, Hurst exponent), and volatility clustering signals. The ML model receives a snapshot of the market but cannot distinguish a mean-reverting environment from a trending one — a distinction that fundamentally changes whether a signal should be traded.

**No analyst behavior modeling.** Discord analysts are the primary signal source, yet the system treats every analyst identically. It cannot encode that "Analyst A typically exits at +5% within 3 days" while "Analyst B holds for weeks targeting +15%." These behavioral priors are critical for both entry decisions (is this analyst reliable?) and exit timing (when will the analyst likely sell?).

### Position Monitoring Gaps

**Minimal TA coverage.** `ta_check.py` computes exactly 4 indicators: RSI(14), MACD(12/26/9), Bollinger Bands(20,2), and 20-bar support/resistance. The backtest enrichment pipeline computes 30+ technical indicators — the position monitor sees a fraction of the available signal.

**Broken sell signal routing.** `PositionMicroAgent.receive_sell_signal()` exists (line 313 of `position_micro_agent.py`) and correctly appends signals + writes them to the workspace. However, `agent_gateway.py` never calls this method — analyst sell signals from Discord never reach the position monitors that need them. This is a confirmed routing bug.

**Empty analyst patterns.** The `analyst_patterns` parameter is accepted by `PositionMicroAgent.__init__()` and used in LLM prompts, but it is always passed as `{}`. The infrastructure exists; the data doesn't.

**No analyst exit prediction.** Position monitors have no model of *when* the analyst is likely to sell. They cannot distinguish "analyst usually sells after 2 days at +5%" from "analyst usually holds through earnings." This means the bot may hold too long (analyst already sold, stock reverses) or exit too early (analyst is still building the position).

**Unused data sources.** The codebase already integrates Unusual Whales (`shared/unusual_whales/client.py` — fully implemented with options flow, GEX, market tide) and has an IBKR adapter stub (`services/connector-manager/src/brokers/ibkr.py`). Neither feeds into position monitoring decisions.

### Quantified Impact

- **Sell signal routing bug**: Every analyst sell signal is silently dropped. If the analyst says "sell AAPL," the bot's position monitor for AAPL never receives it.
- **4 vs 30+ indicators**: Position monitors make exit decisions with ~13% of the technical signal available to the entry model.
- **Static event dates**: After December 2026, all FOMC/CPI/NFP proximity features become stale (return 0) unless manually updated.

---

## 2. Target Users & Jobs-to-be-Done

### Primary User: Harish Kumar (Solo Operator)

| Job | Current Pain | Desired Outcome |
|-----|-------------|-----------------|
| **Improve ML model accuracy** | ~200 features miss regime context, macro reactions, and analyst reliability signals | 60+ new features capturing time series dynamics, economic event reactions, and per-analyst behavior patterns |
| **Exit positions at better prices** | Position monitor uses 4 TA indicators and never receives sell signals | Monitor uses 15+ indicators, receives analyst sell signals, and predicts analyst exit timing |
| **Reduce manual maintenance** | Must hand-edit Python date lists for FOMC/CPI/NFP every year | Dynamic FRED API pulls always-current event schedules |
| **Leverage existing integrations** | Unusual Whales client and IBKR adapter sit unused | Options flow and real-time broker data feed into exit decisions |
| **Understand per-analyst edge** | All analysts treated identically by the system | Per-analyst behavior profiles (win rate, hold time, exit patterns) stored in DB and used for inference |

### Secondary User: The Agents Themselves

Claude SDK agents and Tier 2 micro-agents consume enriched features and TA signals. Richer inputs → better reasoning → better trades. The position monitor micro-agent specifically needs analyst context it currently lacks.

---

## 3. Goals & Non-Goals

### Goals

1. **G1** — Add 60+ new features to the enrichment pipeline across 3 new sub-categories: time series dynamics (~20), economic event reactions (~25), and analyst behavior (~15).
2. **G2** — Build a per-analyst behavior model that captures win rate, hold time distribution, exit P&L thresholds, time-of-day patterns, and conviction indicators.
3. **G3** — Fix sell signal routing so analyst sell signals reach position monitors in real time.
4. **G4** — Expand `ta_check.py` from 4 indicators to 15+ indicators, reusing computation from `enrich_single.py`.
5. **G5** — Wire Unusual Whales options flow and FRED macro data into the position monitor's exit urgency calculation.
6. **G6** — Implement an analyst exit prediction score (`analyst_exit_probability`, 0–100) that factors into the position monitor's urgency calculation.
7. **G7** — Maintain strict backtest ↔ live feature parity. Every feature computed in `enrich.py` must have a live equivalent in `enrich_single.py`.

### Non-Goals

- **Full IBKR order execution.** IBKR integration is limited to real-time data consumption (quotes, Level 2 depth, positions). Order execution remains via Robinhood MCP.
- **Replacing the ML model.** This PRD adds features and improves monitoring. Model architecture changes (new heads, ensemble redesign) are out of scope.
- **Multi-broker position reconciliation.** The system trades through Robinhood; IBKR is a data source only.
- **Automated analyst ranking/scoring for signal filtering.** The behavior model informs exit decisions; it does not gate entry decisions in this phase.
- **Dashboard UI changes.** New features and analyst profiles are stored in DB but dashboard visualization is deferred.

---

## 4. Success Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| **Feature count** | ~200 | 260+ | Count numeric columns in enriched.parquet after pipeline run |
| **Position monitor TA indicators** | 4 | 15+ | Count distinct indicators in `ta_check.py` output |
| **Sell signal delivery rate** | 0% (routing broken) | 100% of sell signals reach relevant position monitor | Integration test: publish sell signal → assert `receive_sell_signal()` called |
| **Analyst profile population** | 0 profiles | Profile exists for every analyst with ≥10 historical trades | Query `analyst_profiles` table after backtest |
| **Exit prediction accuracy** | N/A (no prediction) | Analyst exit probability score correlates (Pearson r ≥ 0.3) with actual exit timing within 24h | Backtest validation on held-out trades |
| **New data sources in exit decisions** | 0 | ≥ 2 (FRED macro + Unusual Whales flow) | Verify exit_decision.py output includes `fred_signals` and `options_flow_signals` keys |
| **Backtest ↔ live parity** | Parity maintained | Parity maintained (all new features present in both pipelines) | Diff feature lists from `enrich.py` vs `enrich_single.py` |
| **Unit test coverage for new code** | N/A | ≥ 80% line coverage on new modules | `pytest --cov` on new files |

---

## 5. User Stories

Full stories with acceptance criteria are in the companion file (`stories.md` — to be produced by Nova if requested). Summary below:

### US-1: Dynamic Economic Event Calendar (P0)

**As a** trading bot operator, **I want** FOMC, CPI, NFP, GDP, PPI, and other economic event dates pulled dynamically from the FRED API, **so that** the enrichment pipeline never goes stale and I don't have to manually update date lists.

**Acceptance Criteria:**
- Given the FRED API is reachable, when `enrich.py` runs, then it fetches event dates from FRED instead of using hard-coded lists.
- Given the FRED API is unreachable, when `enrich.py` runs, then it falls back to cached dates (last successful fetch stored on disk).
- Given a new economic indicator (e.g., GDP, PPI, ISM), when enrichment runs, then the output includes `days_to_gdp`, `days_to_ppi`, `days_to_ism`, etc.
- Given the same signal processed by both `enrich.py` and `enrich_single.py`, when compared, then all event proximity features match within ±1 day tolerance.

### US-2: Time Series Dynamics Features (P0)

**As a** trading bot operator, **I want** the enrichment pipeline to compute regime detection, trend persistence, volatility clustering, and mean-reversion signals, **so that** the ML model can distinguish between trending and mean-reverting market conditions.

**Acceptance Criteria:**
- Given enrichment runs on a trade, when the output is inspected, then it includes: `market_regime` (bull/bear/sideways), `hurst_exponent`, `autocorrelation_lag1` through `lag5`, `volatility_acceleration`, `mean_reversion_speed`, and `intraday_seasonality_score` — at minimum 15 new features.
- Given a strongly trending stock (e.g., 20-day returns > 10%), when the Hurst exponent is computed, then it returns H > 0.55.
- Given all new features, when `preprocess.py` runs, then they are auto-included (numeric, not in EXCLUDE_COLS).

### US-3: Per-Analyst Behavior Model (P0)

**As a** trading bot operator, **I want** the system to build and store a behavioral profile for each Discord analyst, **so that** position monitors and ML models can leverage analyst-specific patterns for better exit timing.

**Acceptance Criteria:**
- Given an analyst with ≥10 historical trades, when backtesting completes, then an `analyst_profile` record is created containing: rolling win rate (10/20 trades), average hold time, median exit P&L, exit P&L distribution quantiles (25th/50th/75th), time-of-day patterns, day-of-week patterns, and average conviction score.
- Given the profile is stored, when a live agent spawns a position monitor, then `analyst_patterns` is populated (not `{}`).
- Given the profile is stored, when enrichment runs, then ~15 analyst behavior features are added to the feature vector.

### US-4: Sell Signal Routing Fix (P0)

**As a** trading bot operator, **I want** analyst sell signals from Discord to be routed to the correct position monitor, **so that** the bot reacts to analyst exit calls instead of ignoring them.

**Acceptance Criteria:**
- Given a sell signal for ticker AAPL arrives via Discord, when it is processed by `agent_gateway.py`, then `receive_sell_signal()` is called on the `PositionMicroAgent` instance monitoring AAPL.
- Given a sell signal arrives for a ticker with no active position monitor, when processed, then it is logged as unroutable (no error, no silent drop).
- Given a sell signal is routed, when the position monitor's next check cycle runs, then `discord_urgency` is ≥ 40 and the signal content appears in LLM reasoning context.

### US-5: Expanded TA for Position Monitors (P1)

**As a** trading bot operator, **I want** the position monitor's TA check to use 15+ technical indicators (matching the richness of the entry enrichment), **so that** exit decisions are informed by the same signal depth as entry decisions.

**Acceptance Criteria:**
- Given `ta_check.py` runs, when the output is inspected, then it includes at minimum: RSI(14), MACD, Bollinger Bands, ADX, CCI, OBV, Stochastic, Williams %R, MFI, Keltner Channel, Ichimoku cloud distance, VWAP distance, volume Z-score, and SPY/VIX context — totaling ≥ 15 distinct indicators.
- Given computation functions exist in `enrich_single.py`, when `ta_check.py` is upgraded, then it imports and reuses those functions rather than reimplementing them.
- Given the expanded TA runs on 5-minute data, when timed, then it completes within 10 seconds (current 4-indicator check completes in ~3s).

### US-6: Options Flow + FRED Macro in Exit Decisions (P1)

**As a** trading bot operator, **I want** the position monitor to factor in Unusual Whales options flow and FRED macro data when calculating exit urgency, **so that** large put flows, GEX flips, and Treasury yield inversions contribute to exit timing.

**Acceptance Criteria:**
- Given the position monitor checks ticker AAPL, when Unusual Whales shows large put premium flow (> $1M) on AAPL, then exit urgency increases by ≥ 10 points.
- Given the 2Y/10Y Treasury yield spread inverts (goes negative), when the position monitor checks any long position, then a `macro_risk` urgency component is added.
- Given either API is unreachable, when the check cycle runs, then it degrades gracefully (zero urgency contribution, no error, no timeout > 5s).

### US-7: Analyst Exit Prediction (P2)

**As a** trading bot operator, **I want** the position monitor to compute an `analyst_exit_probability` score based on the analyst's historical behavior, **so that** the bot can anticipate when the analyst is likely to sell and act preemptively.

**Acceptance Criteria:**
- Given a position held for 3 days where the analyst's median hold time is 2 days, when the exit probability is computed, then it returns ≥ 60.
- Given a position at +4% P&L where the analyst's median exit P&L is +5%, when computed, then exit probability is ≥ 50.
- Given the `analyst_exit_probability` is > 70, when added to the urgency calculation, then total urgency increases by 15–25 points.
- Given an analyst with < 10 historical trades, when exit probability is requested, then it returns a neutral 30 (insufficient data, don't act on it).

### US-8: IBKR Real-Time Data Feed (P2)

**As a** trading bot operator, **I want** the IBKR adapter to provide real-time quotes and Level 2 order book depth to position monitors, **so that** exit decisions use live bid/ask spreads and order flow instead of delayed yfinance data.

**Acceptance Criteria:**
- Given IBKR TWS/Gateway is running, when the adapter's `get_quote()` is called, then it returns real-time bid, ask, last, and volume within 500ms.
- Given Level 2 data is subscribed, when order book depth changes, then the adapter exposes top 5 bid/ask levels.
- Given IBKR is unavailable, when the position monitor runs, then it falls back to yfinance (current behavior) with a logged warning.

---

## 6. Feature Requirements

### Area 1: Advanced Feature Engineering

#### 1a. Time Series Dynamics Features (~20 new features)

| Feature | Computation | Source |
|---------|-------------|--------|
| `market_regime` | HMM (2–3 states) on 60-day log returns + volatility; or simplified rolling Sharpe sign over 20/60 days | yfinance daily OHLCV |
| `regime_confidence` | HMM posterior probability of current state (0–1) | hmmlearn library |
| `hurst_exponent` | Rescaled range (R/S) analysis over 100-day window | numpy (pure computation) |
| `trend_persistence` | Binary: H > 0.55 = trending, H < 0.45 = mean-reverting | Derived from hurst_exponent |
| `autocorrelation_lag1` through `lag5` | Autocorrelation of daily returns at lags 1–5 | pandas .autocorr() |
| `volatility_acceleration` | 5-day realized vol / 20-day realized vol | numpy std of log returns |
| `volatility_regime` | Binary: vol_acceleration > 1.5 = vol expanding | Derived |
| `garch_vol_forecast` | GARCH(1,1) conditional variance forecast (simplified: EWMA λ=0.94) | numpy |
| `mean_reversion_speed` | Half-life of Ornstein-Uhlenbeck process fit on residuals from 20-day SMA | OLS regression |
| `intraday_seasonality_hour` | Average return for current hour-of-day over trailing 20 days | yfinance 1h data |
| `intraday_vol_ratio` | Current hour volatility / average hourly volatility | yfinance 1h data |
| `return_skewness_20d` | 20-day rolling skewness of daily returns | pandas .skew() |
| `return_kurtosis_20d` | 20-day rolling kurtosis of daily returns | pandas .kurt() |
| `fractal_dimension` | Higuchi fractal dimension approximation over 50-day window | numpy |
| `trend_strength_composite` | Weighted combination: ADX + Hurst + autocorrelation_lag1 | Derived |

**New dependencies:** `hmmlearn` (pip install hmmlearn) for HMM-based regime detection. Fallback: rolling Sharpe sign if hmmlearn unavailable.

#### 1b. Economic Event Reaction Features (~25 new features)

| Feature | Computation | Source |
|---------|-------------|--------|
| `days_to_fomc` | Dynamic from FRED API release schedule | FRED API (`fredapi` library) |
| `days_to_cpi` | Dynamic from FRED API (series CPIAUCSL) | FRED API |
| `days_to_nfp` | Dynamic from FRED API (series PAYEMS) | FRED API |
| `days_to_gdp` | Dynamic from FRED API (series GDP) | FRED API |
| `days_to_ppi` | Dynamic from FRED API (series PPIACO) | FRED API |
| `days_to_retail_sales` | Dynamic from FRED API (series RSAFS) | FRED API |
| `days_to_ism_mfg` | Dynamic from FRED API (series MANEMP proxy) | FRED API |
| `days_to_housing_starts` | Dynamic from FRED API (series HOUST) | FRED API |
| `days_to_jobless_claims` | Dynamic (weekly, every Thursday) | FRED API (series ICSA) |
| `{event}_within_3d` | Boolean flags for each event | Derived |
| `last_cpi_surprise` | Actual minus consensus (BLS release vs survey) | FRED + yfinance reaction |
| `last_cpi_stock_reaction_1d` | Ticker's 1-day return after last CPI release | yfinance |
| `last_cpi_stock_reaction_5d` | Ticker's 5-day return after last CPI release | yfinance |
| `last_fomc_rate_surprise_bps` | Actual rate change minus expected (Fed funds futures) | FRED (series DFF) |
| `last_fomc_stock_reaction_1d` | Ticker's 1-day return after last FOMC | yfinance |
| `last_nfp_surprise_pct` | (Actual - Consensus) / Consensus | FRED |
| `earnings_last_surprise` | Last EPS surprise (actual - estimate) / estimate | yfinance .earnings_dates |
| `earnings_last_reaction_1d` | 1-day return post-last-earnings | yfinance |
| `earnings_last_reaction_5d` | 5-day return post-last-earnings | yfinance |
| `sector_rotation_signal` | Relative strength: growth sectors (XLK+XLY) minus defensive (XLU+XLP+XLV) over 20 days | yfinance sector ETFs |
| `economic_surprise_index` | Rolling count of beats minus misses across last 10 releases | FRED multiple series |
| `treasury_2y10y_spread` | 10Y yield minus 2Y yield | FRED (DGS10, DGS2) |
| `treasury_spread_change_5d` | 5-day change in 2Y/10Y spread | Derived |
| `fed_funds_rate` | Current effective federal funds rate | FRED (DFF) |
| `dxy_proxy_return_5d` | 5-day return of UUP (Dollar bull ETF) | yfinance |

**New dependency:** `fredapi` (pip install fredapi). Free API key from fred.stlouisfed.org.

**Caching strategy:** FRED data changes daily at most. Cache responses to disk with 24-hour TTL. Fall back to cached data if API unreachable.

#### 1c. Analyst Behavior Features (~15 new features)

| Feature | Computation | Source |
|---------|-------------|--------|
| `analyst_win_rate_10` | Rolling win rate over last 10 trades | Analyst profile (DB) |
| `analyst_win_rate_20` | Rolling win rate over last 20 trades | Analyst profile |
| `analyst_avg_hold_hours` | Mean hold time in hours across historical trades | Analyst profile |
| `analyst_median_exit_pnl` | Median P&L % at exit | Analyst profile |
| `analyst_exit_pnl_p25` | 25th percentile exit P&L | Analyst profile |
| `analyst_exit_pnl_p75` | 75th percentile exit P&L | Analyst profile |
| `analyst_avg_hold_hours_p25` | 25th percentile hold time | Analyst profile |
| `analyst_avg_hold_hours_p75` | 75th percentile hold time | Analyst profile |
| `analyst_tod_morning_pct` | % of trades entered before 11:00 ET | Analyst profile |
| `analyst_tod_afternoon_pct` | % of trades entered after 14:00 ET | Analyst profile |
| `analyst_dow_monday_pct` | % of trades on Monday | Analyst profile |
| `analyst_dow_friday_pct` | % of trades on Friday | Analyst profile |
| `analyst_conviction_score` | Composite: message length + ticker mention count + sentiment intensity | NLP on Discord messages |
| `analyst_post_earnings_sell_pct` | % of trades analyst exits within 2 days of earnings | Analyst profile |
| `analyst_avg_days_to_sell` | Mean calendar days from entry to exit | Analyst profile |

**Data source:** Computed from historical trade records during backtesting (`transform.py` output). Stored in DB as `analyst_profiles` table (new). Injected into `enrich.py` and `enrich_single.py` as a lookup.

### Area 2: Intelligent Position Tracking

#### 2a. Analyst Behavior Model (Database-Backed)

**What it stores:**

```
analyst_profiles table:
  - analyst_id (FK → analysts)
  - channel_id
  - rolling_win_rate_10, rolling_win_rate_20
  - avg_hold_hours, median_hold_hours
  - hold_hours_p25, hold_hours_p50, hold_hours_p75
  - avg_exit_pnl_pct, median_exit_pnl_pct
  - exit_pnl_p25, exit_pnl_p50, exit_pnl_p75
  - typical_exit_threshold_pct (mode of exit P&L buckets)
  - tod_distribution (JSONB: {morning: 0.4, midday: 0.3, afternoon: 0.3})
  - dow_distribution (JSONB: {mon: 0.2, tue: 0.15, ...})
  - post_earnings_sell_rate
  - avg_conviction_score
  - total_trades_analyzed
  - last_updated_at
```

**Population flow:**
1. `transform.py` extracts trade history with entry/exit timestamps, P&L, and message content.
2. New tool: `compute_analyst_profile.py` — runs after transform, computes all profile fields, writes to `output/analyst_profile.json`.
3. `create_live_agent.py` packages the profile into `manifest.json` and writes it to the live agent's `config.json`.
4. During live trading: profile is incrementally updated after each closed position (append new trade data, recompute rolling metrics).

#### 2b. Sell Signal Routing Fix

**Current state:** `agent_gateway.py` has no code path that calls `PositionMicroAgent.receive_sell_signal()`. The method exists, it works, but it's never invoked.

**Required change:** When a sell/close signal for a ticker arrives (from `message_ingestion.py` → Redis stream → signal processing), `agent_gateway.py` must:
1. Look up active position monitors by ticker.
2. Call `receive_sell_signal(signal_data)` on each matching monitor.
3. Log the routing (ticker, monitor session_id, signal content).

This is a ~20-line routing fix in `agent_gateway.py`, not an architectural change.

#### 2c. Analyst Exit Prediction

**Algorithm (rule-based, not ML):**

```
analyst_exit_probability(position, analyst_profile):
  score = 30  # base (neutral)

  # Hold time factor: how long held vs analyst's typical hold
  hold_ratio = current_hold_hours / analyst.median_hold_hours
  if hold_ratio > 1.5:    score += 25  # well past typical hold
  elif hold_ratio > 1.0:  score += 15
  elif hold_ratio > 0.7:  score += 5

  # P&L factor: current P&L vs analyst's typical exit P&L
  pnl_ratio = current_pnl_pct / analyst.median_exit_pnl_pct
  if pnl_ratio > 1.2:     score += 20  # past typical exit point
  elif pnl_ratio > 0.8:   score += 10

  # Time-of-day factor
  if current_hour in analyst.peak_selling_hours:
    score += 10

  # Day-of-week factor
  if current_dow in analyst.peak_selling_days:
    score += 5

  # Upcoming event factor
  if days_to_earnings <= 2 and analyst.post_earnings_sell_rate > 0.5:
    score += 15

  return min(score, 100)
```

**Integration:** `analyst_exit_probability` is added to the urgency calculation in `exit_decision.py` with a configurable weight (default: 0.3x of raw score added to total urgency).

#### 2d. Richer TA for Exits

Upgrade `ta_check.py` from 4 to 15+ indicators:

| Indicator | Current | Proposed | Urgency Contribution |
|-----------|---------|----------|---------------------|
| RSI(14) | Yes | Yes | Overbought/oversold: +20 |
| MACD(12/26/9) | Yes | Yes | Bearish cross: +10 |
| Bollinger Bands(20,2) | Yes | Yes | Above upper: +15 |
| Support/Resistance(20) | Yes | Yes | Near resistance: +10 |
| ADX(14) | No | **Add** | ADX < 20 (weak trend) + losing position: +10 |
| CCI(20) | No | **Add** | CCI > 200 (overbought) or < -200: +10 |
| OBV divergence | No | **Add** | Price up but OBV down: +15 (bearish divergence) |
| Stochastic(14,3) | No | **Add** | %K > 80 + %K crosses below %D: +10 |
| Williams %R(14) | No | **Add** | > -20 (overbought for longs): +5 |
| MFI(14) | No | **Add** | > 80 (overbought): +10 |
| Keltner Channel | No | **Add** | Price outside upper Keltner: +10 |
| Ichimoku cloud distance | No | **Add** | Price enters cloud from above: +15 |
| VWAP distance | No | **Add** | Price > 2 std above VWAP: +10 |
| Volume Z-score | No | **Add** | Volume Z > 2 on red candle: +10 |
| SPY correlation shift | No | **Add** | 5-day correlation < 0.3 (decorrelation): +10 |
| VIX level context | No | **Add** | VIX > 25 for long positions: +5 |

**Implementation approach:** Extract shared computation functions from `enrich_single.py` into a `shared/ta/indicators.py` module. Both `ta_check.py` and `enrich_single.py` import from it — single source of truth.

#### 2e. Additional Data Sources for Exit Decisions

**Unusual Whales Options Flow (already built, needs wiring):**
- `shared/unusual_whales/client.py` is fully implemented with `get_options_flow()`, `get_gex()`, `get_market_tide()`.
- Wire into `exit_decision.py`: call `get_options_flow(ticker)` → if large put premium (> $500K) on held ticker, add urgency +10–20.
- Wire GEX: if `total_gex` flips sign (positive → negative), add urgency +15 (gamma flip = dealer hedging reversal).
- Wire market tide: if `put_call_ratio` > 1.5, add macro urgency +5.

**FRED Macro Data (new integration):**
- Treasury 2Y/10Y spread: `FRED.get_series('DGS10')` minus `FRED.get_series('DGS2')`. Inversion = macro risk, urgency +5.
- VIX term structure: compare VIX (spot) to VIX3M (3-month). Backwardation (VIX > VIX3M) = panic, urgency +10.
- Fed funds rate change: if rate changed in last 5 days, urgency +5 (increased volatility).

**Cross-Asset Correlation Monitor (new computation):**
- 20-day rolling correlation of held ticker with SPY, sector ETF, and VIX.
- If SPY correlation drops below 0.3 (was > 0.6), flag decorrelation: urgency +10.
- If VIX correlation flips positive for a long position (stock moving with fear index): urgency +10.

**Volume/Order Flow Analysis (enhanced):**
- OBV divergence: price making new highs but OBV declining → bearish divergence, urgency +15.
- Volume-weighted momentum: VWAP slope over 20 bars. Negative slope for long position: urgency +5.
- These can be computed from existing yfinance data (no new API needed).

### Area 3: Time-Series Awareness for Exits

| Signal | Logic | Urgency Contribution |
|--------|-------|---------------------|
| Overstay detection | `current_hold_hours > analyst.hold_hours_p75 * 1.5` | +15 (analyst almost certainly already sold) |
| Time-of-day exit window | Current time matches analyst's peak sell hour (±1h) | +10 |
| Friday afternoon risk | Friday after 2 PM ET + positive P&L | +10 (weekend gap risk) |
| Pre-market/after-hours | Position check during extended hours | Reduce urgency by 50% (can't execute cleanly) |
| Market session transition | 9:30–10:00 AM ET (opening volatility) | Flag for review but don't auto-exit |
| End-of-day squeeze | 3:45–4:00 PM ET + urgency > 40 | +10 (last chance for clean exit) |

---

## 7. Constraints (from User)

1. **Combined feature** — both areas (feature engineering + position management) ship together since they're intertwined (analyst behavior model feeds both).
2. **Data sources** — Use free APIs (FRED, yfinance) PLUS Interactive Brokers (IBKR). IBKR integration exists as a stub in `services/connector-manager/src/brokers/ibkr.py`; wire it in using `ib_insync` library.
3. **Per-analyst modeling** — Analyst behavior is modeled per individual signal source, not aggregated across all analysts.
4. **Phased delivery** — Multi-phase plan is acceptable. Plan first, then implement.
5. **Position monitor focus** — Special attention to improving the sub-agent (position monitor) decision-making with additional data sources.
6. **Python 3.11+** — All new code must be compatible. Ruff linting, 120-char lines.
7. **Tier 2 execution model** — Position monitors run as Python + cheap LLM (OpenRouter), not full Claude SDK sessions. Keep computation lightweight.
8. **Backtest ↔ live parity** — New features auto-picked up by `preprocess.py` if numeric and not in EXCLUDE_COLS. Must be available in both pipelines.
9. **FRED API** — Free (requires a free API key for most endpoints). Key stored in `.env` as `FRED_API_KEY`.
10. **IBKR adapter** — Currently a stub. Full implementation requires `ib_insync` library and a running TWS/IB Gateway instance.

---

## 8. Open Questions (Needs User Input)

| # | Question | Impact | Default if unanswered |
|---|----------|--------|-----------------------|
| OQ-1 | Should the analyst behavior model gate entry decisions (skip trades from low-win-rate analysts) or only inform exits? | Scope of analyst model usage | Exits only (this PRD) |
| OQ-2 | What is the acceptable latency for IBKR data in exit decisions? Is 500ms round-trip sufficient? | IBKR integration depth | 500ms target, fallback to yfinance |
| OQ-3 | Should FRED data be fetched per-check-cycle (every 2 min) or cached with longer TTL (1 hour)? | API usage, freshness | 1-hour cache TTL (macro data doesn't change intraday) |
| OQ-4 | Is there a budget for Unusual Whales API calls per day? The position monitor may call it every 2 minutes per position. | Cost | Batch: 1 call per ticker per 5 minutes (cache) |
| OQ-5 | Should the analyst exit prediction be rule-based (as proposed) or ML-based (logistic regression on analyst features)? | Complexity, accuracy | Rule-based in Phase 1; ML in future phase |

---

## 9. Research & Sources

| Claim | Source |
|-------|--------|
| FRED API provides 800,000+ free economic time series with 120 requests/minute | [FRED API docs](https://fred.stlouisfed.org/docs/api/fred/); [dev.to analysis](https://dev.to/0012303/fred-has-a-free-api-800000-us-economic-time-series-at-your-fingertips-46e9) |
| `fredapi` Python library returns pandas DataFrames, supports ALFRED revisions | [GitHub: mortada/fredapi](https://github.com/mortada/fredapi) (1,183 stars) |
| `pyfredapi` covers all FRED endpoints with optional plotting | [pyfredapi docs](https://pyfredapi.readthedocs.io/en/latest/) |
| HMM regime detection uses 2–3 state Gaussian models on log returns + volatility | [PyQuantLab: Market Regime Detection using HMMs](https://www.pyquantlab.com/articles/Market%20Regime%20Detection%20using%20Hidden%20Markov%20Models.html); [RegimeForecast: HMM practical guide](https://regimeforecast.com/blog/hidden-markov-models-market-regimes-python) |
| Hurst exponent: H > 0.5 = trending, H < 0.5 = mean-reverting, H ≈ 0.5 = random walk | [GitHub: Hurst-Exponent-Trading-Strategy](https://github.com/Sidhus234/Hurst-Exponent-Trading-Strategy) |
| `hmmlearn` library provides Gaussian HMM with Baum-Welch EM algorithm | hmmlearn docs (standard scikit-learn adjacent library) |
| `ib_insync` provides asyncio-native IBKR integration with Level 1 ticks, Level 2 DOM, option Greeks | [ib_insync docs](https://ib-insync.readthedocs.io/readme.html); [GitHub: erdewit/ib_insync](https://github.com/erdewit/ib_insync/) |
| ib_insync requires Python 3.6+, TWS/Gateway v1023+, no ibapi needed | [ib_insync README](https://ib-insync.readthedocs.io/readme.html) |
| Behavioral feature engineering (momentum chasing, panic selling patterns) outperforms linear models for short-term trading | [Springer: Trading Signal Survival Analysis](https://link.springer.com/article/10.1007/s10614-024-10567-8) |
| Hybrid AI (TA + sentiment + XGBoost) achieved 135.49% returns over 24 months | [arXiv: 2601.19504](https://arxiv.org/pdf/2601.19504) |
| Unusual Whales client exists at `shared/unusual_whales/client.py` with full OptionsFlow, GexData, MarketTide models | Codebase: verified via direct file read |
| IBKR adapter stub at `services/connector-manager/src/brokers/ibkr.py` returns mock data | Codebase: verified via direct file read |
| `ta_check.py` has exactly 4 indicators (RSI, MACD, BB, S/R) | Codebase: `agents/templates/position-monitor-agent/tools/ta_check.py`, lines 43–102 |
| `receive_sell_signal()` is never called from agent_gateway.py | Codebase: grep for "sell_signal\|route.*sell" in agent_gateway.py returned 0 matches |
| `analyst_patterns` is always passed as `{}` | Codebase: `position_micro_agent.py` line 56; grep confirms no non-empty assignment |
| FOMC/CPI/NFP are hard-coded date lists through 2026 | Codebase: `enrich.py` lines 693–736 |

---

## 10. Non-Functional Requirements

### Performance

| Constraint | Requirement |
|-----------|-------------|
| Enrichment pipeline (backtest) | Adding 60+ features must not increase per-trade enrichment time by more than 3× (current: ~2s/trade) |
| Live enrichment (`enrich_single.py`) | Must complete within 15 seconds for a single trade (current: ~5s) |
| Position monitor TA check | Must complete within 10 seconds (current: ~3s with 4 indicators) |
| FRED API calls | Cached with 1-hour TTL; max 2 API calls per enrichment run (batch fetch) |
| Unusual Whales calls in monitor | Max 1 call per ticker per 5 minutes (Redis-cached) |
| IBKR data latency | < 500ms for quotes when TWS connected; no impact when disconnected |

### Reliability

- All new data sources must have graceful fallbacks: FRED → disk cache → hardcoded defaults; IBKR → yfinance; Unusual Whales → skip (zero urgency contribution).
- Analyst profile computation must handle analysts with < 10 trades (return neutral/zero features, not errors).
- New features must not produce NaN in the final feature vector (fill with 0.0 or median).

### Testability

- Each new feature sub-category has a dedicated unit test module.
- Integration tests verify FRED API connectivity (with mock for CI).
- Integration test verifies sell signal routing end-to-end.
- Analyst profile computation testable on synthetic trade data.

### Maintainability

- Shared TA computation extracted to `shared/ta/indicators.py` — single source of truth for both `ta_check.py` and `enrich_single.py`.
- FRED event calendar abstracted behind `shared/data/fred_calendar.py` — replaceable data source.
- Analyst profile schema versioned via Alembic migration.

---

## 11. Dependencies & Risks

### New Python Dependencies

| Package | Version | Purpose | Risk |
|---------|---------|---------|------|
| `fredapi` | latest | FRED API client | Low — mature, 1,183 GitHub stars, maintained |
| `hmmlearn` | latest | HMM regime detection | Medium — requires numpy/scipy; optional (fallback to rolling Sharpe) |
| `ib_insync` | 0.9.86+ | IBKR TWS integration | Medium — requires running TWS/Gateway; optional for non-IBKR setups |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| FRED API rate limiting (120 req/min) | Low | Medium | Batch fetch + 1-hour disk cache. Backtest fetches once; live caches aggressively. |
| HMM fitting instability on short histories | Medium | Low | Fallback to rolling Sharpe sign method if hmmlearn fails or returns degenerate states. |
| IBKR TWS not always running | High | Medium | IBKR is additive. All position monitors fall back to yfinance when IBKR unavailable. |
| Unusual Whales API cost scaling | Medium | Medium | Cache per ticker per 5 minutes. Estimate: ~300 calls/day for 10 active positions. |
| Analyst profile cold start (new analysts) | High | Low | Return neutral features (0 / median) for analysts with < 10 trades. Flag in logs. |
| Feature explosion slowing preprocess.py | Low | Low | New features are simple numerics. preprocess.py auto-includes them; no code change needed. |
| Backtest ↔ live parity drift | Medium | High | CI test: diff feature columns from backtest output vs `enrich_single.py` output. Fail build if mismatch. |

---

## 12. Phasing Recommendation

### Phase 1: Foundation (Estimated: 1 week)

**Goal:** Fix the broken plumbing and build the analyst behavior model.

| Deliverable | Files Touched |
|-------------|---------------|
| Sell signal routing fix | `agent_gateway.py` (~20 lines) |
| Analyst profile computation tool | New: `agents/backtesting/tools/compute_analyst_profile.py` |
| Analyst profile DB table | New Alembic migration: `040_analyst_profiles.py` |
| Analyst profile injection into position monitors | `agent_gateway.py`, `position_micro_agent.py` |
| Analyst behavior features in enrichment | `enrich.py`, `enrich_single.py` (~15 features) |
| Unit tests | New: `tests/unit/test_analyst_profile.py`, `tests/unit/test_sell_signal_routing.py` |

**Why first:** The sell signal routing is a P0 bug. The analyst model is a prerequisite for Phase 4 (exit prediction) and feeds into Phase 2 (analyst features in enrichment).

### Phase 2: Advanced Feature Engineering (Estimated: 1.5 weeks)

**Goal:** Add time series dynamics and FRED economic event features.

| Deliverable | Files Touched |
|-------------|---------------|
| Time series dynamics features (~20) | `enrich.py`, `enrich_single.py` |
| FRED API integration + dynamic event calendar | New: `shared/data/fred_calendar.py` |
| Economic event reaction features (~25) | `enrich.py`, `enrich_single.py` |
| Remove hard-coded date lists | `enrich.py` (delete lines 693–736, replace with FRED calls) |
| Disk cache for FRED data | `shared/data/fred_calendar.py` |
| Unit tests | New: `tests/unit/test_time_series_features.py`, `tests/unit/test_fred_calendar.py` |

**Why second:** These features improve ML model accuracy for both entry and exit. No dependency on position monitor changes.

### Phase 3: Rich Position Monitor (Estimated: 1.5 weeks)

**Goal:** Upgrade TA coverage and wire in additional data sources.

| Deliverable | Files Touched |
|-------------|---------------|
| Shared TA indicators module | New: `shared/ta/indicators.py` |
| Expand `ta_check.py` to 15+ indicators | `ta_check.py` (rewrite) |
| Wire Unusual Whales flow into exit decisions | `exit_decision.py` |
| Wire FRED macro signals into exit decisions | `exit_decision.py` |
| Cross-asset correlation monitor | `exit_decision.py` |
| Time-series exit awareness (overstay, TOD, DOW) | `exit_decision.py`, `position_micro_agent.py` |
| Unit tests | New: `tests/unit/test_ta_indicators.py`, `tests/unit/test_exit_data_sources.py` |

**Why third:** Depends on FRED integration from Phase 2. Unusual Whales client already exists — just needs wiring.

### Phase 4: Analyst Exit Prediction (Estimated: 1 week)

**Goal:** Use the analyst behavior model (Phase 1) to predict exit timing.

| Deliverable | Files Touched |
|-------------|---------------|
| `analyst_exit_probability()` function | New in `position_micro_agent.py` or `exit_decision.py` |
| Integration into urgency calculation | `exit_decision.py` |
| Incremental profile updates on position close | `position_micro_agent.py` |
| Backtest validation of prediction accuracy | New: `agents/backtesting/tools/validate_exit_prediction.py` |
| Unit + integration tests | New: `tests/unit/test_exit_prediction.py` |

**Why fourth:** Requires the analyst profile (Phase 1) to be populated and tested in production.

### Phase 5: IBKR Real-Time Data (Estimated: 1.5 weeks)

**Goal:** Replace yfinance polling with IBKR real-time data where available.

| Deliverable | Files Touched |
|-------------|---------------|
| Implement IBKR adapter with `ib_insync` | `services/connector-manager/src/brokers/ibkr.py` (rewrite) |
| Add Level 2 order book methods to broker protocol | `shared/broker/adapter.py` |
| IBKR quote provider for position monitors | New: `shared/data/ibkr_provider.py` |
| Fallback chain: IBKR → yfinance | `exit_decision.py`, `ta_check.py` |
| Bid-ask spread analysis in exit urgency | `exit_decision.py` |
| Integration tests (requires TWS stub) | New: `tests/integration/test_ibkr_adapter.py` |

**Why last:** IBKR integration requires a running TWS/Gateway instance and is additive — every prior phase works without it. This is the highest-risk, highest-reward phase.

### Total Estimated Duration: ~6.5 weeks (sequential)

Phases 1 + 2 can partially overlap (different file sets). Phases 3 + 4 are sequential (4 depends on 1 and 3). Phase 5 is independent and can be parallelized with Phase 4.

**Realistic critical path:** Phases 1 → 2 → 3 → 4 = ~5 weeks. Phase 5 in parallel with 4 = no additional time.

---

## 13. Appendix: File Impact Map

| File | Phase | Change Type |
|------|-------|-------------|
| `agents/backtesting/tools/enrich.py` | 1, 2 | Modify: add analyst, time series, FRED features; remove hardcoded dates |
| `agents/templates/live-trader-v1/tools/enrich_single.py` | 1, 2 | Modify: mirror all new features for live parity |
| `apps/api/src/services/agent_gateway.py` | 1 | Modify: add sell signal routing (~20 lines) |
| `apps/api/src/services/position_micro_agent.py` | 1, 3, 4 | Modify: populate analyst_patterns, add exit prediction |
| `agents/templates/position-monitor-agent/tools/ta_check.py` | 3 | Rewrite: 4 → 15+ indicators |
| `agents/templates/position-monitor-agent/tools/exit_decision.py` | 3, 4 | Modify: add UW, FRED, correlation, prediction signals |
| `shared/broker/adapter.py` | 5 | Modify: add Level 2 methods |
| `services/connector-manager/src/brokers/ibkr.py` | 5 | Rewrite: stub → full ib_insync implementation |
| `shared/unusual_whales/client.py` | 3 | No change (already complete) |
| **New: `shared/ta/indicators.py`** | 3 | Create: shared TA computation library |
| **New: `shared/data/fred_calendar.py`** | 2 | Create: FRED API wrapper + disk cache |
| **New: `shared/data/ibkr_provider.py`** | 5 | Create: IBKR real-time data provider |
| **New: `agents/backtesting/tools/compute_analyst_profile.py`** | 1 | Create: analyst profile builder |
| **New: Alembic migration `040_analyst_profiles.py`** | 1 | Create: analyst_profiles table |
| **New: `agents/backtesting/tools/validate_exit_prediction.py`** | 4 | Create: backtest exit prediction accuracy |

---

*This PRD was produced by Nova (PM Agent) based on codebase reconnaissance, external API research, and user interview answers. Architecture and system design decisions are deferred to Atlas.*
