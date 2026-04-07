"""P16: Ensemble conflict resolver — Bayesian-weighted voting.

When two or more agents disagree on the same symbol, this tool computes a
weighted vote by each agent's recent Sharpe ratio and picks a consensus.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def resolve(conflicts: list[dict]) -> list[dict]:
    """Each conflict = {symbol, proposals: [{agent_id, direction, sharpe}]}."""
    resolutions = []
    for c in conflicts:
        props = c.get("proposals", [])
        if len(props) < 2:
            continue
        total_w = sum(max(0.0, float(p.get("sharpe", 0))) for p in props) or 1.0
        tally: dict[str, float] = {}
        for p in props:
            w = max(0.0, float(p.get("sharpe", 0))) / total_w
            tally[p["direction"]] = tally.get(p["direction"], 0) + w
        winner = max(tally.items(), key=lambda kv: kv[1])
        resolutions.append({
            "symbol": c["symbol"],
            "winner_direction": winner[0],
            "winner_weight": round(winner[1], 3),
            "tally": {k: round(v, 3) for k, v in tally.items()},
            "agents": [p["agent_id"] for p in props],
        })
    return resolutions


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--conflicts", required=True, help="JSON file with conflicts list")
    p.add_argument("--output", required=True)
    args = p.parse_args()

    data = json.loads(Path(args.conflicts).read_text())
    conflicts = data if isinstance(data, list) else data.get("conflicts", [])
    resolutions = resolve(conflicts)
    Path(args.output).write_text(json.dumps({"resolutions": resolutions}, indent=2))
    print(json.dumps({"resolved": len(resolutions)}))


if __name__ == "__main__":
    main()
