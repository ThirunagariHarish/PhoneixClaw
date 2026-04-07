# Polymarket Tab v1.0 — Release Notes

**Release**: Phoenix Trade Bot `0.2.0`
**Date**: 2026-04-07
**Codename**: Polymarket Tab v1.0

## Highlights

Phoenix now trades prediction markets. The new **Polymarket** tab in the
dashboard gives you a dedicated runtime, connector, market-data pipeline, and
risk-controlled agent flow for Polymarket — sitting alongside your existing
equities/options agents and reusing the same lifecycle, backtesting, and
morning-briefing infrastructure.

This is a feature release. No breaking API changes for existing equities
workflows.

## What shipped (v1.0 scope)

| ID  | Feature                                         | Status   |
| --- | ----------------------------------------------- | -------- |
| F1  | Polymarket venue connector & market discovery   | Shipped  |
| F2  | Market data ingestion (books + trades)          | Shipped  |
| F3  | Polymarket agent runtime                        | Shipped  |
| F9  | Paper-mode-by-default + attestation gate        | Shipped  |
| F10 | Risk chain integration                          | Shipped  |
| F12 | Backtesting loader for historical Polymarket    | Shipped  |
| F13 | Dashboard tab + morning briefing section        | Shipped  |

## How to use it

### 1. Run database migrations

Alembic migrations `029`, `030`, and `031` must be applied before the API
starts. With Make:

```bash
make db-upgrade
```

Or directly:

```bash
alembic upgrade head
```

Verify you land at `031_pm_last_backtest_at` (or newer).

### 2. Open the Polymarket tab

A new **Polymarket** entry appears in the dashboard left nav. From here you
can:

- Browse discovered markets (events, outcomes, current books).
- Create a new Polymarket agent from the template.
- View the agent's backtest history and paper-mode P&L.

### 3. Paper mode is the default

Every new Polymarket agent starts in **paper mode**. It will:

- Subscribe to live market data.
- Run its strategy against real books.
- Record simulated fills and P&L.
- **Never** send a real order.

Paper mode is enforced server-side in the agent runtime and the risk chain —
it cannot be bypassed by UI state alone.

### 4. Promote to live

To promote a paper agent to live trading:

1. Open the agent detail page.
2. Click **Promote to live**.
3. Read the attestation dialog (jurisdiction, capital-at-risk, venue TOS).
4. Type the confirmation phrase and sign the attestation.
5. The server validates that:
   - The agent has been in paper mode for the minimum dwell time
     (`pm_paper_mode_since`).
   - A recent backtest exists (`pm_last_backtest_at`).
   - The user has the `pm_trader` role.
6. On success the agent transitions `paper → live` and becomes eligible to
   place real orders, still gated by the 3-layer risk chain.

There is **no auto-promotion**. Every live transition is a human-in-the-loop
decision.

### 5. Morning briefing

The morning briefing agent now includes a Polymarket section summarising open
positions, overnight P&L, upcoming event resolutions, and any agents that
tripped a risk guard.

## Known limitations

- **Single venue.** v1.0 trades Polymarket only. The Kalshi adapter is
  present as a stub and is not wired into discovery or execution — tracked as
  F4 for v1.1.
- **US jurisdiction disclaimer.** Polymarket has jurisdictional restrictions.
  Phoenix does not perform KYC/geofencing — users are responsible for
  compliance with their local laws and Polymarket's terms of service. See
  `docs/LEGAL.md`.
- **Deferred features** (tracked for v1.1+): multi-venue arbitrage (F4),
  advanced limit-order management (F5), cross-market correlation (F6),
  LLM-driven event resolution monitoring (F7), options hedging overlay (F8),
  social-sentiment ingestion (F11).
- **Backtest coverage.** Historical Polymarket data depth is limited by what
  the venue exposes; very old markets may not have full book reconstruction.

## Also in this release

**Backtester OOM fix.** Long-running backtests were getting SIGKILLed by
Docker OOM. Fixed via:

- `phoenix-api` container memory raised 512M → 2G.
- `NODE_OPTIONS` heap cap added.
- `WEB_CONCURRENCY=2` to bound Uvicorn worker count.
- Exit-code `-9` is now detected and surfaced as a fail-fast error in
  `agent_gateway.py` instead of hanging the UI.

## Upgrade steps

From `0.1.x`:

1. `git pull` and rebuild containers: `make down && make up` (or your Coolify
   deploy flow — note `docker-compose.coolify.yml` changed).
2. Apply migrations: `make db-upgrade`. Target revision includes
   `029_pm_v1_0_initial`, `030_pm_paper_mode_since`,
   `031_pm_last_backtest_at`.
3. Restart the dashboard; the Polymarket tab should appear automatically.
4. No `.env` changes are strictly required for paper mode. For live trading
   you will need Polymarket API credentials configured under the venue's
   broker section.

## Rollback plan

If a critical regression appears after deploy:

1. **Stop new Polymarket agents** from the dashboard (disable the tab via
   feature flag, or pause all `pm_*` agents from the orchestrator).
2. **Revert the deploy** to the previous image tag (`0.1.x`).
3. **Downgrade migrations** in reverse order only if schema is the problem:
   ```bash
   alembic downgrade 028
   ```
   Note: this drops Polymarket tables. Paper-mode state will be lost. Live
   positions, if any, must be closed manually at the venue first.
4. **Existing equities/options agents** are unaffected by the Polymarket
   tables and will continue running on `0.1.x`.

## Contacts

- Runbook: `docs/RUNBOOK.md`
- Legal / jurisdiction: `docs/LEGAL.md`
- Architecture: `docs/architecture/` (Polymarket sub-section)
- PRD: `docs/prd/` (Polymarket Tab v1.0)
