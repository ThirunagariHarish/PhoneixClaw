"""Options flow check for position monitoring via Unusual Whales.

Returns put/call ratio, sweep detection, IV rank, and GEX data
to supplement exit decision urgency scoring.

Usage:
    python options_flow_check.py --ticker AAPL --side buy --output flow.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path


def check_options_flow(ticker: str, side: str) -> dict:
    """Query Unusual Whales for options flow signals relevant to exit decisions."""
    result = {
        "ticker": ticker,
        "side": side,
        "exit_urgency": 0,
        "signals": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        from shared.unusual_whales.client import UnusualWhalesClient
    except ImportError:
        result["error"] = "unusual_whales client not available"
        return result

    loop = asyncio.new_event_loop()
    try:
        client = UnusualWhalesClient()
        is_long = side == "buy"
        urgency = 0

        # Options flow
        try:
            flow = loop.run_until_complete(client.get_options_flow(ticker=ticker))
            if flow:
                recent = flow[:50]
                call_premium = sum(float(f.premium or 0) for f in recent if f.option_type == "CALL")
                put_premium = sum(float(f.premium or 0) for f in recent if f.option_type == "PUT")
                total = call_premium + put_premium

                if total > 0:
                    pc_ratio = put_premium / call_premium if call_premium > 0 else 10.0
                    result["signals"]["put_call_ratio"] = round(pc_ratio, 2)

                    if is_long and pc_ratio > 1.5:
                        urgency += 10
                        result["signals"]["flow_alert"] = "heavy_put_flow"
                    elif not is_long and pc_ratio < 0.5:
                        urgency += 10
                        result["signals"]["flow_alert"] = "heavy_call_flow"

                # Detect large sweeps (>$100k premium, aggressive fills)
                large_puts = [f for f in recent if f.option_type == "PUT"
                              and float(f.premium or 0) > 100_000]
                large_calls = [f for f in recent if f.option_type == "CALL"
                               and float(f.premium or 0) > 100_000]

                if is_long and len(large_puts) >= 2:
                    urgency += 15
                    result["signals"]["large_put_sweeps"] = len(large_puts)
                elif not is_long and len(large_calls) >= 2:
                    urgency += 15
                    result["signals"]["large_call_sweeps"] = len(large_calls)
        except Exception as e:
            result["signals"]["flow_error"] = str(e)[:100]

        # GEX (Gamma Exposure)
        try:
            gex = loop.run_until_complete(client.get_gex(ticker))
            if gex and gex.total_gex is not None:
                gex_val = float(gex.total_gex)
                result["signals"]["gex_value"] = gex_val
                result["signals"]["gex_positive"] = gex_val > 0
                # Negative GEX = dealers short gamma = amplified moves
                if gex_val < 0 and is_long:
                    urgency += 5
                    result["signals"]["gex_alert"] = "negative_gex_amplified_moves"
        except Exception:
            pass

        # IV rank from option chain
        try:
            chain = loop.run_until_complete(client.get_option_chain(ticker))
            if chain and chain.contracts:
                ivs = [c.implied_volatility for c in chain.contracts if c.implied_volatility]
                if ivs:
                    current_iv = ivs[0]
                    iv_min, iv_max = min(ivs), max(ivs)
                    iv_rank = (current_iv - iv_min) / (iv_max - iv_min) if iv_max > iv_min else 0.5
                    result["signals"]["iv_rank"] = round(iv_rank, 2)
                    result["signals"]["iv_current"] = round(current_iv, 4)

                    if iv_rank > 0.8:
                        urgency += 8
                        result["signals"]["iv_alert"] = "elevated_iv_rank"
        except Exception:
            pass

        result["exit_urgency"] = min(urgency, 40)

    except Exception as e:
        result["error"] = str(e)[:200]
    finally:
        loop.close()

    return result


def main():
    parser = argparse.ArgumentParser(description="Options flow check for exit decisions")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--side", required=True, choices=["buy", "sell"])
    parser.add_argument("--output", default="flow.json")
    args = parser.parse_args()

    result = check_options_flow(args.ticker, args.side)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
