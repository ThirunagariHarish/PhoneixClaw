"""Cleanup the data/ directory.

Phase H4 retention rules:
- Keep only the LAST 3 backtest versions per agent (older versions deleted)
- Delete supervisor runs older than 7 days
- Delete position sub-agent dirs older than 7 days (positions are closed by then)
- Delete orphan working dirs (agent no longer exists in DB)

Run from the nightly_retention scheduler job. Safe to run repeatedly.

Usage:
    python scripts/cleanup_data_dir.py [--dry-run] [--data-dir /app/data]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def cleanup_backtest_versions(agent_dir: Path, keep: int = 3, dry_run: bool = False) -> int:
    """Keep only the last `keep` versions per agent. Returns bytes freed."""
    output_dir = agent_dir / "output"
    if not output_dir.exists():
        return 0

    versions = []
    for child in output_dir.iterdir():
        if child.is_dir() and child.name.startswith("v"):
            try:
                v_num = int(child.name[1:])
                versions.append((v_num, child))
            except ValueError:
                continue

    if len(versions) <= keep:
        return 0

    versions.sort(key=lambda x: x[0], reverse=True)
    to_delete = versions[keep:]
    bytes_freed = 0

    for v_num, path in to_delete:
        size = _dir_size(path)
        bytes_freed += size
        if dry_run:
            logger.info("[DRY] Would delete backtest %s (%.1f MB)", path, size / 1024 / 1024)
        else:
            try:
                shutil.rmtree(path)
                logger.info("Deleted backtest %s (%.1f MB)", path, size / 1024 / 1024)
            except Exception as exc:
                logger.warning("Failed to delete %s: %s", path, exc)

    return bytes_freed


def cleanup_supervisor_runs(supervisor_dir: Path, days: int = 7, dry_run: bool = False) -> int:
    """Delete supervisor run directories older than `days` days."""
    if not supervisor_dir.exists():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    bytes_freed = 0

    for child in supervisor_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            mtime = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            size = _dir_size(child)
            bytes_freed += size
            if dry_run:
                logger.info("[DRY] Would delete supervisor %s (%.1f MB)", child, size / 1024 / 1024)
            else:
                try:
                    shutil.rmtree(child)
                    logger.info("Deleted supervisor %s (%.1f MB)", child, size / 1024 / 1024)
                except Exception as exc:
                    logger.warning("Failed to delete %s: %s", child, exc)

    return bytes_freed


def cleanup_position_subagents(agent_dir: Path, days: int = 7, dry_run: bool = False) -> int:
    """Delete position sub-agent dirs older than `days` days."""
    positions_dir = agent_dir / "positions"
    if not positions_dir.exists():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    bytes_freed = 0

    for child in positions_dir.iterdir():
        if not child.is_dir():
            continue

        # Check the position's status from position.json — only delete if closed
        pos_file = child / "position.json"
        try:
            data = json.loads(pos_file.read_text()) if pos_file.exists() else {}
            if data.get("status") != "closed":
                continue
        except Exception:
            pass

        try:
            mtime = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            size = _dir_size(child)
            bytes_freed += size
            if dry_run:
                logger.info("[DRY] Would delete sub-agent %s (%.1f MB)", child, size / 1024 / 1024)
            else:
                try:
                    shutil.rmtree(child)
                    logger.info("Deleted sub-agent %s (%.1f MB)", child, size / 1024 / 1024)
                except Exception as exc:
                    logger.warning("Failed to delete %s: %s", child, exc)

    return bytes_freed


def cleanup_orphan_dirs(data_dir: Path, valid_agent_ids: set[str], dry_run: bool = False) -> int:
    """Delete agent dirs whose agent_id no longer exists in the DB."""
    bytes_freed = 0

    for prefix in ("backtest_", "live_agents/"):
        if prefix == "live_agents/":
            parent = data_dir / "live_agents"
            if not parent.exists():
                continue
            for child in parent.iterdir():
                if child.is_dir() and child.name not in valid_agent_ids:
                    size = _dir_size(child)
                    bytes_freed += size
                    if dry_run:
                        logger.info("[DRY] Would delete orphan %s (%.1f MB)", child, size / 1024 / 1024)
                    else:
                        try:
                            shutil.rmtree(child)
                            logger.info("Deleted orphan %s", child)
                        except Exception as exc:
                            logger.warning("Failed to delete orphan %s: %s", child, exc)
        else:
            for child in data_dir.iterdir():
                if child.is_dir() and child.name.startswith(prefix):
                    agent_id = child.name[len(prefix):]
                    if agent_id not in valid_agent_ids:
                        size = _dir_size(child)
                        bytes_freed += size
                        if dry_run:
                            logger.info("[DRY] Would delete orphan %s (%.1f MB)", child, size / 1024 / 1024)
                        else:
                            try:
                                shutil.rmtree(child)
                                logger.info("Deleted orphan %s", child)
                            except Exception as exc:
                                logger.warning("Failed to delete orphan %s: %s", child, exc)

    return bytes_freed


def _dir_size(path: Path) -> int:
    """Recursive directory size in bytes."""
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += _dir_size(Path(entry.path))
            except OSError:
                continue
    except OSError:
        pass
    return total


async def run_cleanup(data_dir: str = "/app/data", dry_run: bool = False) -> dict:
    """Main entrypoint, called from the nightly_retention scheduler job."""
    base = Path(data_dir)
    if not base.exists():
        return {"error": f"data dir {data_dir} not found", "bytes_freed": 0}

    summary = {
        "data_dir": str(base),
        "dry_run": dry_run,
        "bytes_freed": 0,
        "details": {},
    }

    # 1. Backtest version cleanup (per agent)
    for child in base.iterdir():
        if child.is_dir() and child.name.startswith("backtest_"):
            freed = cleanup_backtest_versions(child, keep=3, dry_run=dry_run)
            summary["bytes_freed"] += freed
            summary["details"].setdefault("backtest_versions", 0)
            summary["details"]["backtest_versions"] += freed

    # 2. Supervisor run cleanup
    sup_dir = base / "supervisor"
    if sup_dir.exists():
        freed = cleanup_supervisor_runs(sup_dir, days=7, dry_run=dry_run)
        summary["bytes_freed"] += freed
        summary["details"]["supervisor_runs"] = freed

    # 3. Position sub-agent cleanup (per live agent)
    live_dir = base / "live_agents"
    if live_dir.exists():
        for agent_dir in live_dir.iterdir():
            if agent_dir.is_dir():
                freed = cleanup_position_subagents(agent_dir, days=7, dry_run=dry_run)
                summary["bytes_freed"] += freed
                summary["details"].setdefault("position_subagents", 0)
                summary["details"]["position_subagents"] += freed

    # 4. Orphan agent dir cleanup (requires DB query)
    try:
        from sqlalchemy import select
        from shared.db.engine import get_session
        from shared.db.models.agent import Agent

        async for db in get_session():
            result = await db.execute(select(Agent.id))
            valid_ids = {str(row[0]) for row in result.all()}

        if valid_ids:
            freed = cleanup_orphan_dirs(base, valid_ids, dry_run=dry_run)
            summary["bytes_freed"] += freed
            summary["details"]["orphan_dirs"] = freed
    except Exception as exc:
        logger.warning("Could not check orphans: %s", exc)
        summary["orphan_check_error"] = str(exc)[:200]

    summary["bytes_freed_mb"] = round(summary["bytes_freed"] / 1024 / 1024, 1)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Cleanup data/ directory")
    parser.add_argument("--data-dir", default="/app/data")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    import asyncio
    summary = asyncio.run(run_cleanup(args.data_dir, args.dry_run))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
