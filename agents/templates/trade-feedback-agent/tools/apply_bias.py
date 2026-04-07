"""Phase 2: Write per-agent bias_multipliers.json + post summary briefing."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="applied.json")
    args = p.parse_args()

    bias_doc = json.loads(Path(args.input).read_text())
    per_agent = bias_doc.get("per_agent") or {}

    data_root = Path(
        os.environ.get("PHOENIX_AGENTS_DIR", "/app/data/agents/live")
    )
    applied: list[dict] = []
    warnings: list[dict] = []

    for agent_id, bias in per_agent.items():
        agent_dir = data_root / agent_id
        if not agent_dir.exists():
            print(f"[apply] workdir missing for {agent_id}, skipping", file=sys.stderr)
            continue

        models_dir = agent_dir / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        out = models_dir / "bias_multipliers.json"

        try:
            existing = json.loads(out.read_text()) if out.exists() else {}
        except Exception:
            existing = {}
        existing.update(bias)
        out.write_text(json.dumps(existing, indent=2))

        applied.append({"agent_id": agent_id, "bias": bias})

        # Flag significant drift
        for k in ("sl_bias", "tp_bias"):
            v = bias.get(k)
            if v is not None and (v > 1.2 or v < 0.8):
                warnings.append({
                    "agent_id": agent_id,
                    "field": k,
                    "value": v,
                    "note": "significant drift — investigate",
                })

    result = {
        "applied_count": len(applied),
        "applied": applied,
        "warnings": warnings,
    }
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(f"[apply] updated {len(applied)} agents, {len(warnings)} warnings")

    # Post a briefing row so the dashboard can see it
    try:
        import httpx
        base = os.environ.get("PHOENIX_API_URL", "http://localhost:8011")
        key = os.environ.get("PHOENIX_API_KEY", "")
        headers = {"X-Agent-Key": key, "Content-Type": "application/json"}

        body_lines = ["# Trade Feedback — Daily Bias Correction", ""]
        if applied:
            for a in applied:
                bias = a["bias"]
                body_lines.append(
                    f"- {a['agent_id'][:8]}: " +
                    ", ".join(f"{k}={v}" for k, v in bias.items())
                )
        else:
            body_lines.append("No agents had significant bias deviations (quiet night).")
        if warnings:
            body_lines.append("")
            body_lines.append("⚠ Drift warnings:")
            for w in warnings:
                body_lines.append(
                    f"- {w['agent_id'][:8]} {w['field']}={w['value']} ({w['note']})"
                )

        payload = {
            "kind": "trade_feedback",
            "title": "Phoenix Trade Feedback — Nightly Bias Update",
            "body": "\n".join(body_lines),
            "data": result,
            "agents_woken": len(applied),
            "dispatched_to": ["ws", "db"],
        }
        r = httpx.post(f"{base}/api/v2/briefings", headers=headers,
                       json=payload, timeout=15)
        if r.status_code in (200, 201):
            print(f"[apply] persisted briefing id={r.json().get('id')}")
    except Exception as exc:
        print(f"[apply] briefing persist skipped: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
