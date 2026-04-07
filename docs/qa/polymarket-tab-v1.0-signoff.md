# Polymarket Tab v1.0 — QA Sign-off

QA by: Quill
Date: 2026-04-07
PRD: `docs/prd/polymarket-tab.md`
Architecture: `docs/architecture/polymarket-tab.md`

---

## 1. Test execution summary

| Suite | Command | Collected | Passed | Failed |
|---|---|---|---|---|
| Unit (polymarket) + integration + chaos | `pytest tests/unit/polymarket/ tests/chaos/ tests/integration/polymarket/` | 179 | 179 | 0 |
| API routes | `pytest apps/api/tests/test_polymarket_routes.py` | 36 | 36 | 0 |
| Benchmarks (PM) | `pytest tests/benchmark/test_pm_book_latency.py tests/benchmark/test_pm_scan_throughput.py` | 2 | 2 | 0 |
| **Total** | | **217** | **217** | **0** |

All existing tests pass clean (Devin's claim of 215 verified; actual count is 217 including the two benchmark specs).

## 2. Dashboard TypeScript compilation

Command: `cd apps/dashboard && npx tsc --noEmit`

- `apps/dashboard/src/pages/polymarket/index.tsx`: **clean, zero errors**.
- Pre-existing errors (out of scope — NOT introduced by this feature):
  - `src/pages/AgentDashboard.tsx:899,900,965` — ModelResult cast.
  - `src/pages/Backtests.tsx:10` — unused `BarChart3` import.
  - `src/pages/Connectors.tsx:732,773` — unused `total`, setState shape mismatch.
  - `src/pages/Login.tsx:5,57` — unused imports.
  - `src/pages/Tasks.tsx:569,586` — unused `@ts-expect-error`.
  - `src/types/index.ts:34` — missing `./instance` module.
- Flagged for Devin/Nova outside the PM scope. None block PM shipping.

## 3. Feature coverage matrix (v1.0 scope: F1, F2, F3, F9, F10, F12, F13)

| Feature | Story | AC summary | Implementation evidence | Verdict |
|---|---|---|---|---|
| **F1** Broker adapter + CLOB connector | S1.1 signed auth, no plaintext keys | `services/connector-manager/src/brokers/polymarket/{signing,clob_client,adapter}.py`; `tests/unit/polymarket/test_broker.py` 23 tests pass | PASS |
| F1 | S1.2 RTDS WS normalized <50ms p95, gap -> Gamma resync | `rtds_ws.py`, `sequence_gap.py`; `test_sequence_gap.py` 12 tests; benchmark `test_pm_book_latency.py` passes | PASS |
| F1 | S1.3 Gamma metadata cache w/ TTL + staleness | `gamma_client.py` | PASS |
| **F2** Unified discovery scanner | S2.1 unified `MarketRow{venue,id,question,bids,volume,expiry,resolution_source}`; >=500/min; per-venue isolation | `shared/polymarket/events.py`; scanner tests 22 pass; `test_pm_scan_throughput.py` passes | PASS |
| F2 | S2.2 filters persist + URL-shareable | Category / min_volume / tradeable filters present in Markets tab; **URL persistence NOT implemented** | **PARTIAL — BUG-2** |
| **F3** Sum-to-one + cross-venue arb | S3.1 detect sum<1, size, place atomically, rollback partial fills, min-edge configurable | `agents/polymarket/sum_to_one_arb/{detector,sizing,agent}.py`; 22 detector+agent tests pass; rollback path asserted at `agent.py:191-214` | PASS |
| F3 | S3.2 PM<->Kalshi cross-venue arb w/ similarity + manual override | `agents/polymarket/cross_venue_arb/detector.py`; 9 tests pass | PASS |
| F3 | S3.3 log edge/fees/slippage/PnL | Agent emits reason codes + submission records | PASS |
| **F9** Resolution-risk scorer | S9.1 oracle/dispute/ambiguity/tradeable; gate at risk chain | `shared/polymarket/resolution_risk.py`; `services/execution/src/risk_chain.py:105-157` blocks on `f9_tradeable=False`; 14 tests pass | PASS |
| F9 | S9.2 UI badge + rationale | `ResolutionRiskBadge` in polymarket/index.tsx around L199 | PASS |
| **F10** Walk-forward PM backtester | S10.1 reuses walk_forward + engine; outputs Brier/Sharpe/DD/calibration | `services/backtest-runner/src/loaders/polymarket_loader.py`; `test_pm_backtest_loader.py` 14 tests pass | PASS |
| F10 | S10.2 backtest artifacts gate promotion | Backtest capability exists but **promotion gate does not check backtest attachment or recency** | **FAIL — BUG-1** |
| **F12** PM morning briefing | S12.1 top movers, new high-volume, 24h resolutions, F9 risks, PnL, kill status | `agents/templates/morning-briefing-agent/tools/compile_pm_section.py`; API `GET /api/polymarket/briefing/section`; BriefingTab in UI | PASS |
| **F13** Per-strategy OpenClaw agent + global kill | S13.1 per-strategy state machine + envelope | Strategy model + PM routes for pause/resume/promote/demote; `test_pm_risk.py` 19 tests | PASS |
| F13 | S13.2 global kill halts all PM in <2s, chaos in CI | `tests/chaos/test_pm_kill_switch.py::test_kill_switch_halts_sum_to_one_arb_under_2s` PASSES; propagation asserted <2s; rollback test of in-flight YES leg passes | PASS |
| F13 | S13.3 per-strategy pause/resume independent of global switch | `POST /api/polymarket/strategies/{id}/pause|resume`; tested in `test_polymarket_routes.py` | PASS |
| Promotion gate | 4 rules (backtest, soak, F9 coverage, Brier/Sharpe) | `shared/polymarket/promotion_gate.py` — 3 of 4 rules implemented (soak, brier, sharpe, f9_coverage); **backtest attachment rule missing** | **PARTIAL — BUG-1** |
| Promotion gate | Audit log on attempts incl. failures | `promotion_gate.py` writes audit rows; `test_promotion_gate.py` 14 tests pass | PASS |
| Promotion gate | Typed confirmation modal | Promote modal in polymarket/index.tsx ~L578; API re-validates | PASS |
| Jurisdiction gate | Region flag, attestation required before live | `shared/polymarket/jurisdiction.py`; `test_jurisdiction.py` 9 tests pass; `POST /jurisdiction/attest` | PASS |

### Out-of-scope features (NOT tested, by design)
F4 (v1.2), F5 (v1.1), F6 (v1.2), F7 (v1.3), F8 (v1.2), F11 (v1.1) — deferred per PRD section 3. No implementation expected.

## 4. Bugs filed

See `docs/qa/polymarket-tab-v1.0-bugs.md`.

| ID | Severity | Feature | Title |
|---|---|---|---|
| BUG-1 | P1 | Promotion gate / F10 S10.2 | Walk-forward backtest attachment + 30-day recency check not enforced |
| BUG-2 | P3 | F2 S2.2 | Markets-tab filters not URL-shareable |

## 5. Known risks (carry-forward from PRD section 6/7)

- **R4 / OQ1 US jurisdiction**: v1.0 must stay geo-fenced off until user confirms CFTC stance. Jurisdiction gate is wired (`jurisdiction.py` + attestation endpoint) — verify feature flag default is OFF in production `.env` before any live promotion.
- **Paper-only invariant**: Section 5 mandates default-paper. Confirmed in schema/gate logic and chaos tests, but production DB must enforce `mode` CHECK constraint. QA did not run a live DB so CHECK constraint presence is unverified in this session. Recommend a one-line migration review before ship.
- **R3 CLOB signing key custody**: OQ5 unresolved — user has not chosen Fernet-in-Postgres vs OS keychain vs hardware. Current impl uses `shared/crypto/credentials.py` Fernet; this is acceptable for v1.0 paper but must be re-confirmed before live.
- **Exit criteria not yet observable**: v1.0 requires F3 paper >=30 days + >0 trades/day + Brier<=0.20. That is a post-merge runtime gate, not a pre-merge QA gate.

## 6. Verdict

**CONDITIONAL**

Rationale:
- 217/217 tests pass; all 7 v1.0 features are substantively implemented; kill-switch chaos test passes well under 2s; F9 gating enforced at the risk chain; API + dashboard align.
- Blocker for unconditional sign-off is **BUG-1**: the promotion gate is explicitly specified (section 5, rule 1) to require a backtest attached and recent, and that rule is not enforced in `promotion_gate.py`. This is the gate's load-bearing contract — a strategy with good live-paper calibration but zero backtest evidence could be promoted today. Must-fix before any live promotion is possible in production.
- **BUG-2** (URL-shareable filters) is a minor AC miss, P3. Does not block v1.0 ship; can fast-follow.
- Pre-existing dashboard TS errors outside PM are not blockers for this feature but should be routed to Nova.

### Conditions to clear
1. Fix BUG-1: promotion_gate.py must load the latest PM walk-forward BacktestRun for the strategy and enforce existence + 30-day recency + Brier/Sharpe, with audit row on failure. Add unit test to `test_promotion_gate.py`.
2. Confirm `strategy.mode` DB CHECK constraint is present in the migration that ships with this feature.
3. Confirm `polymarket_enabled` / region feature flag defaults to OFF in production config.
4. (Optional / non-blocking) Fix BUG-2 URL-shareable filters.

Return this report to Build for routing to Nova and Devin.

---

## 7. Artifacts

- Bug list: `/Users/harishkumar/Projects/TradingBot/ProjectPhoneix/docs/qa/polymarket-tab-v1.0-bugs.md`
- Sign-off (this file): `/Users/harishkumar/Projects/TradingBot/ProjectPhoneix/docs/qa/polymarket-tab-v1.0-signoff.md`
