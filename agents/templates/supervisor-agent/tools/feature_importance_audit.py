"""P16: Feature-importance audit — detects regime drift.

Compares the top-10 features from the current explainability.json against a
30-day-old snapshot. If more than 30% of the top-10 have shifted rank, emits
a signal to retrigger llm_pattern_discovery.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def top_features(path: Path, k: int = 10) -> list[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        feats = data.get("top_features", [])
        return [f.get("feature", "") for f in feats[:k]]
    except Exception:
        return []


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--current", required=True)
    p.add_argument("--baseline", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    cur = top_features(Path(args.current))
    base = top_features(Path(args.baseline))
    if not cur or not base:
        Path(args.output).write_text(json.dumps({
            "retrain_needed": False,
            "reason": "missing_explainability",
        }))
        return

    shared = set(cur) & set(base)
    shift_pct = 1.0 - (len(shared) / max(len(cur), 1))
    retrain = shift_pct > 0.30
    result = {
        "retrain_needed": retrain,
        "shift_pct": round(shift_pct, 3),
        "current_top10": cur,
        "baseline_top10": base,
        "shared_features": sorted(shared),
    }
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
