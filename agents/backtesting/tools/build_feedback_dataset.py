"""Build a feedback dataset from trade_signals for the next retraining cycle.

Pulls the last N days of trade signals from Phoenix API and produces a
`feedback_dataset.parquet` that the preprocess step can concatenate into
training data. Missed profitable trades are weighted higher to correct the
false-negative bias.

Usage:
    python build_feedback_dataset.py \
        --agent-id <uuid> \
        --days 30 \
        --output output/feedback_dataset.parquet
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _api_config() -> dict:
    cfg_path = Path("config.json")
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            return {
                "url": cfg.get("phoenix_api_url") or os.getenv("PHOENIX_API_URL", ""),
                "key": cfg.get("phoenix_api_key", ""),
            }
        except Exception:
            pass
    return {
        "url": os.getenv("PHOENIX_API_URL", ""),
        "key": os.getenv("PHOENIX_API_KEY", ""),
    }


def fetch_signals(agent_id: str, days: int = 30) -> list[dict]:
    """Fetch trade signals from Phoenix API."""
    api = _api_config()
    if not api["url"]:
        print("  [feedback] No API URL configured", file=sys.stderr)
        return []

    try:
        import httpx
        resp = httpx.get(
            f"{api['url']}/api/v2/trade-signals",
            headers={"X-Agent-Key": api["key"]},
            params={"agent_id": agent_id, "days": days, "limit": 1000},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        print(f"  [feedback] API returned {resp.status_code}", file=sys.stderr)
    except Exception as exc:
        print(f"  [feedback] Fetch failed: {exc}", file=sys.stderr)
    return []


def build_dataset(signals: list[dict]) -> dict:
    """Convert signals into a labeled training dataset.

    Rules:
    - `executed` + realized_pnl_pct > 0 → label=1 (positive example, weight=1.0)
    - `executed` + realized_pnl_pct < 0 → label=0 (negative example, weight=1.0)
    - `rejected` + was_missed_opportunity=True → label=1 (FALSE NEGATIVE, weight=2.0)
    - `rejected` + realized_pnl_pct < 0 → label=0 (correct rejection, weight=0.5)
    - `watchlist` / `paper` are tracked but not used for retraining

    Returns a dict with counts and the rows ready for parquet.
    """
    rows = []
    stats = {
        "executed_wins": 0, "executed_losses": 0,
        "correct_rejections": 0, "missed_opportunities": 0,
        "skipped_no_outcome": 0, "watchlist": 0, "paper": 0,
    }

    for s in signals:
        decision = s.get("decision", "")
        pnl = s.get("realized_pnl_pct")
        missed = s.get("was_missed_opportunity", False)

        if decision == "executed":
            if pnl is None:
                stats["skipped_no_outcome"] += 1
                continue
            label = 1 if pnl > 0 else 0
            weight = 1.0
            if label == 1:
                stats["executed_wins"] += 1
            else:
                stats["executed_losses"] += 1
        elif decision == "rejected":
            if missed:
                # False negative — should have traded
                label = 1
                weight = 2.0
                stats["missed_opportunities"] += 1
            elif pnl is not None and pnl < 0:
                # Correct rejection — market moved against, downweight
                label = 0
                weight = 0.5
                stats["correct_rejections"] += 1
            else:
                # Can't label (neutral outcome or no data)
                stats["skipped_no_outcome"] += 1
                continue
        elif decision == "watchlist":
            stats["watchlist"] += 1
            continue
        elif decision == "paper":
            stats["paper"] += 1
            continue
        else:
            continue

        row = {
            "ticker": s.get("ticker"),
            "direction": s.get("direction"),
            "decision": decision,
            "label": label,
            "weight": weight,
            "realized_pnl_pct": pnl,
            "created_at": s.get("created_at"),
        }
        # Flatten features into the row
        # (Features are fetched from the API in the `features` dict if available;
        # the list endpoint doesn't include them by default, so we'd need a separate fetch.
        # For now we include what we have.)
        rows.append(row)

    return {"rows": rows, "stats": stats}


def main():
    parser = argparse.ArgumentParser(description="Build feedback dataset for retraining")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--output", default="feedback_dataset.parquet")
    args = parser.parse_args()

    signals = fetch_signals(args.agent_id, args.days)
    print(f"  Fetched {len(signals)} signals over {args.days} days")

    result = build_dataset(signals)
    stats = result["stats"]

    print(f"  Dataset stats: {json.dumps(stats, indent=2)}")

    rows = result["rows"]
    if not rows:
        print("  No labeled rows to write — skipping output")
        return

    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(output_path, index=False)
        print(f"  Wrote {len(df)} labeled rows to {output_path}")
    except ImportError:
        # Fall back to JSON
        output_path = Path(args.output).with_suffix(".json")
        output_path.write_text(json.dumps(rows, indent=2, default=str))
        print(f"  pandas not available — wrote {len(rows)} rows to {output_path}")

    # Also write a summary for auditing
    summary_path = Path(args.output).with_suffix(".summary.json")
    summary_path.write_text(json.dumps({
        "agent_id": args.agent_id,
        "days": args.days,
        "signals_fetched": len(signals),
        "rows_written": len(rows),
        "stats": stats,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    print(f"  Summary written to {summary_path}")


if __name__ == "__main__":
    main()
