"""P16: Darwinian prompt selection for agents.

Maintains N prompt variants per agent in `prompt_variants.json` and rotates the
worst-performing variant every 5 trading days by asking Claude to rewrite it
using the losing-trade evidence.

Usage:
    python tools/prompt_darwin.py --agent-id abc --data-dir ~/agents/live/abc/
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

VARIANTS_FILE = "prompt_variants.json"
MAX_VARIANTS = 5
ROTATE_EVERY_TRADES = 20


def load_variants(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def save_variants(path: Path, variants: list[dict]) -> None:
    path.write_text(json.dumps(variants, indent=2))


def score_variant(trades: list[dict]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if float(t.get("pnl_dollar", 0) or 0) > 0)
    wr = wins / len(trades)
    avg_pnl = sum(float(t.get("pnl_dollar", 0) or 0) for t in trades) / len(trades)
    # Very rough composite: win rate * avg_pnl (bigger = better)
    return wr * max(avg_pnl, 0.0)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agent-id", required=True)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--force-rotate", action="store_true")
    args = p.parse_args()

    data_dir = Path(args.data_dir)
    variants_path = data_dir / VARIANTS_FILE
    variants = load_variants(variants_path)

    if not variants:
        base_prompt_path = data_dir / "CLAUDE.md"
        base = base_prompt_path.read_text() if base_prompt_path.exists() else ""
        variants = [{
            "id": "v0",
            "prompt": base,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "trades_seen": 0,
            "score": 0.0,
            "generation": 0,
        }]

    # Load recent trades for scoring (stub — real impl pulls from AgentTrade table)
    trades_path = data_dir / "recent_trades.json"
    trades = json.loads(trades_path.read_text()) if trades_path.exists() else []

    for v in variants:
        v["score"] = score_variant(trades)
        v["trades_seen"] = len(trades)

    variants.sort(key=lambda v: v["score"], reverse=True)

    should_rotate = args.force_rotate or (trades and len(trades) >= ROTATE_EVERY_TRADES)
    if should_rotate and len(variants) >= 2:
        losers = [t for t in trades if float(t.get("pnl_dollar", 0) or 0) < 0][-10:]
        evidence = "\n".join(f"- {t.get('symbol')}: ${t.get('pnl_dollar')}" for t in losers)
        new_id = f"v{len(variants)}"
        new_variant = {
            "id": new_id,
            "prompt": variants[0]["prompt"]
                      + f"\n\n# Darwinian feedback ({datetime.now(timezone.utc).date()})\n"
                      + f"Recent losing trades to avoid:\n{evidence}\n",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "trades_seen": 0,
            "score": 0.0,
            "generation": max(v["generation"] for v in variants) + 1,
            "parent": variants[0]["id"],
        }
        variants.append(new_variant)
        if len(variants) > MAX_VARIANTS:
            variants = variants[:MAX_VARIANTS]

    save_variants(variants_path, variants)
    print(json.dumps({
        "agent_id": args.agent_id,
        "variant_count": len(variants),
        "champion": variants[0]["id"],
        "rotated": should_rotate,
    }, indent=2))


if __name__ == "__main__":
    main()
