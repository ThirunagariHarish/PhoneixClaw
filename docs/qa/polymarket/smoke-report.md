# Polymarket Tab — Smoke Report

Date: 2026-04-07
Tester: Quill (QA)
Env: Dashboard http://localhost:3000, API http://localhost:8011, Chromium (Playwright MCP), macOS Darwin 25.3.0
User: quill@phoenix.dev (self-registered via /auth/register; `admin@phoenix.local` seed rejected by pydantic EmailStr — `.local` TLD)

## Verdict: READY (with 1 P2 bug)

All acceptance criteria for the smoke pass:
- Sidebar has `Polymarket` entry under Trading section, routes to `/polymarket`.
- Page loads with zero JS errors.
- All 7 tabs render (Markets, Strategies, Orders, Positions, Promotion, Briefing, Risk).
- Jurisdiction attestation banner visible (user has no attestation); "Attest" CTA present.
- Global "Kill Switch" button top-right opens confirm dialog with Cancel / Activate (Cancel works, not activated).
- All Polymarket API endpoints return 200.

## Per-tab results

| Tab | Render | API calls | Errors | Status |
|---|---|---|---|---|
| Markets | OK — filters (category, min volume, F9 checkbox), Force scan, table with headers Question/Category/Volume/Liquidity/Expiry/F9, empty state "No markets match the current filters." + "Showing 0 of 0 markets" | `GET /api/polymarket/markets?limit=100` → 200 | none | PASS |
| Strategies | OK — empty state "No Polymarket strategies registered yet." | `GET /api/polymarket/strategies` → 200 | none | PASS |
| Orders | OK — table headers SUBMITTED/MODE/SIDE/QTY/LIMIT/STATUS/FEES/SLIP BPS/F9, "No orders." | `GET /api/polymarket/orders?limit=200` → 200 | none | PASS |
| Positions | OK — headers OPENED/MODE/QTY/AVG ENTRY/UNREALIZED/REALIZED/CLOSED, "No positions." | `GET /api/polymarket/positions` → 200 | none | PASS |
| Promotion | OK — "STRATEGY / no strategies", "Last gate evaluation", "No promotion attempts yet.", "Audit history / No audit rows." | (covered by /strategies) | none | PASS |
| Briefing | OK — PAPER P&L $0, LIVE P&L $0, MOVERS 0, F9 RISKS 0, Kill switch idle, raw JSON section | `GET /api/polymarket/briefing/section` → 200 | none | PASS |
| Risk | OK — Kill switch idle, Jurisdiction "missing/expired", Strategy status Total 0 / Live 0 / Paused 0 | (status + strategies) | none | PASS |

## Jurisdiction banner
Banner renders with red "Jurisdiction attestation required" heading and copy referencing LEGAL.md. `Attest` button present. Not clicked (no valid attestation modified). `GET /api/polymarket/jurisdiction/current` → 200. PASS.

## Kill switch dialog
Top-right button triggers an alertdialog:
- Title: "Activate Polymarket kill switch?"
- Body: "All Polymarket strategies will halt within 2 seconds. Open orders are cancelled where possible. This event is logged."
- Reason textbox, Cancel + Activate + Close buttons.
- Cancel dismisses cleanly — no network mutation fired.
PASS (no activation per instructions).

## Console errors (whole session)
- `POST /auth/login 422` × 2 — expected, from wrong creds during login bootstrapping. Not a Polymarket bug but see B-002 for UX observation.
- `GET /api/v2/performance/by-agent 404` — unrelated to Polymarket (fires once on another page load). Not a Polymarket blocker.
- Zero console errors on the `/polymarket` route itself.

## Failed network requests on /polymarket
None. 100% of Polymarket API calls returned 200.

## Screenshots
Playwright MCP `browser_take_screenshot` timed out (5s) after fonts-loaded, likely a tooling/driver hang unrelated to the app (text DOM snapshots captured cleanly instead). Raw page snapshots stored at:
- /Users/harishkumar/Projects/TradingBot/ProjectPhoneix/.playwright-mcp/page-2026-04-07T16-44-46-855Z.yml (Markets)
- /Users/harishkumar/Projects/TradingBot/ProjectPhoneix/.playwright-mcp/page-2026-04-07T16-47-27-915Z.yml (Strategies)
- /Users/harishkumar/Projects/TradingBot/ProjectPhoneix/.playwright-mcp/page-2026-04-07T16-50-30-743Z.yml (Orders)
- /Users/harishkumar/Projects/TradingBot/ProjectPhoneix/.playwright-mcp/page-2026-04-07T16-50-44-667Z.yml (Positions)
- /Users/harishkumar/Projects/TradingBot/ProjectPhoneix/.playwright-mcp/page-2026-04-07T16-50-56-913Z.yml (Promotion)
- /Users/harishkumar/Projects/TradingBot/ProjectPhoneix/.playwright-mcp/page-2026-04-07T16-51-09-673Z.yml (Briefing)
- /Users/harishkumar/Projects/TradingBot/ProjectPhoneix/.playwright-mcp/page-2026-04-07T16-51-21-910Z.yml (Risk)
- /Users/harishkumar/Projects/TradingBot/ProjectPhoneix/.playwright-mcp/page-2026-04-07T16-51-37-730Z.yml (Kill switch dialog)

## Bugs filed
- B-001 (P2): `kill-switch/status` polled at excessive rate
- B-002 (P3): Seeded admin email `admin@phoenix.local` rejected by /auth/login (422)
