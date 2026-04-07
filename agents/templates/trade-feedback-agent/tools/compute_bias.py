"""Phase 1: Compute rolling SL/TP/slippage bias multipliers per agent.

Ported from apps/api/src/services/trade_outcome_feedback.py (now deleted).
Talks to the Phoenix API instead of importing DB models directly so this
tool can run inside any Claude Code session.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


MIN_SAMPLES = 30
SIGNIFICANT_DEVIATION = 0.10


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--output", default="bias.json")
    args = p.parse_args()

    import httpx
    base = os.environ.get("PHOENIX_API_URL", "http://localhost:8011")
    key = os.environ.get("PHOENIX_API_KEY", "")
    headers = {"X-Agent-Key": key} if key else {}

    # Phoenix-side helper endpoint returns raw rows: if it doesn't exist we
    # fall back to an admin SQL execution via /api/v2/admin/sql (if available).
    result_per_agent: dict[str, dict] = {}

    try:
        r = httpx.get(
            f"{base}/api/v2/admin/trade-outcomes?days={args.days}",
            headers=headers, timeout=30,
        )
        if r.status_code == 200:
            payload = r.json()
            result_per_agent = _compute_from_rows(payload.get("per_agent") or {})
        else:
            print(f"[compute_bias] /trade-outcomes returned {r.status_code} — skipping",
                  file=sys.stderr)
    except Exception as exc:
        print(f"[compute_bias] fetch failed: {exc}", file=sys.stderr)

    Path(args.output).write_text(json.dumps({
        "days": args.days,
        "min_samples": MIN_SAMPLES,
        "significant_deviation": SIGNIFICANT_DEVIATION,
        "per_agent": result_per_agent,
    }, indent=2, default=str))
    print(f"[compute_bias] {len(result_per_agent)} agents with significant bias")


def _compute_from_rows(per_agent: dict) -> dict[str, dict]:
    """Given per_agent = {agent_id: [row, row, ...]}, compute bias dicts."""
    out: dict[str, dict] = {}
    for agent_id, rows in per_agent.items():
        if not isinstance(rows, list) or len(rows) < MIN_SAMPLES:
            continue

        def _mean_ratio(numer_key: str, denom_key: str) -> float | None:
            ratios = []
            for r in rows:
                n = r.get(numer_key)
                d = r.get(denom_key)
                if n is None or d is None or d == 0:
                    continue
                try:
                    ratios.append(float(n) / float(d))
                except Exception:
                    continue
            if len(ratios) < MIN_SAMPLES:
                return None
            return sum(ratios) / len(ratios)

        sl = _mean_ratio("actual_mae_atr", "predicted_sl_mult")
        tp = _mean_ratio("actual_mfe_atr", "predicted_tp_mult")
        slip = _mean_ratio("actual_slip_bps", "predicted_slip_bps")

        bias: dict[str, float] = {}
        if sl is not None and abs(sl - 1.0) > SIGNIFICANT_DEVIATION:
            bias["sl_bias"] = round(sl, 3)
        if tp is not None and abs(tp - 1.0) > SIGNIFICANT_DEVIATION:
            bias["tp_bias"] = round(tp, 3)
        if slip is not None and abs(slip - 1.0) > SIGNIFICANT_DEVIATION:
            bias["slip_bias"] = round(slip, 3)
        if bias:
            out[agent_id] = bias
    return out


if __name__ == "__main__":
    main()
