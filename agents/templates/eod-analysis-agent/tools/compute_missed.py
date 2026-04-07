"""Phase 3: Flag missed opportunities — rejected signals where the price ran."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="missed.json")
    p.add_argument("--min-pct", type=float, default=1.0,
                   help="Min % favorable move to count as missed")
    args = p.parse_args()

    data = json.loads(Path(args.input).read_text())
    signals = data.get("signals") or []

    missed: list[dict] = []
    per_agent: dict[str, dict] = {}

    for s in signals:
        if (s.get("decision") or "").lower() != "rejected":
            continue
        best_pct = max(
            (s.get("pct_1h") or -999, s.get("pct_4h") or -999, s.get("pct_eod") or -999),
        )
        if best_pct < args.min_pct:
            continue
        missed.append({
            "signal_id": s.get("id"),
            "agent_id": s.get("agent_id"),
            "ticker": s.get("ticker"),
            "direction": s.get("direction"),
            "entry_price": s.get("entry_price"),
            "best_pct": round(best_pct, 2),
            "pct_1h": s.get("pct_1h"),
            "pct_4h": s.get("pct_4h"),
            "pct_eod": s.get("pct_eod"),
        })
        ag = per_agent.setdefault(str(s.get("agent_id")), {
            "agent_id": s.get("agent_id"),
            "missed_count": 0,
            "potential_pct": 0.0,
        })
        ag["missed_count"] += 1
        ag["potential_pct"] += best_pct

    out = {
        "missed_count": len(missed),
        "missed_signals": missed[:50],  # cap payload size
        "per_agent": sorted(per_agent.values(), key=lambda a: a["missed_count"], reverse=True),
    }
    Path(args.output).write_text(json.dumps(out, indent=2, default=str))
    print(f"[missed] {len(missed)} missed opportunities across {len(per_agent)} agents")


if __name__ == "__main__":
    main()
