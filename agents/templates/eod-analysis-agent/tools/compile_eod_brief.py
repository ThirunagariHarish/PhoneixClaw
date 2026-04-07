"""Phase 4: Compile the 300-400 word EOD brief via Claude Haiku."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


HAIKU = os.environ.get("EOD_MODEL", "claude-haiku-4-5-20251001")


PROMPT = """You are Phoenix, writing the end-of-day trading analysis for the user.

Today's executed trades (by agent):
{trades}

Missed opportunities (rejected signals that moved favorably):
{missed}

Write a 300-400 word EOD brief with these sections:

## Day's Results
Top 3 performing agents (by realized PnL) and bottom 1-2 laggards. Include exact $ numbers.

## Notable Missed Opportunities
2-3 of the biggest rejected signals with % move and commentary on WHY it was likely rejected (stop-loss? low confidence?).

## Regime Observations
What kind of day was this (trend, chop, vol spike)? Any patterns across agents?

## Tomorrow's Focus
One-line watchlist recommendation.

Rules:
- Plain text, no markdown headers beyond the 4 above
- ALL-CAPS ticker symbols
- Direct and trader-friendly
- Max 400 words total
- End with one bottom-line summary: "Total: N trades, $X realized, $Y potential missed"
"""


def _fallback(trades: dict, missed: dict) -> str:
    lines = [f"# Phoenix EOD Analysis — {trades.get('date', '')}", ""]
    lines.append("## Day's Results")
    for a in (trades.get("per_agent") or [])[:5]:
        lines.append(
            f"- {a['name']}: {a['count']} trades, ${a['pnl']:+.2f} "
            f"({a['winners']}W / {a['losers']}L)"
        )
    lines.append("")
    lines.append("## Notable Missed Opportunities")
    for m in (missed.get("missed_signals") or [])[:3]:
        lines.append(
            f"- {m['ticker']} {m['direction']}: ran {m['best_pct']:+.2f}% post-rejection"
        )
    lines.append("")
    lines.append(
        f"Total: {trades.get('total_trades', 0)} trades, "
        f"${trades.get('total_pnl', 0):+.2f} realized, "
        f"{missed.get('missed_count', 0)} missed opportunities"
    )
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--trades", required=True)
    p.add_argument("--missed", required=True)
    p.add_argument("--output", default="brief.txt")
    args = p.parse_args()

    trades = json.loads(Path(args.trades).read_text()) if Path(args.trades).exists() else {}
    missed = json.loads(Path(args.missed).read_text()) if Path(args.missed).exists() else {}

    key = os.environ.get("ANTHROPIC_API_KEY")
    brief: str | None = None
    if key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            resp = client.messages.create(
                model=HAIKU,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": PROMPT.format(
                        trades=json.dumps(trades, default=str)[:5000],
                        missed=json.dumps(missed, default=str)[:3000],
                    ),
                }],
            )
            brief = resp.content[0].text.strip()
        except Exception as exc:
            print(f"[compile] Haiku call failed: {exc}", file=sys.stderr)

    if not brief:
        brief = _fallback(trades, missed)

    Path(args.output).write_text(brief)
    print(f"[compile] wrote {len(brief)} chars to {args.output}")


if __name__ == "__main__":
    main()
