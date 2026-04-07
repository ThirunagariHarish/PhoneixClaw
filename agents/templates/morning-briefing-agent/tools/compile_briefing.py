"""Phase 2: Turn the event bundle into a concise user-facing briefing.

Cheap Haiku call. Falls back to a template on API failure.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


HAIKU_MODEL = os.environ.get("BRIEFING_MODEL", "claude-haiku-4-5-20251001")

PROMPT_TEMPLATE = """You are Phoenix, a concise pre-market briefing writer for an active trader.

Today's date: {date}

Here is the overnight event bundle (JSON):
{events}

Write a 250-word briefing with these sections:
## Market Overnight
Top 3 drivers with direction + magnitude (e.g. "SPX futures -0.6% on rate fears")

## Today's Calendar
Earnings/macro prints that will move markets with exact times in ET

## Positions at Risk
Any open agent positions exposed to today's events (from the agent_positions list)

## Watchlist Heat
Tickers the agents are watching that have overnight catalysts from the Discord messages

## Suggested Actions
1-3 manual decisions the user should make before market open (or "nothing to do")

Rules:
- Plain English, no jargon
- Bullet points, not paragraphs
- ALL-CAPS ticker symbols
- Include exact numbers when possible
- No headers beyond the 5 above
- Hard cap: 300 words total
"""


def _template_fallback(events: dict) -> str:
    lines = [f"# Phoenix Morning Briefing — {events.get('collected_at', '')[:10]}", ""]
    moves = events.get("overnight_moves") or {}
    lines.append("## Market Overnight")
    for t, m in list(moves.items())[:5]:
        lines.append(f"- {t}: {m.get('pct_change', 0):+.2f}% (last ${m.get('last', 0)})")
    lines.append("")
    lines.append("## Today's Calendar")
    lines.append("- (calendar unavailable in fallback)")
    lines.append("")
    lines.append("## Positions at Risk")
    for ap in (events.get("agent_positions") or [])[:5]:
        lines.append(f"- {ap.get('name')}: {len(ap.get('positions', []))} open position(s)")
    lines.append("")
    lines.append("## Suggested Actions")
    lines.append("- Review positions and confirm daily loss limits before open")
    return "\n".join(lines)


def _call_haiku(prompt: str) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as exc:
        print(f"[compile] LLM call failed: {exc}", file=sys.stderr)
        return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--events", required=True)
    p.add_argument("--output", default="briefing.txt")
    args = p.parse_args()

    events_path = Path(args.events)
    if not events_path.exists():
        print(f"[compile] {events_path} not found", file=sys.stderr)
        sys.exit(1)

    events = json.loads(events_path.read_text())
    # Trim messages to keep prompt cheap
    trimmed = {
        **events,
        "discord_messages": [
            {"author": m.get("author"), "content": (m.get("content") or "")[:400],
             "tickers": m.get("tickers", [])}
            for m in (events.get("discord_messages") or [])[:60]
        ],
    }

    prompt = PROMPT_TEMPLATE.format(
        date=events.get("collected_at", "")[:10],
        events=json.dumps(trimmed, default=str)[:8000],
    )

    briefing = _call_haiku(prompt) or _template_fallback(events)
    Path(args.output).write_text(briefing)
    print(f"[compile] wrote briefing ({len(briefing)} chars) to {args.output}")


if __name__ == "__main__":
    main()
