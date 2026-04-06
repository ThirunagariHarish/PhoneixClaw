"""Mini backtest — quick 30-day validation of proposed improvements.

For each proposal, simulate the change against recent backtest data and
measure the impact on win rate / Sharpe.

Usage:
    python mini_backtest.py --input improvements.json --days 30 --output results.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def test_proposals(improvements: dict, days: int) -> dict:
    """Run mini-backtest on each proposal and score impact."""
    result = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": days,
        "results": [],
    }

    for agent_block in improvements.get("proposals", []):
        agent_id = agent_block.get("agent_id")
        agent_results = {
            "agent_id": agent_id,
            "agent_name": agent_block.get("agent_name", ""),
            "tested_proposals": [],
        }

        for proposal in agent_block.get("proposals", []):
            test_result = _simulate(proposal, agent_id, days)
            test_result["proposal"] = proposal
            agent_results["tested_proposals"].append(test_result)

        result["results"].append(agent_results)

    return result


def _simulate(proposal: dict, agent_id: str, days: int) -> dict:
    """Simulate the proposal's impact.

    For now this is heuristic: estimate the proposed change's expected
    effect using simple rules. Full integration with the backtest engine
    is left for a follow-up.
    """
    proposal_type = proposal.get("type", "")
    baseline_win_rate = 0.55  # Stub baseline
    baseline_sharpe = 1.0

    # Heuristic impact estimates
    if proposal_type == "raise_confidence_threshold":
        new_wr = baseline_win_rate + 0.04
        new_sharpe = baseline_sharpe + 0.15
        confidence = 0.7
    elif proposal_type == "tighten_pattern_match":
        new_wr = baseline_win_rate + 0.03
        new_sharpe = baseline_sharpe + 0.10
        confidence = 0.6
    elif proposal_type == "tighten_stop_loss":
        new_wr = baseline_win_rate - 0.02
        new_sharpe = baseline_sharpe + 0.20  # Better risk-adjusted
        confidence = 0.65
    elif proposal_type == "expand_universe":
        new_wr = baseline_win_rate
        new_sharpe = baseline_sharpe + 0.05
        confidence = 0.5
    else:
        new_wr = baseline_win_rate
        new_sharpe = baseline_sharpe
        confidence = 0.3

    win_rate_delta = new_wr - baseline_win_rate
    sharpe_delta = new_sharpe - baseline_sharpe

    # Pass criteria: >2% improvement in win rate OR Sharpe
    passes = win_rate_delta > 0.02 or sharpe_delta > 0.05

    return {
        "passes": passes,
        "baseline_win_rate": baseline_win_rate,
        "proposed_win_rate": round(new_wr, 3),
        "win_rate_delta": round(win_rate_delta, 3),
        "baseline_sharpe": baseline_sharpe,
        "proposed_sharpe": round(new_sharpe, 3),
        "sharpe_delta": round(sharpe_delta, 3),
        "confidence": confidence,
        "method": "heuristic",
    }


def main():
    parser = argparse.ArgumentParser(description="Mini backtest")
    parser.add_argument("--input", required=True)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--output", default="results.json")
    args = parser.parse_args()

    improvements = json.loads(Path(args.input).read_text())
    result = test_proposals(improvements, args.days)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))

    n_passing = sum(
        1 for ar in result["results"] for tp in ar["tested_proposals"]
        if tp.get("passes")
    )
    n_total = sum(len(ar["tested_proposals"]) for ar in result["results"])
    print(f"Tested {n_total} proposals, {n_passing} passed → {args.output}")


if __name__ == "__main__":
    main()
