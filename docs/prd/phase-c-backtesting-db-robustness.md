# PRD: Phase C — DB-Backed Backtesting Robustness + Channel Coverage Audit

Version: 1.0 | Status: Draft | Date: 2026-04-18 | Author: Nova-PM

## Problem Statement

Phoenix used to ingest Discord via scraping; it now uses a Discord bot writing to the `channel_messages` Postgres table. Backtesting must read historical messages from `channel_messages` exclusively — never live Discord. Coverage may be uneven across channels (target: 2 years of history per channel), and channel naming is inconsistent across DB columns, connector config, agent config, dashboard, and tests. A backfill tool is needed for channels with gaps.

## Goals

1. **DB-only verification**: zero live Discord API calls during backtest runs.
2. **Coverage audit**: verify 24 months of history per configured channel; identify gaps.
3. **Channel naming audit**: standardize `channel_id` vs `channel_name` usage; migration plan if inconsistent.
4. **Backfill tooling**: bulk historical import (Discord API → `channel_messages`) with idempotency and resumability.
5. **Architecture documentation**: full DB-backed backtesting flow documented.

## Non-Goals

- Pipeline engine (Phase A)
- AI flow enhancements (Phase B)
- Live signal routing changes
- Multi-connector backtesting (single connector scope per backtest remains)
- OpenClaw orchestration (Phase F)
- Performance/speed improvements to the backtest pipeline itself

## User Stories

### US-1: Operator Onboarding a New Channel
As an operator onboarding a new Discord channel, I want to run a coverage audit and, if history is short, trigger a backfill so that the first backtest has 2 years of data.

**Acceptance:** CLI `audit` returns pass/fail; CLI `backfill <channel>` populates gaps and is resumable.

### US-2: Data Scientist Running Multi-Channel Backtests Offline
As a data scientist, I want to run backtests with network disabled and still have them complete, so that my results are reproducible and do not depend on Discord availability.

**Acceptance:** Backtest run in a container with no external egress completes successfully for any channel with DB coverage.

### US-3: Engineer Debugging Naming Inconsistencies
As an engineer, I want a naming audit output showing every place a channel is referenced and the current form used, so that I can standardize without guesswork.

**Acceptance:** Audit output JSON lists references by path, field, value format, and flags mismatches.

## Functional Requirements

### F-1: Coverage Audit Tool
CLI tool: `python -m backtesting.tools.coverage_audit`. For every channel in `connectors.config.channel_ids`:
- row count in `channel_messages`
- min(`created_at`), max(`created_at`)
- pass if `max - min >= 24 months` AND row count above a threshold (TBD)
- fail otherwise; emit structured JSON + human summary

### F-2: Channel Naming Audit Tool
CLI tool scans:
- DB schema (`channel_messages`, `connectors`, `backtest_trade`)
- Code references in `apps/`, `services/`, `shared/`, `agents/`
- Config files (`.env.example`, `docker-compose.yml`, Makefile)
- Dashboard TypeScript types

Output: every reference point, the field name, and the format used (`#name`, `name`, UUID, Discord snowflake). Flags inconsistencies. Proposes canonical form (Atlas decides in architecture phase).

### F-3: Backfill Tool
CLI tool: `python -m backtesting.tools.backfill --channel <channel_id> [--from <date>] [--to <date>]`.
- Uses Discord bot credentials from `connectors` table
- Respects Discord API rate limits (honors `Retry-After` on 429)
- Idempotent: skips already-imported messages via `platform_message_id` unique key
- Resumable: checkpoint file (`./backfill-checkpoint.json`) with last cursor per channel; resumes on restart
- Streams to DB in batches (500 messages/commit)
- Emits progress log: percent complete, ETA, rate-limit waits

### F-4: DB-Only Verification
- Code audit: document/remove live-Discord code paths in the backtest pipeline. Identified target: `agents/backtesting/tools/transform.py` lines 121–186 `fetch_discord_history()` which calls `discord.com/api/v10`. Deprecate or remove.
- Enforce `--source postgres` mode (already supported) as the only valid mode for backtests; make it the default.
- Integration test: run a full backtest with egress blocked at container level; must pass.

### F-5: Architecture Documentation
Write `docs/architecture/backtesting-db-flow.md` with:
- Data flow from ingestion → `channel_messages` → backtest pipeline
- Which tools read which tables
- Schema of `channel_messages` and FK relationships
- Resumability semantics of backfill
- Retention policy (Atlas decides)

## Acceptance Criteria

1. Coverage audit CLI exists; produces JSON + human summary for all configured channels.
2. Every configured channel has ≥24 months coverage, OR a documented backfill plan is in place.
3. Naming audit CLI exists; output lists all references; zero inconsistencies remain OR migration plan is documented.
4. Canonical channel identifier form is chosen and enforced (schema + code).
5. Backfill tool is idempotent (re-running does not duplicate rows).
6. Backfill tool is resumable (killing mid-run and restarting resumes from checkpoint).
7. Backfill tool tested on at least one real channel with ≥10k historical messages.
8. Backtest pipeline runs successfully with network egress disabled.
9. `fetch_discord_history()` in `transform.py` is deprecated or removed.
10. `docs/architecture/backtesting-db-flow.md` exists and is accurate.

## Dependencies

- `channel_messages` table and schema
- Discord bot credentials from `connectors` table
- `agents/backtesting/` pipeline
- `shared/discord_utils/channel_discovery.py`

## Risks

| # | Risk | Mitigation |
|---|---|---|
| C-R1 | Discord API rate limits during large backfill | Honor `Retry-After`; chunked requests; checkpoint every batch; run off-hours |
| C-R2 | `backtest_trade.channel_message_id` FK blocks re-imports | Idempotent UPSERT on `platform_message_id`; never delete existing rows |
| C-R3 | Naming migration breaks live agents mid-run | Multi-phase deprecation: add new column, dual-write, migrate readers, drop old |
| C-R4 | Discord API returns partial message history for older channels | Document the limit in coverage audit; flag channels where Discord's cap is hit |
| C-R5 | Backfill imports messages with different ordering/IDs than live ingestion | Use `discord.Message.id` as canonical `platform_message_id`; verify with cross-check |

## Open Questions for Atlas

1. How do we identify the "backtestable channel" set? From `connectors` table, from `channel_messages` distinct values, or explicit allowlist?
2. Should backfilled data be versioned (backfill_run_id) for traceability?
3. Retention policy for `channel_messages` — infinite, or rolling window?
4. Should coverage-audit failures auto-trigger backfill, or stay manual?
5. Migration strategy for channel naming: single cutover, or multi-phase deprecation?

## Out of Scope

- Pipeline engine (Phase A)
- AI flow (Phase B)
- OpenClaw (Phase F)
- Backtest pipeline performance tuning
- Multi-connector backtesting
- Streaming partial results to dashboard

## Codebase Audit Findings (for Atlas)

1. **`transform.py` has a live-Discord path** (lines 121–186 `fetch_discord_history()` calls `discord.com/api/v10`). Needs deprecation/removal.
2. **`--source postgres` mode exists** but is not enforced — make it the only supported mode.
3. **Channel naming is inconsistent**:
   - `channel_messages.channel` (String 200) stores mixed format
   - `connectors.config.channel_ids` stores list of Discord IDs
   - `discord-ingestion` extracts from multiple keys (`channel_ids`, `channel_id`, `selected_channels`)
4. **No coverage tooling exists** today.

## Handoff to Atlas

Atlas produces: coverage audit CLI spec; naming audit CLI spec; backfill tool architecture (rate-limit handling, checkpoint format, resumption semantics); canonical channel identifier choice + migration plan; backtest DB-only enforcement mechanism; `docs/architecture/backtesting-db-flow.md`.
