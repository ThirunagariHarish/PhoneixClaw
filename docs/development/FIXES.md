# PhoenixTrade Platform — Fixes (February 2026)

This document describes all bugs fixed and their root causes, for future reference.

---

## Issue 1: Sync Channels Not Working

**Symptom:** Clicking "Sync Channels" on the Data Sources page returned 0 channels, or the
operation appeared to do nothing.

**Root cause:** The `_ensure_channels_from_credentials` function assumed `channel_ids` was always
stored as a comma-separated string. Some sources stored them as a Python list `[123, 456]`, and
`list.split(",")` would throw or return empty results. Additionally, the endpoint filtered by
`user_id`, preventing admins from syncing other users' sources.

**Fix (sources.py):**
- `_ensure_channels_from_credentials` now handles both `str` and `list` formats.
- Added `_get_source_for_user_or_admin` helper that skips ownership check for admin users.
- The `sync-channels` endpoint now returns an explicit 400 error if no channel_ids are found.
- Frontend invalidates `['channels']` queries after sync so Backtesting page updates.

**Files changed:**
- `services/api-gateway/src/routes/sources.py`
- `services/dashboard-ui/src/pages/DataSources.tsx`

---

## Issue 2: Raw Messages Not Appearing

**Symptom:** Messages from Discord did not appear on the Raw Messages page.

**Root cause:** Multiple potential failure points in the pipeline:
1. `DiscordIngestor.start()` could fail silently if `discord.py-self` didn't support the `bot=`
   parameter.
2. `RawMessageWriterService._flush()` had no retry logic — transient DB errors caused message loss.
3. No logging made it difficult to diagnose which stage was failing.

**Fix:**
- `DiscordIngestor.start()` now catches `TypeError` from `bot=` param and retries without it.
  Enhanced logging shows user, mode, channels, and data_source on connect/failure.
- `RawMessageWriterService` now retries flush up to 3 times with backoff on DB errors.
  Tracks `_total_written` and `_total_errors` counters logged on shutdown.
- `stop()` methods wrapped in try/except to prevent cascade failures.

**Files changed:**
- `services/discord-ingestor/src/connector.py`
- `services/audit-writer/src/raw_message_writer.py`

---

## Issue 3: Admin Not Seeing All Data Sources

**Symptom:** An admin user only saw their own data sources, not sources from other users.

**Root cause:** The `/auth/refresh` endpoint created a new access token WITHOUT the `is_admin`
claim. After any token refresh (which happens automatically), the JWT lost the `admin: true` flag,
so the API middleware set `request.state.is_admin = False`.

```python
# BEFORE (broken):
access_token = create_access_token(user_id)  # is_admin defaults to False

# AFTER (fixed):
user = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
access_token = create_access_token(user_id, is_admin=user.is_admin)
```

**Fix:** The refresh endpoint now queries the User from the database and passes the current
`is_admin` value when creating the new access token.

**Files changed:**
- `services/auth-service/src/auth.py`

---

## Issue 4: Backtesting Cannot View Channels

**Symptom:** The channel dropdown in the Backtesting wizard was empty, even after adding a data
source with channel IDs.

**Root cause:** The `GET /sources/{id}/channels` endpoint only returned channels from the
`channels` table. For pre-existing sources (created before the sync feature), the table was empty
because `_ensure_channels_from_credentials` was never called.

**Fix:**
- `list_channels` endpoint now performs a **lazy sync**: if no channels exist in the table, it
  decrypts credentials and auto-creates them on-the-fly.
- Backtesting page shows a "Sync Channels" button when the dropdown is empty, with a loading state.
- Frontend properly shows loading/empty/populated states for the channel dropdown.

**Files changed:**
- `services/api-gateway/src/routes/sources.py`
- `services/dashboard-ui/src/pages/Backtesting.tsx`

---

## Issue 5: Docker Deployment Optimization

**Symptom:** Deployment rebuilt all 14 Docker images every time, taking 10+ minutes. The
`nlp-parser` service (1.5GB with ML models) was particularly slow and caused disk exhaustion.

**Root cause:**
- No BuildKit cache mounts — pip/npm downloaded everything from scratch each build.
- No selective build — all services rebuilt even for single-file changes.
- `nlp-parser` combined pip install + model downloads in one stage, so any requirements change
  re-downloaded all ML models.

**Fix:**
- All 13 Python Dockerfiles: added `# syntax=docker/dockerfile:1` and
  `--mount=type=cache,target=/root/.cache/pip` for pip caching.
- `dashboard-ui`: added `--mount=type=cache,target=/root/.npm` for npm caching.
- `nlp-parser`: split into 3 stages (deps → models → runtime) so model downloads are cached
  independently. Removed `CACHEBUST` arg that was invalidating the cache.
- Created `scripts/selective-build.sh` that uses `git diff` to detect changed services and
  only builds those.

**Files changed:**
- All `services/*/Dockerfile` files
- New: `scripts/selective-build.sh`

---

## Testing

Integration tests were added covering:
- Trade parser end-to-end (5 valid signals + 5 noise messages)
- Raw message writer flush with mocked DB
- Raw message writer retry on DB failure
- Auth token admin claim preservation
- Channel sync with string, list, and duplicate handling

**Test file:** `tests/integration/test_e2e_pipeline.py` (19 tests)
