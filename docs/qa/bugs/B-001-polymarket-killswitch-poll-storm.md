# Bug B-001: Polymarket kill-switch status endpoint is polled at excessive frequency

Severity: P2
Env: Dashboard http://localhost:3000, API http://localhost:8011, Chromium (Playwright MCP), macOS, 2026-04-07

Steps:
1. Log in to dashboard.
2. Navigate to /polymarket.
3. Stay on the page for ~1 minute and observe the network panel (or run Playwright `browser_network_requests` filter `/polymarket`).

Expected:
`GET /api/polymarket/kill-switch/status` polls at a modest cadence (e.g. every 2–5 seconds), as is typical for a status indicator.

Actual:
During the smoke run, `GET /api/polymarket/kill-switch/status` fired ~80+ times over a session of roughly 60–90 seconds while the user was merely clicking through tabs. The kill-switch call fires in clusters of 3–7 back-to-back between every other request (`markets`, `strategies`, `orders`, `positions`, `briefing/section`, `jurisdiction/current`). That suggests the status hook is either re-subscribing on every render, being fired per-component instance (Header + Risk tab + Briefing tab all showing "Kill switch idle"), or lacks a shared query key / dedupe.

Evidence:
- Network trace captured in this session: see `docs/qa/polymarket/smoke-report.md` network section (80+ `kill-switch/status` entries, all 200).
- Representative cluster: 7 consecutive `kill-switch/status` calls sandwiched around a single `markets?limit=100` request.
- All responses 200, so no user-facing error — but it will generate unnecessary load on the Control Plane and hot-path the DB/Redis backing the status check.

Expected vs Actual:
- Expected: 1 shared TanStack Query with `refetchInterval` on the order of 2000–5000 ms, deduped across consumers.
- Actual: Multiple independent subscribers and/or a very low interval / refetch-on-every-render.

Suspected area:
- `apps/dashboard/src/pages/polymarket/*` — kill switch indicator hook (likely used in the Polymarket header, Risk tab, and Briefing tab simultaneously).
- Most likely cause: each component calls `useQuery` with a different query key, or a `useEffect` that calls fetch on every render, or `refetchInterval` set far too low.

Fix suggestion (for Devin via Build):
- Centralize the kill-switch status into a single `useKillSwitchStatus()` hook with a stable query key (e.g. `['polymarket', 'kill-switch', 'status']`), `refetchInterval: 3000`, `refetchOnWindowFocus: false`. All three consumers should reuse this hook so TanStack Query dedupes them.

Not a release blocker for a local smoke, but should be fixed before any staging/load test.
