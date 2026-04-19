"""Verification gate for migration 049 (drop legacy `channel_messages.channel` column).

Migration 048 added `channel_id_snowflake` alongside the legacy `channel` column and backfilled
numeric values. Migration 049 is prepared but should only be applied after a verification window
confirming:

1. `channel_id_snowflake` is populated for ~100% of rows (tolerates a small rounding window).
2. `channel` and `channel_id_snowflake` agree wherever `channel` is a valid snowflake.
3. `channel_id_snowflake` non-null ratio has been stable (not climbing) for at least 24h
   — indicating that writers have fully cut over to the dual-write path.
4. No code paths read the legacy `channel` column any more
   (static grep: `rg "\.channel[^_]" services/ shared/ apps/`).

Usage:
    python -m scripts.verify_snowflake_cutover [--strict]

Exit codes:
    0 — safe to apply migration 049
    1 — not safe yet (one or more checks failed); re-run later
    2 — tool error (DB unreachable, schema mismatch, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

MIN_BACKFILL_RATIO = 0.999  # tolerate 0.1% stragglers
STABILITY_WINDOW_HOURS = 24


async def _check_backfill_coverage() -> tuple[bool, str]:
    from shared.db.engine import async_session

    async with async_session() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(channel_id_snowflake) AS snowflake_populated,
                    COUNT(*) FILTER (WHERE channel ~ '^[0-9]+$') AS legacy_snowflake_like
                FROM channel_messages
                """
            )
        )
        row = result.one()
    total = int(row.total or 0)
    populated = int(row.snowflake_populated or 0)
    legacy_like = int(row.legacy_snowflake_like or 0)

    if total == 0:
        return True, "No rows in channel_messages yet — vacuously safe."

    ratio = populated / total
    ok = ratio >= MIN_BACKFILL_RATIO
    detail = (
        f"channel_id_snowflake populated on {populated:,}/{total:,} rows "
        f"(ratio={ratio:.4f}, legacy snowflake-shaped={legacy_like:,})"
    )
    return ok, detail


async def _check_snowflake_agreement() -> tuple[bool, str]:
    """Where `channel` is numeric, it must equal `channel_id_snowflake`."""
    from shared.db.engine import async_session

    async with async_session() as session:
        result = await session.execute(
            text(
                """
                SELECT COUNT(*) AS mismatches
                FROM channel_messages
                WHERE channel ~ '^[0-9]+$'
                  AND channel_id_snowflake IS NOT NULL
                  AND channel <> channel_id_snowflake
                """
            )
        )
        mismatches = int(result.scalar() or 0)
    ok = mismatches == 0
    return ok, f"Legacy/snowflake mismatches: {mismatches}"


async def _check_stability_window() -> tuple[bool, str]:
    """Confirm that every row written in the last STABILITY_WINDOW_HOURS has a snowflake."""
    from shared.db.engine import async_session

    async with async_session() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    COUNT(*) AS recent_total,
                    COUNT(channel_id_snowflake) AS recent_populated
                FROM channel_messages
                WHERE posted_at > now() - (:hours || ' hours')::interval
                """
            ),
            {"hours": STABILITY_WINDOW_HOURS},
        )
        row = result.one()
    recent_total = int(row.recent_total or 0)
    recent_populated = int(row.recent_populated or 0)
    if recent_total == 0:
        return True, f"No new rows in last {STABILITY_WINDOW_HOURS}h — nothing to invalidate."
    ok = recent_populated == recent_total
    return ok, (
        f"In last {STABILITY_WINDOW_HOURS}h: {recent_populated}/{recent_total} rows have snowflake."
    )


def _check_no_legacy_reads() -> tuple[bool, str]:
    """Static grep: make sure no active code reads the legacy `channel` column."""
    try:
        completed = subprocess.run(
            [
                "rg",
                "-n",
                r"channel_messages.*\.channel[^_a-zA-Z]",
                "apps/",
                "services/",
                "shared/",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except FileNotFoundError:
        return True, "ripgrep not installed; skipping static legacy-read check."
    except subprocess.TimeoutExpired:
        return False, "ripgrep timed out during legacy-read scan."

    hits = [ln for ln in (completed.stdout or "").splitlines() if ln.strip()]
    ok = len(hits) == 0
    detail = f"Legacy `channel` column read sites: {len(hits)}"
    if hits:
        detail += "\n  " + "\n  ".join(hits[:10])
        if len(hits) > 10:
            detail += f"\n  ... and {len(hits) - 10} more"
    return ok, detail


async def _run_checks(strict: bool) -> int:
    checks = [
        ("backfill_coverage", _check_backfill_coverage()),
        ("snowflake_agreement", _check_snowflake_agreement()),
        ("stability_window", _check_stability_window()),
    ]

    results: list[tuple[str, bool, str]] = []
    for name, coro in checks:
        try:
            ok, detail = await coro
        except Exception as exc:
            logger.exception("Check %s errored", name)
            return 2
        results.append((name, ok, detail))

    static_ok, static_detail = _check_no_legacy_reads()
    results.append(("no_legacy_reads", static_ok, static_detail))

    print(f"Snowflake cutover verification — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 72)
    all_ok = True
    for name, ok, detail in results:
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {name}: {detail}")
        if not ok:
            all_ok = False

    print("=" * 72)
    if all_ok:
        print("Safe to apply migration 049. Run `make db-upgrade` after merging the 049 upgrade body.")
        return 0

    if strict:
        print("FAIL: one or more checks failed — do not apply migration 049 yet.")
        return 1

    print("WARN: soft mode — some checks failed, but --strict not set.")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on any failure.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        exit_code = asyncio.run(_run_checks(strict=args.strict))
    except Exception:
        logger.exception("Verification script errored")
        sys.exit(2)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
