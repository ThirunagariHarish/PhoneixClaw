# Phase 14 — PM news collectors — Devin notes

## Scope
Phase 14 from `docs/architecture/polymarket-tab.md` (line 776). Brand-new
PM-specific news collectors per user decision #7. Pure ingestion only;
v1.2 F6 news reactor will consume the resulting Redis stream.

Untouched (per instructions): `agents/polymarket/`, `apps/api/`,
`apps/dashboard/`, `services/orchestrator/`, `services/execution/`,
`shared/polymarket/`.

## What was added
All under `services/message-ingestion/src/collectors/polymarket/`:

- `base.py` — `BasePMNewsCollector`, `PMNewsItem`, dedupe LRU,
  metrics counters, `parse_rss_datetime`, `make_item_id` (sha1 of
  source|url|title), category constants.
- `publisher.py` — `PMNewsPublisher` writing to the dedicated
  `pm:news` Redis stream via `XADD ... MAXLEN ~`. Catches Redis
  errors so a transient outage cannot crash the collector loop.
- `rss.py` — stdlib-only RSS 2.0 + Atom 1.0 parser. Avoids adding
  feedparser as a new dependency for v1.0.
- `election.py` — `ElectionNewsCollector` (no keyword filter; feeds
  are already topical).
- `sports.py` — `SportsNewsCollector` (no keyword filter; ESPN feeds
  are pre-filtered by league).
- `macro.py` — `MacroNewsCollector` with default macro keyword
  filter (CPI / NFP / FOMC / Powell / GDP / etc.) on top of Fed and
  BLS feeds.
- `crypto.py` — `CryptoNewsCollector` with default major-coin
  keyword filter on top of CoinDesk / CoinTelegraph feeds.
- `config.yaml` — feed URLs, poll intervals, keyword overrides per
  collector. Stream key is `pm:news`, MAXLEN ~ 50_000.
- `__init__.py` — package re-exports.

Tests:

- `tests/unit/services/message_ingestion/test_pm_collectors.py` —
  uses `respx` for HTTP mocking and a `FakeRedis` (xadd-only) for
  the publisher. Covers:
  - id stability + uniqueness
  - RSS 2.0 + Atom parsing
  - publisher write path + error swallowing
  - end-to-end poll for all 4 collectors
  - dedupe across two consecutive polls
  - macro/crypto keyword filtering drops unrelated items
  - HTTP non-200, network exception, parse error all increment
    `errors` and yield zero published items
  - **isolation assertion**: only `pm:news` is written, never any
    twitter/reddit/discord topic
  - invalid category raises at construction time

## Phase 14 DoD mapping
> "each collector writes to its dedicated topic, isolated from
> existing twitter/reddit/discord adapters; volumes show in metrics."

- Dedicated topic: `pm:news` Redis stream, configurable but
  defaulted in both `publisher.py` and `config.yaml`. The isolation
  assertion test verifies no other stream key is touched.
- Isolation from existing adapters: the new code lives in a new
  `collectors/polymarket/` subpackage and reuses none of
  `twitter_adapter.py`, `reddit_adapter.py`, `discord_adapter.py`,
  `base_adapter.py`, or `orchestrator.py`. Imports verified by
  inspection.
- Metrics: every collector exposes a `metrics` dict with
  `fetched / kept / duplicates / filtered / errors / published`
  counters; the publisher exposes `published_count`. A future
  Prometheus exporter (out of Phase 14 scope) can scrape these.

## Files touched
New files only — nothing existing was edited.

- `services/message-ingestion/src/collectors/__init__.py`
- `services/message-ingestion/src/collectors/polymarket/__init__.py`
- `services/message-ingestion/src/collectors/polymarket/base.py`
- `services/message-ingestion/src/collectors/polymarket/publisher.py`
- `services/message-ingestion/src/collectors/polymarket/rss.py`
- `services/message-ingestion/src/collectors/polymarket/election.py`
- `services/message-ingestion/src/collectors/polymarket/sports.py`
- `services/message-ingestion/src/collectors/polymarket/macro.py`
- `services/message-ingestion/src/collectors/polymarket/crypto.py`
- `services/message-ingestion/src/collectors/polymarket/config.yaml`
- `tests/unit/services/message_ingestion/test_pm_collectors.py`

(`tests/unit/services/__init__.py` and
`tests/unit/services/message_ingestion/__init__.py` already existed
or were created as empty package markers.)

## Deviations from the plan
None on the design. One mechanical note:

- The `services/message-ingestion/` directory uses a hyphen, which
  is not a valid Python module name. The existing
  `services/backtest-runner/src/pipeline.py` references it as
  `services.message_ingestion.src.orchestrator`, which only works
  via dynamic loading or path injection. To keep the new collectors
  importable in tests without depending on whatever the runtime
  uses, the test file inserts
  `services/message-ingestion/src` onto `sys.path` and imports the
  collectors as `collectors.polymarket.*`. This matches the
  existing pattern for the in-repo orchestrator and avoids any
  conftest changes. If Build prefers a stable importable name, the
  cleanest fix is to rename the directory to
  `services/message_ingestion/` (out of Phase 14 scope).

## Local checks
**Blocked:** the Bash tool is denied in this Devin session, so I
could not run `make test` / `make lint` myself. The code was
reviewed by inspection only:

- `pytest tests/unit/services/message_ingestion/test_pm_collectors.py -v`
  — needs to be run by Quill / Build.
- `make lint` — needs to be run.
- `make typecheck` — needs to be run.

I am explicitly flagging this rather than marking the phase
"green". If any of these fail, route back to me with output and I
will fix without bypassing.

## Open risks / follow-ups
- **Scheduler not wired.** Phase 14 only ships the collectors and
  config. A scheduler that calls `collector.poll_once()` on the
  configured interval is intentionally not part of Phase 14 — the
  architecture doc only requires "each collector writes to its
  dedicated topic." The future F6 reactor (v1.2) or a small
  APScheduler entry point can call them. Flag for Build to confirm
  whether a scheduler entry point is wanted now or deferred.
- **Feed reachability** is not validated against real endpoints in
  unit tests; that belongs in an integration test outside Phase 14.
- **Keyword filter coverage** for macro and crypto is conservative.
  v1.2 F6's LLM scoring is the intended quality layer; v1.0 errs
  toward over-inclusion of high-signal items.
- **Per-process dedupe only.** Restarting a collector replays
  already-published items until they age out of the source feed.
  This is acceptable for v1.0 because the F6 reactor is not yet
  consuming, and the stream MAXLEN cap bounds growth. Persistent
  dedupe (Redis SET with TTL) is a v1.2 follow-up if needed.
