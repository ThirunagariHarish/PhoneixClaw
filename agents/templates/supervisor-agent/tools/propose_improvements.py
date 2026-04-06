"""Propose improvements for each agent based on performance analysis.

Uses simple rule-based proposals (Claude API integration optional).

Usage:
    python propose_improvements.py --input analysis.json --output improvements.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def propose(analysis: dict) -> dict:
    """Generate concrete improvement proposals per agent."""
    result = {
        "proposed_at": datetime.now(timezone.utc).isoformat(),
        "proposals": [],
    }

    for agent in analysis.get("per_agent", []):
        agent_id = agent.get("agent_id")
        issues = agent.get("issues", [])
        proposals: list[dict] = []

        # Issue: low_win_rate
        if "low_win_rate" in issues:
            avg_conf = agent.get("avg_confidence") or 0.65
            new_threshold = min(avg_conf + 0.10, 0.90)
            proposals.append({
                "type": "raise_confidence_threshold",
                "current": avg_conf,
                "proposed": round(new_threshold, 2),
                "reason": f"Win rate {agent['win_rate']:.0%} too low; raise threshold to filter weaker signals",
                "expected_impact": "Fewer trades, higher quality",
            })

        # Issue: overconfident_misses
        if "overconfident_misses" in issues:
            proposals.append({
                "type": "tighten_pattern_match",
                "current": 2,
                "proposed": 3,
                "reason": "Model confidence is high but win rate is low; require more pattern confirmations",
                "expected_impact": "Catches false positives in high-confidence regime",
            })

        # Issue: significant_loss
        if "significant_loss" in issues:
            proposals.append({
                "type": "tighten_stop_loss",
                "current": 2.0,
                "proposed": 1.5,
                "reason": f"Lost ${agent.get('total_pnl', 0):.2f} today; tighter stop limits drawdown",
                "expected_impact": "Smaller losses per losing trade",
            })

        # Issue: high_rejection_rate
        if "high_rejection_rate" in issues:
            proposals.append({
                "type": "review_risk_chain",
                "current": "default",
                "proposed": "investigate",
                "reason": f"{agent.get('trades_rejected')}/{agent.get('trades_rejected', 0) + agent.get('trades_taken', 0)} rejected — risk chain may be too restrictive",
                "expected_impact": "Capture more valid signals",
            })

        # No issues but low activity → suggest expanding universe
        if not issues and agent.get("trades_taken", 0) < 2:
            proposals.append({
                "type": "expand_universe",
                "current": "default",
                "proposed": "add_2_tickers",
                "reason": "Low trade volume; consider expanding ticker universe",
                "expected_impact": "More trading opportunities",
            })

        if proposals:
            result["proposals"].append({
                "agent_id": agent_id,
                "agent_name": agent.get("name", ""),
                "issues": issues,
                "proposals": proposals[:3],  # Cap at 3 per agent per day
            })

    return result


def main():
    parser = argparse.ArgumentParser(description="Propose improvements")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="improvements.json")
    args = parser.parse_args()

    analysis = json.loads(Path(args.input).read_text())
    result = propose(analysis)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(f"Generated proposals for {len(result['proposals'])} agents → {args.output}")


if __name__ == "__main__":
    main()
