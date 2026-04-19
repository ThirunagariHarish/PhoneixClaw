"""Naming Audit CLI — scan DB schema, code, config for channel naming inconsistencies.

Identifies mixed formats, multiple keys, and missing indexes for channel references.
Outputs structured JSON with findings and migration recommendations.

Architecture: docs/architecture/phase-c-backtesting-db-robustness.md §6

Usage:
    python -m tools.naming_audit [--output naming-audit.json] [--verbose]

Exit codes:
    0 - Success (findings may or may not be present)
    2 - Tool error
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from shared.db.engine import async_session

REPO_ROOT = Path(__file__).parent.parent.absolute()


async def scan_db_schema() -> list[dict[str, Any]]:
    """Scan database schema for channel-related columns."""
    findings = []
    session = async_session()

    try:
        # Query information_schema for channel-related columns
        query = text(
            """
            SELECT table_name, column_name, data_type, character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_name IN ('channel', 'channel_id', 'channel_name', 'channel_id_snowflake')
            ORDER BY table_name, column_name
            """
        )
        result = await session.execute(query)
        columns = result.fetchall()

        for table_name, column_name, data_type, max_length in columns:
            # Sample values to detect mixed formats
            sample_query = text(
                f"""
                SELECT DISTINCT "{column_name}"
                FROM "{table_name}"
                LIMIT 100
                """
            )
            sample_result = await session.execute(sample_query)
            sample_values = [row[0] for row in sample_result.fetchall() if row[0]]

            # Detect format
            snowflake_pattern = re.compile(r"^[0-9]{18,20}$")
            has_snowflakes = any(snowflake_pattern.match(str(v)) for v in sample_values)
            has_text = any(not snowflake_pattern.match(str(v)) for v in sample_values)

            format_detected = "unknown"
            if has_snowflakes and has_text:
                format_detected = "mixed"
            elif has_snowflakes:
                format_detected = "snowflake_string"
            elif has_text:
                format_detected = "text_slug"

            issue = None
            if format_detected == "mixed":
                issue = "Mixed snowflake and text values in same column"

            findings.append(
                {
                    "location": "database",
                    "table": table_name,
                    "field": column_name,
                    "type": f"{data_type}({max_length})" if max_length else data_type,
                    "format_detected": format_detected,
                    "sample_count": len(sample_values),
                    "issue": issue,
                    "recommendation": (
                        "Migrate to channel_id_snowflake column"
                        if issue or column_name == "channel"
                        else None
                    ),
                }
            )

        # Check for missing indexes on FK columns
        index_query = text(
            """
            SELECT
                t.relname AS table_name,
                a.attname AS column_name
            FROM pg_class t
            JOIN pg_attribute a ON a.attrelid = t.oid
            LEFT JOIN pg_index i ON i.indrelid = t.oid
                AND a.attnum = ANY(i.indkey)
            WHERE t.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
              AND a.attname IN ('channel', 'channel_id', 'channel_id_snowflake')
              AND i.indrelid IS NULL
              AND NOT a.attisdropped
            """
        )
        index_result = await session.execute(index_query)
        missing_indexes = index_result.fetchall()

        for table_name, column_name in missing_indexes:
            findings.append(
                {
                    "location": "database",
                    "table": table_name,
                    "field": column_name,
                    "type": "index_missing",
                    "format_detected": "n/a",
                    "sample_count": 0,
                    "issue": f"Foreign key {column_name} lacks index",
                    "recommendation": f"CREATE INDEX ix_{table_name}_{column_name} ON {table_name}({column_name})",
                }
            )

    finally:
        await session.close()

    return findings


def scan_code_references() -> list[dict[str, Any]]:
    """Scan code files for channel-related references using ripgrep."""
    findings = []

    # Patterns to search for
    pattern = r"channel_id|channel_name|channel[^_]"

    # Directories to scan
    scan_dirs = [
        "apps/api/src/routes/",
        "services/discord-ingestion/src/",
        "shared/discord_utils/",
        "agents/backtesting/tools/",
        "services/connector-manager/src/connectors/",
    ]

    try:
        # Use ripgrep if available
        cmd = ["rg", pattern, "--no-heading", "--line-number", "--color=never"]
        for d in scan_dirs:
            full_path = REPO_ROOT / d
            if full_path.exists():
                cmd.append(str(full_path))

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                # Parse rg output: path:line:content
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    file_path, line_num, content = parts
                    rel_path = Path(file_path).relative_to(REPO_ROOT)
                    findings.append(
                        {
                            "location": "code",
                            "file": str(rel_path),
                            "line": int(line_num),
                            "content": content.strip()[:100],
                            "issue": None,
                            "recommendation": None,
                        }
                    )
        elif result.returncode == 1:
            # No matches found (not an error)
            pass
        else:
            # Fallback to Python glob + regex if ripgrep fails
            findings.extend(_fallback_code_scan(scan_dirs, pattern))

    except (subprocess.TimeoutExpired, FileNotFoundError):
        # Fallback if ripgrep not available
        findings.extend(_fallback_code_scan(scan_dirs, pattern))

    return findings


def _fallback_code_scan(scan_dirs: list[str], pattern: str) -> list[dict[str, Any]]:
    """Fallback code scanning using Python glob and regex."""
    findings = []
    regex = re.compile(pattern)

    for d in scan_dirs:
        full_path = REPO_ROOT / d
        if not full_path.exists():
            continue

        for py_file in full_path.rglob("*.py"):
            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, start=1):
                        if regex.search(line):
                            rel_path = py_file.relative_to(REPO_ROOT)
                            findings.append(
                                {
                                    "location": "code",
                                    "file": str(rel_path),
                                    "line": line_num,
                                    "content": line.strip()[:100],
                                    "issue": None,
                                    "recommendation": None,
                                }
                            )
            except Exception:
                continue

    return findings


def scan_config_files() -> list[dict[str, Any]]:
    """Scan config files for channel references."""
    findings = []

    config_files = [
        ".env.example",
        "docker-compose.yml",
        "agents/backtesting/CLAUDE.md",
    ]

    pattern = re.compile(r"channel_id|channel_name|CHANNEL")

    for config_file in config_files:
        file_path = REPO_ROOT / config_file
        if not file_path.exists():
            continue

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    if pattern.search(line):
                        findings.append(
                            {
                                "location": "config",
                                "file": config_file,
                                "line": line_num,
                                "content": line.strip()[:100],
                                "issue": None,
                                "recommendation": None,
                            }
                        )
        except Exception:
            continue

    return findings


def scan_dashboard_types() -> list[dict[str, Any]]:
    """Scan TypeScript files in dashboard for channel types."""
    findings = []

    ts_dirs = [
        "apps/dashboard/src/types/",
        "apps/dashboard/src/pages/",
    ]

    pattern = re.compile(r"channel.*:|channelId|channelName")

    for ts_dir in ts_dirs:
        dir_path = REPO_ROOT / ts_dir
        if not dir_path.exists():
            continue

        for ts_file in dir_path.rglob("*.ts*"):
            try:
                with open(ts_file, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, start=1):
                        if pattern.search(line):
                            rel_path = ts_file.relative_to(REPO_ROOT)
                            findings.append(
                                {
                                    "location": "dashboard",
                                    "file": str(rel_path),
                                    "line": line_num,
                                    "content": line.strip()[:100],
                                    "issue": None,
                                    "recommendation": None,
                                }
                            )
            except Exception:
                continue

    return findings


async def run_naming_audit(verbose: bool = False) -> dict[str, Any]:
    """Execute naming audit and return structured results."""
    if verbose:
        sys.stderr.write("Starting naming audit...\n")

    # Collect findings from all sources
    if verbose:
        sys.stderr.write("Scanning database schema...\n")
    db_findings = await scan_db_schema()

    if verbose:
        sys.stderr.write("Scanning code references...\n")
    code_findings = scan_code_references()

    if verbose:
        sys.stderr.write("Scanning config files...\n")
    config_findings = scan_config_files()

    if verbose:
        sys.stderr.write("Scanning dashboard TypeScript...\n")
    dashboard_findings = scan_dashboard_types()

    all_findings = db_findings + code_findings + config_findings + dashboard_findings

    # Count issues
    issues_count = sum(1 for f in all_findings if f.get("issue"))

    # Migration plan from architecture doc §6.3
    migration_plan = [
        {
            "step": 1,
            "action": "Add channel_id_snowflake column",
            "sql": "ALTER TABLE channel_messages ADD COLUMN channel_id_snowflake VARCHAR(20);",
        },
        {
            "step": 2,
            "action": "Backfill snowflake values",
            "sql": (
                "UPDATE channel_messages SET channel_id_snowflake = channel "
                "WHERE channel ~ '^[0-9]{18,20}$';"
            ),
        },
        {
            "step": 3,
            "action": "Create index",
            "sql": (
                "CREATE INDEX ix_channel_messages_channel_posted "
                "ON channel_messages(channel_id_snowflake, posted_at);"
            ),
        },
        {
            "step": 4,
            "action": "Update code references",
            "description": (
                "Update all connectors, routes, and dashboard to use channel_id_snowflake. "
                "Verify in staging for 1 week, then drop legacy channel column."
            ),
        },
    ]

    result = {
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "canonical_form": "snowflake_string",
        "total_findings": len(all_findings),
        "issues_count": issues_count,
        "findings": all_findings,
        "migration_plan": migration_plan,
    }

    if verbose:
        sys.stderr.write(f"Audit complete. Found {len(all_findings)} references, {issues_count} issues.\n")

    return result


def print_summary(result: dict[str, Any]) -> None:
    """Print human-readable summary to stderr."""
    sys.stderr.write("\nNaming Audit Summary\n")
    sys.stderr.write("====================\n")
    sys.stderr.write(f"Audit Timestamp: {result['audit_timestamp']}\n")
    sys.stderr.write(f"Canonical Form: {result['canonical_form']}\n")
    sys.stderr.write(f"Total Findings: {result['total_findings']}\n")
    sys.stderr.write(f"Issues Found: {result['issues_count']}\n\n")

    if result["issues_count"] > 0:
        sys.stderr.write("Issues:\n")
        for f in result["findings"]:
            if f.get("issue"):
                location = f.get("table") or f.get("file") or "unknown"
                sys.stderr.write(f"  - {f['location']}/{location}: {f['issue']}\n")
                if f.get("recommendation"):
                    sys.stderr.write(f"    Recommendation: {f['recommendation']}\n")

    sys.stderr.write(f"\nMigration Plan: {len(result['migration_plan'])} steps\n")
    for step in result["migration_plan"]:
        sys.stderr.write(f"  Step {step['step']}: {step['action']}\n")

    sys.stderr.write("\n")


async def main_async(args: argparse.Namespace) -> int:
    """Run naming audit and handle output."""
    try:
        result = await run_naming_audit(verbose=args.verbose)

        # Write JSON output
        if args.output:
            with open(args.output, "w") as f:
                json.dump(result, f, indent=2)
            sys.stderr.write(f"Naming audit results written to {args.output}\n")
        else:
            # Write to stdout if no output file specified
            print(json.dumps(result, indent=2))

        # Print summary
        print_summary(result)

        return 0

    except Exception as e:
        sys.stderr.write(f"ERROR: Naming audit failed: {e}\n")
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 2


def main() -> None:
    """Entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Audit channel naming consistency across DB, code, and config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Path to write JSON results (default: stdout)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print verbose progress to stderr",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
