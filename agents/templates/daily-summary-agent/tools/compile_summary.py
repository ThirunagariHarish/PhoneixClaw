"""Phase 2: Compile a 1-2 paragraph daily summary using Claude Haiku."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


HAIKU = os.environ.get("DAILY_SUMMARY_MODEL", "claude-haiku-4-5-20251001")


PROMPT = """You are Phoenix, writing a short daily recap for an active trader.

Today's raw per-agent PnL data (JSON):
{data}

Write a 1-2 paragraph summary (max 250 words) that:
- Highlights the best and worst performing agents by name
- Calls out unusual activity (huge wins, big losses, low volume)
- Ends with a one-line bottom line: "Total: X trades, $Y.YY"

Rules:
- Plain text, no markdown headers
- ALL-CAPS ticker symbols if you mention any
- Direct and trader-friendly
- If total_trades == 0, write "Quiet day — no trades executed."
"""


def _fallback(data: dict) -> str:
    trades = data.get("trades") or []
    total_pnl = data.get("total_pnl", 0)
    total_trades = data.get("total_trades", 0)
    if total_trades == 0:
        return "Quiet day — no trades executed."
    lines = [f"Daily Summary — {data.get('date', '')}", ""]
    for t in trades[:10]:
        lines.append(f"• {t['name']}: {t['count']} trades, ${t['pnl']:+.2f}")
    lines.append("")
    lines.append(f"Total: {total_trades} trades, ${total_pnl:+.2f}")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="summary.txt")
    args = p.parse_args()

    data = json.loads(Path(args.input).read_text())

    key = os.environ.get("ANTHROPIC_API_KEY")
    summary: str | None = None
    if key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            resp = client.messages.create(
                model=HAIKU,
                max_tokens=512,
                messages=[{"role": "user", "content": PROMPT.format(data=json.dumps(data))}],
            )
            summary = resp.content[0].text.strip()
        except Exception as exc:
            print(f"[compile] Haiku call failed: {exc}", file=sys.stderr)

    if not summary:
        summary = _fallback(data)

    Path(args.output).write_text(summary)
    print(f"[compile] wrote {len(summary)} chars to {args.output}")


if __name__ == "__main__":
    main()
