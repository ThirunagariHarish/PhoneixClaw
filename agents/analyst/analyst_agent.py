"""Analyst Agent — persona-driven multi-tool signal generator.

Supports two workflow modes:
  signal_intake  — poll recent Discord/UW signals, analyze each ticker, emit signals
  pre_market     — run pre-market analysis on a watchlist of tickers

Usage:
    python agents/analyst/analyst_agent.py \
        --agent_id <UUID> \
        --persona_id aggressive_momentum \
        --mode signal_intake \
        --config '{"tickers": ["AAPL", "NVDA"]}'
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root on sys.path for shared imports
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("analyst_agent")


async def run_signal_intake(
    agent_id: str,
    persona_id: str,
    config: dict,
) -> list[dict]:
    """Poll recent Discord/UW signals and analyze each unique ticker.

    For each ticker found in recent signals, runs the full tool chain and
    emits a TradeSignal if confidence is above threshold.

    Returns list of emitted signal summaries.
    """
    from agents.analyst.personas.library import get_persona
    from agents.analyst.tools.analyze_chart import analyze_chart
    from agents.analyst.tools.emit_trade_signal import emit_trade_signal
    from agents.analyst.tools.fetch_discord_signals import fetch_discord_signals
    from agents.analyst.tools.get_news_sentiment import get_news_sentiment
    from agents.analyst.tools.scan_options_flow import scan_options_flow
    from agents.analyst.tools.score_trade_setup import score_trade_setup

    try:
        persona = get_persona(persona_id)
    except KeyError:
        logger.warning("Unknown persona '%s', falling back to aggressive_momentum", persona_id)
        persona = get_persona("aggressive_momentum")

    since_minutes = config.get("since_minutes", 30)
    max_tickers = config.get("max_tickers", 10)
    interval = config.get("chart_interval", persona.preferred_timeframes[0] if persona.preferred_timeframes else "15m")

    logger.info("signal_intake: persona=%s, since=%dmin, interval=%s", persona.id, since_minutes, interval)

    raw_signals = await fetch_discord_signals(agent_id=agent_id, since_minutes=since_minutes)
    if not raw_signals:
        logger.info("signal_intake: no recent Discord/UW signals found")
        return []

    # Deduplicate tickers, prioritize most recent
    seen: dict[str, dict] = {}
    for sig in raw_signals:
        ticker = (sig.get("ticker") or "").upper()
        if ticker and ticker not in seen:
            seen[ticker] = sig
        if len(seen) >= max_tickers:
            break

    tickers = list(seen.keys())
    logger.info("signal_intake: analyzing %d tickers: %s", len(tickers), tickers)

    emitted: list[dict] = []
    persona_dict = {
        "tool_weights": persona.tool_weights,
        "min_confidence_threshold": persona.min_confidence_threshold,
        "signal_filters": persona.signal_filters,
    }

    for ticker in tickers:
        try:
            logger.info("Analyzing %s...", ticker)

            chart, options, sentiment = await asyncio.gather(
                analyze_chart(ticker, interval=interval),
                scan_options_flow(ticker),
                get_news_sentiment(ticker),
                return_exceptions=True,
            )

            # Replace exceptions with neutral defaults
            if isinstance(chart, Exception):
                logger.warning("chart error for %s: %s", ticker, chart)
                chart = {"signal": "neutral", "patterns": [], "current_price": 0.0}
            if isinstance(options, Exception):
                logger.warning("options error for %s: %s", ticker, options)
                options = {"signal": "neutral"}
            if isinstance(sentiment, Exception):
                logger.warning("sentiment error for %s: %s", ticker, sentiment)
                sentiment = {"signal": "neutral"}

            score = score_trade_setup(
                ticker=ticker,
                persona_config=persona_dict,
                chart_signal=chart,
                options_signal=options,
                sentiment_signal=sentiment,
            )

            confidence = score["confidence"]
            recommendation = score["recommendation"]

            if not score["above_threshold"]:
                logger.info("%s: confidence=%d, below threshold — skipping", ticker, confidence)
                continue

            current_price = chart.get("current_price", 0.0) or 0.0
            stop_loss_pct = persona.stop_loss_pct()
            rr_target = 2.0 if persona.stop_loss_style == "tight" else 3.0

            if recommendation == "buy":
                direction = "buy"
                stop_loss = round(current_price * (1 - stop_loss_pct / 100), 2)
                take_profit = round(current_price * (1 + (stop_loss_pct / 100) * rr_target), 2)
            else:
                direction = "sell"
                stop_loss = round(current_price * (1 + stop_loss_pct / 100), 2)
                take_profit = round(current_price * (1 - (stop_loss_pct / 100) * rr_target), 2)

            patterns = chart.get("patterns", [])
            pattern_name = patterns[0] if patterns else None

            reasoning = (
                f"{persona.name} analysis for {ticker}: "
                f"Chart={chart.get('signal','neutral')} (RSI={chart.get('rsi','?')}), "
                f"Options={options.get('signal','neutral')} "
                f"(sweeps={options.get('sweep_count',0)}), "
                f"Sentiment={sentiment.get('sentiment','Neutral')} "
                f"(score={sentiment.get('score',0)}). "
                f"Confidence={confidence}. "
                f"Signals used: {', '.join(score['signals_used']) or 'none'}."
            )

            tool_signals = {
                "chart": chart,
                "options_flow": options,
                "sentiment": sentiment,
                "score_breakdown": score["breakdown"],
            }

            signal_id = await emit_trade_signal(
                agent_id=agent_id,
                ticker=ticker,
                direction=direction,
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                reasoning=reasoning,
                analyst_persona=persona.id,
                tool_signals_used=tool_signals,
                pattern_name=pattern_name,
            )

            if not signal_id:
                logger.error("Signal emit failed for %s — skipping", ticker)
                continue

            summary = {
                "signal_id": signal_id,
                "ticker": ticker,
                "direction": direction,
                "confidence": confidence,
                "entry_price": current_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "pattern": pattern_name,
                "persona": persona.id,
                "emitted_at": datetime.now(timezone.utc).isoformat(),
            }
            emitted.append(summary)
            logger.info("Emitted signal %s for %s (%s, confidence=%d)", signal_id, ticker, direction, confidence)

        except Exception as exc:
            logger.error("Error processing %s: %s", ticker, exc, exc_info=True)

    logger.info("signal_intake complete: emitted %d signals", len(emitted))
    return emitted


async def run_pre_market(
    agent_id: str,
    persona_id: str,
    config: dict,
) -> list[dict]:
    """Run pre-market analysis on a configured watchlist.

    Analyzes each ticker in config['tickers'] or config['watchlist'] and
    emits signals for any setups above threshold.

    Returns list of emitted signal summaries.
    """
    from agents.analyst.personas.library import get_persona
    from agents.analyst.tools.analyze_chart import analyze_chart
    from agents.analyst.tools.emit_trade_signal import emit_trade_signal
    from agents.analyst.tools.get_news_sentiment import get_news_sentiment
    from agents.analyst.tools.scan_options_flow import scan_options_flow
    from agents.analyst.tools.score_trade_setup import score_trade_setup

    try:
        persona = get_persona(persona_id)
    except KeyError:
        logger.warning("Unknown persona '%s', falling back to aggressive_momentum", persona_id)
        persona = get_persona("aggressive_momentum")

    tickers = config.get("tickers") or config.get("watchlist") or []
    if not tickers:
        logger.warning("pre_market: no tickers configured")
        return []

    # Pre-market uses daily chart for broader view
    interval = config.get("chart_interval", "1h")
    logger.info("pre_market: persona=%s, %d tickers, interval=%s", persona.id, len(tickers), interval)

    persona_dict = {
        "tool_weights": persona.tool_weights,
        "min_confidence_threshold": persona.min_confidence_threshold,
        "signal_filters": persona.signal_filters,
    }

    emitted: list[dict] = []

    for ticker in tickers:
        ticker = ticker.upper()
        try:
            logger.info("Pre-market analyzing %s...", ticker)

            chart, options, sentiment = await asyncio.gather(
                analyze_chart(ticker, interval=interval, lookback_days=10),
                scan_options_flow(ticker, since_minutes=480),  # 8 hours
                get_news_sentiment(ticker),
                return_exceptions=True,
            )

            if isinstance(chart, Exception):
                chart = {"signal": "neutral", "patterns": [], "current_price": 0.0}
            if isinstance(options, Exception):
                options = {"signal": "neutral"}
            if isinstance(sentiment, Exception):
                sentiment = {"signal": "neutral"}

            score = score_trade_setup(
                ticker=ticker,
                persona_config=persona_dict,
                chart_signal=chart,
                options_signal=options,
                sentiment_signal=sentiment,
            )

            confidence = score["confidence"]
            recommendation = score["recommendation"]

            if not score["above_threshold"]:
                logger.info("%s: confidence=%d, below threshold — skipping", ticker, confidence)
                continue

            current_price = chart.get("current_price", 0.0) or 0.0
            stop_loss_pct = persona.stop_loss_pct()
            rr_target = 2.0 if persona.stop_loss_style == "tight" else 3.0

            if recommendation == "buy":
                direction = "buy"
                stop_loss = round(current_price * (1 - stop_loss_pct / 100), 2)
                take_profit = round(current_price * (1 + (stop_loss_pct / 100) * rr_target), 2)
            else:
                direction = "sell"
                stop_loss = round(current_price * (1 + stop_loss_pct / 100), 2)
                take_profit = round(current_price * (1 - (stop_loss_pct / 100) * rr_target), 2)

            patterns = chart.get("patterns", [])
            pattern_name = patterns[0] if patterns else None

            reasoning = (
                f"[PRE-MARKET] {persona.name} scan for {ticker}: "
                f"Chart={chart.get('signal','neutral')} "
                f"(RSI={chart.get('rsi','?')}, trend={chart.get('trend','?')}), "
                f"Options={options.get('signal','neutral')}, "
                f"Sentiment={sentiment.get('sentiment','Neutral')}. "
                f"Confidence={confidence}."
            )

            tool_signals = {
                "chart": chart,
                "options_flow": options,
                "sentiment": sentiment,
                "score_breakdown": score["breakdown"],
            }

            signal_id = await emit_trade_signal(
                agent_id=agent_id,
                ticker=ticker,
                direction=direction,
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                reasoning=reasoning,
                analyst_persona=persona.id,
                tool_signals_used=tool_signals,
                pattern_name=pattern_name,
            )

            if not signal_id:
                logger.error("Signal emit failed for %s — skipping", ticker)
                continue

            summary = {
                "signal_id": signal_id,
                "ticker": ticker,
                "direction": direction,
                "confidence": confidence,
                "entry_price": current_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "pattern": pattern_name,
                "persona": persona.id,
                "emitted_at": datetime.now(timezone.utc).isoformat(),
            }
            emitted.append(summary)
            logger.info("Pre-market signal %s for %s (%s, confidence=%d)", signal_id, ticker, direction, confidence)

        except Exception as exc:
            logger.error("pre_market error for %s: %s", ticker, exc, exc_info=True)

    logger.info("pre_market complete: emitted %d signals", len(emitted))
    return emitted


async def main_async(args: argparse.Namespace) -> None:
    config: dict = {}
    if args.config:
        try:
            config = json.loads(args.config)
        except json.JSONDecodeError as exc:
            logger.warning("Could not parse --config JSON: %s", exc)

    logger.info(
        "Analyst agent starting: agent_id=%s, persona=%s, mode=%s",
        args.agent_id, args.persona_id, args.mode,
    )

    if args.mode == "signal_intake":
        results = await run_signal_intake(args.agent_id, args.persona_id, config)
    elif args.mode == "pre_market":
        results = await run_pre_market(args.agent_id, args.persona_id, config)
    else:
        logger.error("Unknown mode: %s. Use 'signal_intake' or 'pre_market'", args.mode)
        results = []

    output = {
        "agent_id": args.agent_id,
        "persona_id": args.persona_id,
        "mode": args.mode,
        "signals_emitted": len(results),
        "results": results,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    print(json.dumps(output, indent=2, default=str))
    logger.info("Analyst agent completed: %d signals emitted", len(results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyst Agent — persona-driven signal generator")
    parser.add_argument("--agent_id", required=True, help="UUID of the analyst agent row")
    parser.add_argument(
        "--persona_id",
        default="aggressive_momentum",
        help="Persona ID (aggressive_momentum, conservative_swing, options_flow_specialist, etc.)",
    )
    parser.add_argument(
        "--mode",
        default="signal_intake",
        choices=["signal_intake", "pre_market"],
        help="Workflow mode",
    )
    parser.add_argument(
        "--config",
        default="{}",
        help="JSON config string (tickers, since_minutes, chart_interval, etc.)",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))
