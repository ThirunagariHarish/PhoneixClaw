"""Coverage Audit CLI — verify Discord channel message history coverage.

Validates that each configured Discord channel has at least N months of history
and a minimum message count. Outputs structured JSON and human-readable summary.

Architecture: docs/architecture/phase-c-backtesting-db-robustness.md §5

Usage:
    python -m tools.coverage_audit [--connector-id <uuid>] [--output coverage.json] \
        [--min-months 24] [--min-messages 100]

Exit codes:
    0 - All channels pass
    1 - One or more channels fail coverage requirements
    2 - Tool error (DB connection, invalid args, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from shared.db.engine import async_session


async def run_coverage_audit(
    connector_id: str | None = None,
    min_months: int = 24,
    min_messages: int = 100,
) -> dict[str, Any]:
    """Execute coverage audit and return structured results.

    Args:
        connector_id: Optional UUID to audit a single connector
        min_months: Minimum required months of history
        min_messages: Minimum required message count

    Returns:
        Dict with keys: audit_timestamp, threshold_months, channels_total,
        channels_pass, channels_fail, failures, passes
    """
    session = async_session()
    try:
        # Query active Discord connectors
        query = text(
            """
            SELECT id, name, config
            FROM connectors
            WHERE type = 'discord' AND is_active = true
            """
        )
        if connector_id:
            query = text(
                """
                SELECT id, name, config
                FROM connectors
                WHERE id = :cid AND type = 'discord' AND is_active = true
                """
            )
            result = await session.execute(query, {"cid": connector_id})
        else:
            result = await session.execute(query)

        connectors = result.fetchall()

        if not connectors:
            return {
                "audit_timestamp": datetime.now(timezone.utc).isoformat(),
                "threshold_months": min_months,
                "channels_total": 0,
                "channels_pass": 0,
                "channels_fail": 0,
                "failures": [],
                "passes": [],
            }

        failures = []
        passes = []

        for row in connectors:
            conn_id, conn_name, config = row
            channel_ids = config.get("channel_ids", [])

            if not channel_ids:
                continue

            for channel_id in channel_ids:
                # Query channel_messages for this channel
                # Handle both channel_id_snowflake (new) and channel (old) columns
                count_query = text(
                    """
                    SELECT
                        COUNT(*) as msg_count,
                        MIN(posted_at) as earliest,
                        MAX(posted_at) as latest
                    FROM channel_messages
                    WHERE connector_id = :cid
                      AND (channel_id_snowflake = :ch_id OR channel = :ch_id)
                    """
                )
                channel_result = await session.execute(
                    count_query, {"cid": str(conn_id), "ch_id": str(channel_id)}
                )
                channel_row = channel_result.fetchone()

                if not channel_row or channel_row[0] == 0:
                    # No messages found
                    failures.append(
                        {
                            "connector_id": str(conn_id),
                            "connector_name": conn_name,
                            "channel_id": str(channel_id),
                            "message_count": 0,
                            "date_range_days": 0,
                            "earliest_message": None,
                            "latest_message": None,
                            "reason": "No messages found in database",
                            "recommended_backfill": (
                                f"python -m tools.backfill --connector-id {conn_id} "
                                f"--channel-id {channel_id}"
                            ),
                        }
                    )
                    continue

                msg_count, earliest, latest = channel_row

                if earliest and latest:
                    date_range_days = (latest - earliest).days
                else:
                    date_range_days = 0

                required_days = min_months * 30

                # Check if channel passes requirements
                if date_range_days >= required_days and msg_count >= min_messages:
                    passes.append(
                        {
                            "connector_id": str(conn_id),
                            "connector_name": conn_name,
                            "channel_id": str(channel_id),
                            "message_count": msg_count,
                            "date_range_days": date_range_days,
                            "earliest_message": earliest.isoformat() if earliest else None,
                            "latest_message": latest.isoformat() if latest else None,
                        }
                    )
                else:
                    # Determine reason
                    reasons = []
                    if date_range_days < required_days:
                        reasons.append(f"Insufficient history ({date_range_days} < {required_days} days)")
                    if msg_count < min_messages:
                        reasons.append(f"Insufficient messages ({msg_count} < {min_messages})")

                    # Calculate backfill start date
                    if latest:
                        from_date = (latest - (latest - earliest) - (latest - earliest)).strftime("%Y-%m-%d")
                    else:
                        from_date = "2022-01-01"

                    failures.append(
                        {
                            "connector_id": str(conn_id),
                            "connector_name": conn_name,
                            "channel_id": str(channel_id),
                            "message_count": msg_count,
                            "date_range_days": date_range_days,
                            "earliest_message": earliest.isoformat() if earliest else None,
                            "latest_message": latest.isoformat() if latest else None,
                            "reason": "; ".join(reasons),
                            "recommended_backfill": (
                                f"python -m tools.backfill --connector-id {conn_id} "
                                f"--channel-id {channel_id} --from {from_date}"
                            ),
                        }
                    )

        return {
            "audit_timestamp": datetime.now(timezone.utc).isoformat(),
            "threshold_months": min_months,
            "threshold_messages": min_messages,
            "channels_total": len(passes) + len(failures),
            "channels_pass": len(passes),
            "channels_fail": len(failures),
            "failures": failures,
            "passes": passes,
        }

    finally:
        await session.close()


def print_human_summary(result: dict[str, Any]) -> None:
    """Print human-readable summary to stderr."""
    sys.stderr.write("\nCoverage Audit Summary\n")
    sys.stderr.write("======================\n")
    sys.stderr.write(f"Audit Timestamp: {result['audit_timestamp']}\n")
    threshold_msg = result.get('threshold_messages', 100)
    sys.stderr.write(f"Threshold: {result['threshold_months']} months, {threshold_msg} messages\n")
    sys.stderr.write(f"Total Channels: {result['channels_total']}\n")
    sys.stderr.write(f"Passed: {result['channels_pass']}\n")
    sys.stderr.write(f"Failed: {result['channels_fail']}\n\n")

    if result["passes"]:
        sys.stderr.write("Passing Channels:\n")
        for p in result["passes"]:
            sys.stderr.write(
                f"  PASS {p['connector_name']} / {p['channel_id']}: "
                f"{p['message_count']} msgs, {p['date_range_days']} days\n"
            )

    if result["failures"]:
        sys.stderr.write("\nFailing Channels:\n")
        for f in result["failures"]:
            sys.stderr.write(
                f"  FAIL {f['connector_name']} / {f['channel_id']}: "
                f"{f['message_count']} msgs, {f['date_range_days']} days\n"
            )
            sys.stderr.write(f"       Reason: {f['reason']}\n")
            sys.stderr.write(f"       Backfill: {f['recommended_backfill']}\n")

    sys.stderr.write("\n")


async def main_async(args: argparse.Namespace) -> int:
    """Run coverage audit and handle output."""
    try:
        result = await run_coverage_audit(
            connector_id=args.connector_id,
            min_months=args.min_months,
            min_messages=args.min_messages,
        )

        # Write JSON output
        if args.output:
            with open(args.output, "w") as f:
                json.dump(result, f, indent=2)
            sys.stderr.write(f"Coverage audit results written to {args.output}\n")

        # Print human summary
        print_human_summary(result)

        # Determine exit code
        if result["channels_fail"] > 0:
            return 1
        return 0

    except Exception as e:
        sys.stderr.write(f"ERROR: Coverage audit failed: {e}\n")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 2


def main() -> None:
    """Entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Audit Discord channel message coverage for backtesting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--connector-id",
        type=str,
        help="Optional UUID of specific connector to audit",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Path to write JSON results (default: stdout)",
    )
    parser.add_argument(
        "--min-months",
        type=int,
        default=24,
        help="Minimum required months of history (default: 24)",
    )
    parser.add_argument(
        "--min-messages",
        type=int,
        default=100,
        help="Minimum required message count (default: 100)",
    )

    args = parser.parse_args()

    # Validate connector_id if provided
    if args.connector_id:
        try:
            uuid.UUID(args.connector_id)
        except ValueError:
            sys.stderr.write(f"ERROR: Invalid UUID format for --connector-id: {args.connector_id}\n")
            sys.exit(2)

    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
