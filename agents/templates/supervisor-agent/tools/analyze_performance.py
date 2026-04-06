"""Analyze daily performance per agent and per pattern.

Usage:
    python analyze_performance.py --input daily_data.json --output analysis.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def analyze(daily_data: dict) -> dict:
    """Compute per-agent and per-pattern metrics."""
    result = {
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "date": daily_data.get("date", ""),
        "per_agent": [],
        "summary": {
            "total_agents": 0,
            "total_trades": 0,
            "total_wins": 0,
            "total_losses": 0,
            "overall_win_rate": 0.0,
        },
    }

    agents = daily_data.get("agents", [])
    result["summary"]["total_agents"] = len(agents)

    total_wins = 0
    total_losses = 0
    total_trades = 0

    for agent in agents:
        trades = agent.get("trades", [])
        n_trades = len(trades)
        if n_trades == 0 and agent.get("paper_count", 0) == 0:
            # Idle agent — skip
            continue

        wins = 0
        losses = 0
        total_pnl = 0.0
        confidences = []
        rejected_count = 0

        for t in trades:
            decision = t.get("decision_status", "accepted")
            if decision == "rejected":
                rejected_count += 1
                continue
            pnl = t.get("pnl_dollar", 0) or 0
            total_pnl += pnl
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
            conf = t.get("model_confidence")
            if conf is not None:
                confidences.append(conf)

        avg_conf = sum(confidences) / len(confidences) if confidences else None
        win_rate = wins / max(wins + losses, 1)

        agent_metrics = {
            "agent_id": agent.get("id"),
            "name": agent.get("name", ""),
            "type": agent.get("type", ""),
            "trades_taken": n_trades - rejected_count,
            "trades_rejected": rejected_count,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 3),
            "total_pnl": round(total_pnl, 2),
            "avg_confidence": round(avg_conf, 3) if avg_conf is not None else None,
            "paper_count": agent.get("paper_count", 0),
            "paper_realized_pnl": agent.get("paper_realized_pnl", 0),
            "issues": [],
        }

        # Diagnose issues
        if win_rate < 0.40 and (wins + losses) >= 5:
            agent_metrics["issues"].append("low_win_rate")
        if rejected_count > n_trades * 0.5:
            agent_metrics["issues"].append("high_rejection_rate")
        if avg_conf and avg_conf > 0.85 and win_rate < 0.50:
            agent_metrics["issues"].append("overconfident_misses")
        if total_pnl < -100:
            agent_metrics["issues"].append("significant_loss")

        result["per_agent"].append(agent_metrics)
        total_wins += wins
        total_losses += losses
        total_trades += n_trades

    result["summary"]["total_trades"] = total_trades
    result["summary"]["total_wins"] = total_wins
    result["summary"]["total_losses"] = total_losses
    result["summary"]["overall_win_rate"] = round(total_wins / max(total_wins + total_losses, 1), 3)

    return result


def main():
    parser = argparse.ArgumentParser(description="Analyze daily performance")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="analysis.json")
    args = parser.parse_args()

    daily_data = json.loads(Path(args.input).read_text())
    result = analyze(daily_data)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(f"Analyzed {len(result['per_agent'])} active agents → {args.output}")
    print(f"  Overall win rate: {result['summary']['overall_win_rate']:.1%}")


if __name__ == "__main__":
    main()
