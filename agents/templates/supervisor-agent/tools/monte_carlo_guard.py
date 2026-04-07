"""P16: Monte Carlo guard — bootstrap trade-shuffle simulation.

Given a list of recent trade PnLs, simulates 100 alternative orderings and
rejects the staged change if ANY path drops equity more than `max_dd_cap`.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path


def bootstrap_paths(pnls: list[float], n_paths: int = 100,
                    starting_capital: float = 100_000.0) -> list[dict]:
    results = []
    for _ in range(n_paths):
        shuffled = pnls.copy()
        random.shuffle(shuffled)
        equity = starting_capital
        peak = equity
        dd_worst = 0.0
        for p in shuffled:
            equity += p
            peak = max(peak, equity)
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > dd_worst:
                    dd_worst = dd
        results.append({
            "final_equity": equity,
            "max_drawdown": dd_worst,
            "total_return": (equity - starting_capital) / starting_capital,
        })
    return results


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--trades", required=True, help="JSON file with pnl list")
    p.add_argument("--output", required=True)
    p.add_argument("--max-dd-cap", type=float, default=0.10)
    p.add_argument("--n-paths", type=int, default=100)
    args = p.parse_args()

    data = json.loads(Path(args.trades).read_text())
    if isinstance(data, dict):
        pnls = data.get("pnls") or [t.get("pnl_dollar", 0) for t in data.get("trades", [])]
    else:
        pnls = data
    pnls = [float(p) for p in pnls if p is not None]

    if not pnls:
        Path(args.output).write_text(json.dumps({"approved": False, "reason": "no_trades"}))
        return

    paths = bootstrap_paths(pnls, n_paths=args.n_paths)
    worst_dd = max(r["max_drawdown"] for r in paths)
    p5_dd = sorted([r["max_drawdown"] for r in paths])[int(len(paths) * 0.95)]
    approved = worst_dd < args.max_dd_cap
    out = {
        "approved": approved,
        "worst_dd": round(worst_dd, 4),
        "p95_dd": round(p5_dd, 4),
        "max_dd_cap": args.max_dd_cap,
        "mean_return": round(sum(r["total_return"] for r in paths) / len(paths), 4),
        "paths_checked": len(paths),
    }
    Path(args.output).write_text(json.dumps(out, indent=2))
    print(json.dumps(out))


if __name__ == "__main__":
    main()
