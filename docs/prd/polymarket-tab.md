# PRD: Polymarket Tab — Phoenix Trade Bot

Owner: Nova (PM)
Status: Draft v0.1
Date: 2026-04-07
Next handoff: Atlas (architecture)

---

## 1. Problem Statement & Goals

### Problem
Phoenix is a best-in-class equities/options/derivatives bot, but prediction markets (Polymarket, Kalshi) have matured into a multi-billion-dollar venue class with persistent inefficiencies: thin books, slow oracles, narrative-driven mispricings, sum-to-one violations, and cross-venue arbitrage. Existing OSS Polymarket bots are single-strategy, single-venue, and lack institutional-grade risk, calibration, and paper-trading infrastructure. The user — a power trader new to prediction markets — wants Phoenix to become the *unified* PM trading surface that beats every OSS bot by reusing Phoenix's existing risk chain, OpenClaw orchestrator, ML pipeline, and briefing infrastructure rather than rebuilding them.

### Goals
1. Ship a Polymarket tab that exposes discovery, strategies, positions, calibration, and per-strategy paper/live controls.
2. Reuse Phoenix infrastructure end-to-end: no parallel risk system, no parallel orchestrator, no parallel backtester.
3. Default-paper-everywhere with an explicit, audited promotion gate per strategy.
4. Deliver 7 strategy archetypes (sum-to-one arb, cross-venue arb, market making, ML fair-value, news reactor, combinatorial arb, whale-copy) gated behind a calibration-and-resolution-risk layer.
5. Be venue-agnostic in design (Polymarket first, Kalshi second, Opinion later) so the discovery scanner and arb engines compose.

### Non-goals (v1)
- Other crypto trading (spot, perps, DeFi yield) — only PM, which happens to settle on Polygon.
- Mobile UI.
- Multi-tenant customer access (single power-user only in v1).
- Auto-tuning hyperparameters of the ML ensemble (manual training cycles).
- Building a proprietary oracle.

---

## 2. Target User & Success Metrics

### Target user
Single power trader operating Phoenix in single-tenant mode. Deeply familiar with options/equities risk concepts (Kelly, Brier, slippage, adverse selection) but new to prediction-market mechanics (UMA OO, CLOB signing, sum-to-one, taker fees, resolution wording risk). Needs the system to teach by surfacing the right metrics, not by hiding complexity.

### Success metrics (to be validated with user before v1.0 lock)
| Category | Metric | Target |
|---|---|---|
| Adoption | Days/week user opens Polymarket tab | >=5 |
| Safety | Live-mode strategies that bypassed paper gate | 0 (hard) |
| Calibration | Brier score on resolved markets traded | <= 0.18 |
| Reliability | Stale-WS reconnect MTTR | < 5s |
| Paper PnL | Sharpe (paper) over 60 trading days before any live promotion | >= 1.5 |
| Live PnL (post-promotion) | Net of fees + slippage, monthly | > 0 |
| Resolution risk | Trades flagged "ambiguous" by F9 that later disputed | <= 5% |
| Discovery | Markets scanned/min across venues | >= 500 |

Open: user must confirm Sharpe target, Brier target, and the 60-day paper-soak duration.

---

## 3. Phased Roadmap

### v1.0 — Foundation + Safe Edge (must-haves)
**Features:** F1, F2, F3, F9, F10, F12, F13

**Why this grouping:**
- F1 (broker adapter) and F13 (per-strategy OpenClaw agent + global kill switch) are the *substrate* — nothing else can ship without them.
- F2 (discovery) is the data layer every strategy reads from.
- F3 (sum-to-one + cross-venue arb) is the **lowest-risk first edge**: it is market-neutral, requires no fair-value model, no inventory, no news interpretation, and is the cleanest paper→live test.
- F9 (resolution-risk scorer) is non-negotiable for v1: any strategy that trades a wording-ambiguous or oracle-disputable market without F9 is reckless. F9 gates *every* strategy, so it must ship with the first one.
- F10 (walk-forward backtester for PM) is required to justify the promotion gate — no paper→live without backtest evidence.
- F12 (PM morning briefing) is the user's daily on-ramp; without it the tab is a dead screen each morning.

**Exit criteria for v1.0:**
- F3 runs in paper for >=30 days with >0 trades/day and Brier <= 0.20.
- Global kill switch verified to halt PM strategies in <2s in a chaos test.
- Promotion gate audit log shows zero bypasses.

### v1.1 — Intelligence Layer
**Features:** F5 (ML ensemble fair-value), F11 (calibration dashboard + adaptive Kelly)

Rationale: Once arb is paying for the platform, layer the *directional* edge. F5 produces fair values; F11 makes Kelly sizing trust-aware via Brier/reliability. They ship together because adaptive Kelly without calibration data is dangerous, and fair-value without sizing is academic.

### v1.2 — Liquidity & Information Edges
**Features:** F4 (maker-rebate market making), F6 (news reactor), F8 (whale copy)

Rationale: All three need v1.1's calibration data to size safely. MM needs fair-value (F5) to quote around. News reactor needs F9 (already shipped) to filter ambiguous markets. Whale copy needs Polygon ingestion infra that piggybacks on the F1 connector.

### v1.3 — Combinatorial Edge
**Features:** F7 (logical/combinatorial arb)

Rationale: Highest engineering complexity (constraint solver across linked markets), lowest urgency, and depends on a mature discovery scanner (F2 hardened by v1.0–v1.2 usage).

---

## 4. User Stories & Acceptance Criteria

Stories use: priority (P0/P1/P2), Given/When/Then. Each strategy story implicitly inherits: "must run in paper mode by default" and "must respect global kill switch."

### F1 — Polymarket broker adapter + CLOB connector (P0, v1.0)

**S1.1** As a trader, I want Phoenix to authenticate to Polymarket CLOB, so that I can place and cancel orders.
- Given valid CLOB API credentials stored encrypted, When the adapter initializes, Then it must complete a signed `GET /auth` round-trip and expose `health: ok`.
- AC: failure surfaces in the Connectors page with a clear error code; no plaintext keys in logs.

**S1.2** As a trader, I want a live order book and trade stream, so that strategies see fresh prices.
- Given the RTDS websocket is connected, When a book update arrives, Then it must be normalized into Phoenix's internal book schema and published on the event bus within 50ms p95.
- AC: WS gap detection triggers automatic resync against Gamma REST snapshot.

**S1.3** As a trader, I want a Gamma-API-backed market metadata cache, so that discovery and resolution scoring have one source of truth.
- AC: cache TTL configurable; staleness surfaced per market.

Dependencies: existing broker adapter pattern in `shared/broker/adapter.py`, `shared/broker/factory.py`, `shared/broker/circuit_breaker.py`; connector-manager `services/connector-manager/src/base.py`, `factory.py`.

### F2 — Unified market-discovery scanner (P0, v1.0)

**S2.1** As a trader, I want one scanner that pulls Polymarket and Kalshi markets, so that arb and discovery are venue-agnostic.
- Given both venues are reachable, When the scanner runs on its interval, Then it must produce a unified `MarketRow{venue, id, question, yes_bid, yes_ask, volume, expiry, resolution_source}`.
- AC: >= 500 markets/min throughput; per-venue failure isolated (one venue down does not blank the other).

**S2.2** As a trader, I want filters in the Polymarket tab (category, expiry, volume, spread, edge), so that I can find tradeable markets fast.
- AC: filters persist per user; URL-shareable.

Open question (see section 7): Kalshi API access tier, rate limits, and US-jurisdiction status as of April 2026.

### F3 — Sum-to-one + cross-venue arb agent (P0, v1.0)

**S3.1** As a trader, I want an agent that detects sum-to-one violations within a single Polymarket multi-outcome market, so that I can lock risk-free edge.
- Given a market with outcomes whose best asks sum to <1 (after fees), When detected, Then the agent must size and place all legs atomically in paper mode.
- AC: leg-failure rollback; partial-fill handling; min-edge threshold configurable.

**S3.2** As a trader, I want PM↔Kalshi cross-venue arb when the same event lists on both venues.
- AC: event-matching uses F9 wording similarity + manual user override list; no auto-trade on a match below user-set similarity score.

**S3.3** As a trader, I want every arb attempt logged with edge, fees, slippage, and realized PnL.

### F4 — Maker-rebate market-making agent (P1, v1.2)

**S4.1** As a trader, I want an MM agent that quotes both sides around an F5 fair value with inventory skew, so that I capture rebates and spread.
- AC: max inventory cap per market; auto-flatten on cap breach; adverse-selection guard pauses quoting on N consecutive losing fills.

**S4.2** As a trader, I want inventory hedging via opposite-side legs in linked markets when available.

### F5 — ML ensemble fair-value model (P1, v1.1)

**S5.1** As a trader, I want the existing 8-model ensemble retrained on PM features (price history, volume, narrative sentiment, time-to-resolution, on-chain flow), so that strategies have a fair-value signal.
- AC: training pipeline reuses `agents/backtesting/` 9-step pipeline; outputs Brier and log-loss on holdout; refuses to publish a model with Brier > 0.22.

**S5.2** As a trader, I want fair values published per market on the event bus with confidence intervals.

Dependencies: `agents/backtesting/`, `shared/backtest/engine.py`.

### F6 — News-driven event reactor (P1, v1.2)

**S6.1** As a trader, I want the LLM gateway to score breaking news for impact on currently-held or watched PM markets.
- Given a news item from `services/connector-manager/src/flash_news.py`, Twitter, Reddit, or Discord, When the LLM scores impact > threshold, Then the reactor must propose a trade (paper) within 5s.
- AC: every reaction logged with the source URL, LLM rationale, and the F9 ambiguity score that gated it.

**S6.2** As a trader, I want a kill on the news reactor independent of the global kill switch (per-strategy pause).

Dependencies: `shared/llm/client.py`, `services/connector-manager/src/flash_news.py`, existing Twitter/Reddit/Discord ingestion.

### F7 — Combinatorial / logical arb engine (P2, v1.3)

**S7.1** As a trader, I want a solver that detects logical impossibilities across linked markets (e.g., P(A) + P(A∩B) inconsistencies, conditional vs marginal mismatches).
- AC: solver runs on the unified market graph from F2; flags candidates with proof tree; requires user one-click approval before paper-trading in v1.3 (no full auto).

### F8 — Whale / smart-money copy tracker (P1, v1.2)

**S8.1** As a trader, I want a Polygon on-chain watcher that flags wallets with sustained PnL on Polymarket and surfaces their new positions.
- AC: wallet leaderboard with rolling Brier and PnL; opt-in copy at user-set fraction; copy trades inherit F9 gating.

### F9 — Resolution-risk scorer (P0, v1.0)

**S9.1** As a trader, I want every PM market scored for resolution risk before any strategy can act on it, so that I avoid UMA-disputable or wording-ambiguous markets.
- Given a market, When the scorer runs, Then it must produce: oracle type, dispute history, LLM ambiguity score (0–1), and a final `tradeable: bool`.
- AC: any strategy that places an order on a market with `tradeable=false` is blocked at the risk chain; block is auditable.

**S9.2** As a trader, I want a UI badge on each market showing the F9 score and rationale.

### F10 — Walk-forward backtester for PM (P0, v1.0)

**S10.1** As a trader, I want to backtest any PM strategy with walk-forward windows, so that promotion-gate evidence is statistically honest.
- AC: reuses `services/backtest-runner/src/walk_forward.py` and `engine.py`; outputs Brier, Sharpe, max drawdown, fee-adjusted PnL, calibration plot.

**S10.2** As a trader, I want backtest artifacts attached to a strategy as the prerequisite for paper→live promotion.

Dependencies: `services/backtest-runner/src/walk_forward.py`, `simulation.py`, `metrics.py`, `pipeline.py`.

### F11 — Calibration dashboard + adaptive Kelly (P1, v1.1)

**S11.1** As a trader, I want a calibration view (Brier, reliability curve, log loss) per strategy and per market category.
- AC: updates daily; downloadable.

**S11.2** As a trader, I want Kelly sizing that scales down when Brier degrades and scales up when calibration improves, with a hard cap.
- AC: cap configurable; default cap = quarter-Kelly; size=0 when Brier > user threshold.

### F12 — Polymarket morning briefing (P0, v1.0)

**S12.1** As a trader, I want a daily PM section in the morning briefing covering: top 10 movers, new high-volume markets, resolutions in next 24h, F9-flagged risks, current paper/live PnL, kill-switch status.
- AC: extends `agents/templates/morning-briefing-agent/` and `apps/api/src/routes/morning_routine.py`; renders in `apps/dashboard/src/pages/MorningBriefing.tsx`.

### F13 — Per-strategy OpenClaw agent + global kill switch wiring (P0, v1.0)

**S13.1** As a trader, I want each PM strategy to be its own OpenClaw agent with its own state machine and risk envelope.
- AC: state transitions reuse `services/orchestrator/src/state_machine.py`; each agent has independent `mode`, `max_notional`, `max_loss_day`, `max_inventory`.

**S13.2** As a trader, I want the global kill switch to halt every PM strategy in <2s and require explicit re-arm.
- AC: integrates with `services/global-monitor/src/kill_switch.py`; chaos test in CI.

**S13.3** As a trader, I want per-strategy pause/resume from the Polymarket tab without touching the global switch.

---

## 5. Paper → Live Promotion Gate

A first-class, hard-enforced workflow. No strategy ever starts live; promotion is per-strategy, audited, and reversible.

### UI
- Each strategy card on the Polymarket tab shows a `mode` chip: `PAPER` (green) or `LIVE` (amber).
- A `Promote to live` button is disabled until **all** of the following are true:
  1. A walk-forward backtest (F10) is attached, dated within the last 30 days, with Brier <= user-set threshold and Sharpe >= user-set threshold.
  2. Paper-mode runtime >= configured soak period (default 30 days for v1.0, user-configurable).
  3. Resolution-risk coverage: F9 has scored 100% of markets the strategy traded in paper.
  4. Calibration check (F11) passes once F11 ships; until then, paper Brier is the gate.
- Clicking `Promote to live` opens a modal requiring: (a) typed confirmation of strategy name, (b) max notional for first 7 days, (c) explicit acknowledgement of resolution risk.

### API
- `POST /api/polymarket/strategies/{id}/promote` — body includes the four gate proofs and the user's typed confirmation. Server re-validates every gate before persisting `mode=live`.
- `POST /api/polymarket/strategies/{id}/demote` — single-click; no gate.
- `GET /api/polymarket/strategies/{id}/promotion_audit` — full history.

### Audit trail
- Every promotion, demotion, and *attempted* promotion (pass or fail) writes a row to `audit_log` (reuse `shared/db/models/audit_log.py`) with: actor, timestamp, gate evaluations, attached backtest id, soak duration, resulting mode.
- Rows are immutable; surfaced in the Risk & Compliance page (`apps/dashboard/src/pages/RiskCompliance.tsx`).

### Per-strategy granularity
- `mode` lives on the strategy row, not on the tab or the user. Reuse `shared/db/models/strategy.py` with a new `mode` column (PAPER default, NOT NULL, DB-level CHECK).
- The execution risk chain (`services/execution/src/risk_chain.py`) reads `mode` and routes paper orders to a sim-fill path; live orders flow to the F1 adapter. A live order from a `mode=paper` strategy must be rejected at the chain with a hard error and an audit row.

---

## 6. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | UMA Optimistic Oracle disputes / wrong resolution | Med | High | F9 scorer; block trading on markets with prior disputes; per-market max notional cap when ambiguity score > 0.3 |
| R2 | Dynamic taker fees eat MM/arb edge | High | Med | Fee-aware sizing in F3/F4; refresh fee schedule from Gamma each cycle; min-edge threshold includes worst-case fee |
| R3 | CLOB signing key custody | Med | Critical | Reuse `shared/crypto/credentials.py` (Fernet) for at-rest encryption; key never logged; signing isolated in adapter; user-only access. Open question on hardware-key option. |
| R4 | Regulatory: CFTC stance on PM US access, Kalshi event-contract restrictions | High | High | Open question (section 7). v1.0 ships behind a region-aware feature flag. User confirms jurisdiction before live promotion. |
| R5 | Thin-book slippage | High | Med | Per-market depth check before order; max-notional auto-derived from L2 depth; cancel-and-reprice on partial fills |
| R6 | Stale-book WS gaps | Med | High | Heartbeat + sequence-number gap detection; force REST resync; pause strategies on stale > 2s |
| R7 | Adverse selection on MM (F4) | High | High | N-consecutive-loss kill; widen on toxic flow; inventory caps; F5 fair-value confidence gate |
| R8 | Model miscalibration drift | Med | High | Daily Brier check (F11); auto-demote-to-paper if Brier crosses threshold; retrain trigger |
| R9 | LLM hallucination in F6 / F9 | Med | Med | F9 score requires structured output; F6 always goes through F9 + risk chain; both log full prompt+response |
| R10 | Cross-venue event-matching false positive (F3 PM↔Kalshi) | Med | High | Similarity threshold; manual override list; F9 must agree on both legs |
| R11 | Polygon RPC downtime (F1, F8) | Med | Med | Multi-RPC failover; circuit breaker reuse `shared/broker/circuit_breaker.py` |
| R12 | Whale-copy lag → buying tops | Med | Med | F11 calibration on copy trades; only copy wallets with rolling Brier < threshold |

---

## 7. Open Questions (need user input or research)

1. **US legality of Polymarket as of April 2026.** Has the CFTC consent order or any settlement changed US-resident access? User must confirm jurisdiction. Until confirmed, live mode is geo-fenced off.
2. **Kalshi API access tier and rate limits.** Need user to provide credentials and confirm account tier; rate limits will shape F2 throughput.
3. **CFTC event-contract rules** affecting which Kalshi categories we can trade and which arb pairs are legal.
4. **Opinion (or competing PM venue) API maturity** — does it have a public CLOB and websocket today? If not, F2 ships PM+Kalshi only and Opinion is deferred.
5. **CLOB signing key storage approach.** Acceptable: (a) Fernet-encrypted in Postgres reusing `shared/crypto/credentials.py`, (b) OS keychain, (c) hardware key (YubiKey/Ledger). User to choose.
6. **Soak period for paper→live promotion.** Default proposed: 30 days. User to confirm.
7. **Brier and Sharpe gate thresholds** for promotion. Defaults proposed: Brier <= 0.18, Sharpe >= 1.5. User to confirm.
8. **Initial bankroll and per-strategy max notional caps** for the first live week.
9. **Should F7 (combinatorial arb) ever trade fully automatically, or stay one-click forever?** PM proposes one-click forever; user to confirm.
10. **Twitter/Reddit/Discord ingestion sources currently wired** — need user to confirm which channels feed F6.

---

## 8. Out of Scope (v1)

- Any non-PM crypto trading (spot, perps, DeFi yield, NFT). PM settles on Polygon; that is the only crypto surface allowed.
- Mobile UI / mobile push.
- Multi-tenant customer access — Phoenix supports multi-tenant but the PM tab is single-power-user in v1.
- Auto-hyperparameter tuning of the F5 ensemble.
- Building a custom oracle or dispute service.
- Tax-lot reporting for PM positions (defer to v1.x).
- Social copy-export (publishing the user's positions).

---

## 9. Dependencies on Existing Phoenix Subsystems

| Subsystem | Path | Used by |
|---|---|---|
| Broker adapter pattern | `shared/broker/adapter.py`, `shared/broker/factory.py`, `shared/broker/alpaca_adapter.py` (reference impl), `shared/broker/circuit_breaker.py` | F1 |
| Connector framework | `services/connector-manager/src/base.py`, `factory.py`, `router.py`, `main.py` | F1, F2 |
| Flash news ingestion | `services/connector-manager/src/flash_news.py` | F6 |
| Risk chain (3-layer) | `services/execution/src/risk_chain.py` | F3, F4, F6, F7, F8, F13, promotion gate |
| Global monitor / kill switch | `services/global-monitor/src/kill_switch.py`, `circuit_breaker.py`, `main.py` | F13 |
| Orchestrator + state machine | `services/orchestrator/src/state_machine.py`, `main.py`, `rl_engine.py` | F13 (per-strategy agent lifecycle) |
| Backtest runner + walk-forward | `services/backtest-runner/src/walk_forward.py`, `engine.py`, `simulation.py`, `metrics.py`, `pipeline.py`, `data_loader.py` | F10, promotion gate |
| ML pipeline (8-model ensemble) | `agents/backtesting/` (9-step pipeline), `shared/backtest/engine.py` | F5 |
| LLM gateway | `shared/llm/client.py`, `services/llm-gateway` | F6, F9, F12 |
| Morning briefing | `agents/templates/morning-briefing-agent/` (`config.json`, `tools/compile_briefing.py`, `tools/wake_children.py`, `tools/report_briefing.py`), `apps/api/src/routes/morning_routine.py`, `apps/api/src/routes/briefing_history.py`, `apps/dashboard/src/pages/MorningBriefing.tsx` | F12 |
| Event bus | `shared/events/bus.py`, `producers.py`, `consumers.py`, `envelope.py` | F1 (book stream), F2, F5, F6 |
| Strategy model | `shared/db/models/strategy.py` (add `mode` column) | Promotion gate, F13 |
| Audit log | `shared/db/models/audit_log.py` | Promotion gate |
| Credentials encryption | `shared/crypto/credentials.py` (Fernet) | F1 (CLOB key custody) |
| Dashboard page pattern | `apps/dashboard/src/pages/Strategies.tsx`, `Connectors.tsx`, `Positions.tsx`, `Backtests.tsx`, `RiskCompliance.tsx`, `App.tsx`, `components/layout/AppShell.tsx` | New `Polymarket.tsx` page + tab registration |
| Feature flags | `shared/feature_flags.py` | Region gating, per-feature rollout |
| Rate limiter | `shared/rate_limiter.py` | F2 venue scanners |
| WS gateway | `services/ws-gateway` | Live book/positions push to UI |

---

## 10. Architecture Handoff (for Atlas)

This PRD intentionally specifies **what** and **why**, not **how**. Atlas will own:
- Module/service decomposition (single PM service vs split adapter/strategy services).
- Schema additions to `shared/db/models/strategy.py` (`mode`, gate metadata).
- Event-bus topic naming and ordering guarantees.
- Where the F9 gate physically lives in the risk chain.
- F7 solver technology choice.
- Key-storage implementation per user's answer to Open Question 5.

---

## 11. Research & Sources

This draft is grounded in codebase recon only; external citations (Polymarket CLOB docs, Gamma API, RTDS WS, Kalshi API, CFTC orders, UMA OO docs, py-clob-client) will be added in v0.2 after the open questions in section 7 are answered, so that the cited APIs and rules match the user's confirmed jurisdiction and venue access as of April 2026.
