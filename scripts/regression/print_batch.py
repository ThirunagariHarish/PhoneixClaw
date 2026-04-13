#!/usr/bin/env python3
"""Print tasks for one batch from tests/regression/user_journeys.yaml (for parallel QA / subagents)."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("batch_id", type=int, help="Batch number (see user_journeys.yaml)")
    p.add_argument(
        "--file",
        default="tests/regression/user_journeys.yaml",
        type=Path,
    )
    args = p.parse_args()
    data = yaml.safe_load(args.file.read_text())
    for b in data.get("batches", []):
        if b.get("batch_id") != args.batch_id:
            continue
        print(f"# Batch {b['batch_id']}: {b['name']}")
        for t in b.get("tasks", []):
            print(f"  {t['id']}: {t['title']} → {t.get('route', '')}")
        return
    raise SystemExit(f"No batch_id={args.batch_id}")


if __name__ == "__main__":
    main()
