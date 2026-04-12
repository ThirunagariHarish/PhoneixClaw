"""IBKR real-time data check for position monitoring.

Fetches Level 2 order book depth, live options Greeks, and bid/ask spread
from Interactive Brokers to provide institutional-grade exit signals.

Requires: pip install ib_insync
Set IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID environment variables.

Falls back gracefully when IBKR is not connected — returns empty signals
rather than erroring. This is an optional enhancement on top of the core
TA + macro + options flow checks.

Usage:
    python ibkr_data_check.py --ticker AAPL --side buy --output ibkr.json
    python ibkr_data_check.py --ticker AAPL --side buy --option-contract '{"strike": 185, "expiry": "2026-04-18", "right": "C"}' --output ibkr.json
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def check_ibkr_data(
    ticker: str,
    side: str,
    option_contract: dict | None = None,
) -> dict:
    """Fetch IBKR data for exit decision signals.

    Returns bid/ask spread, order book imbalance, live Greeks (for options),
    and theta decay urgency. Degrades gracefully if IBKR is unavailable.
    """
    result = {
        "ticker": ticker,
        "side": side,
        "exit_urgency": 0,
        "signals": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    host = os.getenv("IBKR_HOST", "127.0.0.1")
    port = int(os.getenv("IBKR_PORT", "7497"))
    client_id = int(os.getenv("IBKR_CLIENT_ID", "10"))

    try:
        from ib_insync import IB, Option, Stock
    except ImportError:
        result["signals"]["ibkr_status"] = "ib_insync_not_installed"
        return result

    ib = IB()
    is_long = side == "buy"
    urgency = 0

    try:
        ib.connect(host, port, clientId=client_id, timeout=5)
    except Exception as e:
        result["signals"]["ibkr_status"] = f"connection_failed: {str(e)[:100]}"
        return result

    try:
        # Build contract
        if option_contract:
            contract = Option(
                ticker,
                option_contract.get("expiry", ""),
                float(option_contract.get("strike", 0)),
                option_contract.get("right", "C"),
                "SMART",
            )
        else:
            contract = Stock(ticker, "SMART", "USD")

        ib.qualifyContracts(contract)

        # 1. Bid/Ask spread
        try:
            ticker_data = ib.reqMktData(contract, "", False, False)
            ib.sleep(2)

            bid = ticker_data.bid
            ask = ticker_data.ask
            last = ticker_data.last

            if bid and ask and bid > 0 and ask > 0:
                spread = ask - bid
                spread_pct = spread / ((bid + ask) / 2) * 100
                result["signals"]["bid"] = round(bid, 2)
                result["signals"]["ask"] = round(ask, 2)
                result["signals"]["spread"] = round(spread, 4)
                result["signals"]["spread_pct"] = round(spread_pct, 2)

                # Wide spread = illiquid = risky exit
                if spread_pct > 2.0:
                    urgency += 10
                    result["signals"]["spread_alert"] = "very_wide_spread"
                elif spread_pct > 1.0:
                    urgency += 5
                    result["signals"]["spread_alert"] = "wide_spread"

            if last:
                result["signals"]["last_price"] = round(last, 2)

            ib.cancelMktData(contract)
        except Exception as e:
            result["signals"]["market_data_error"] = str(e)[:100]

        # 2. Order book depth (Level 2)
        try:
            dom = ib.reqMktDepth(contract, numRows=5)
            ib.sleep(2)

            if dom:
                bid_size = sum(d.size for d in dom if d.side == 1)
                ask_size = sum(d.size for d in dom if d.side == 0)
                total = bid_size + ask_size

                if total > 0:
                    imbalance = (bid_size - ask_size) / total
                    result["signals"]["bid_size"] = bid_size
                    result["signals"]["ask_size"] = ask_size
                    result["signals"]["order_book_imbalance"] = round(imbalance, 3)

                    # Sell-side pressure on a long position
                    if is_long and imbalance < -0.3:
                        urgency += 8
                        result["signals"]["book_alert"] = "heavy_selling_pressure"
                    elif not is_long and imbalance > 0.3:
                        urgency += 8
                        result["signals"]["book_alert"] = "heavy_buying_pressure"

            ib.cancelMktDepth(contract)
        except Exception as e:
            result["signals"]["depth_error"] = str(e)[:100]

        # 3. Live Greeks (options only)
        if option_contract:
            try:
                greeks = ticker_data.modelGreeks or ticker_data.lastGreeks
                if greeks:
                    result["signals"]["delta"] = round(greeks.delta or 0, 4)
                    result["signals"]["gamma"] = round(greeks.gamma or 0, 6)
                    result["signals"]["theta"] = round(greeks.theta or 0, 4)
                    result["signals"]["vega"] = round(greeks.vega or 0, 4)
                    result["signals"]["iv"] = round(greeks.impliedVol or 0, 4)

                    # Theta decay urgency
                    theta = abs(greeks.theta or 0)
                    current_value = result["signals"].get("last_price", 0)
                    if current_value > 0 and theta > 0:
                        daily_decay_pct = (theta / current_value) * 100
                        result["signals"]["daily_theta_decay_pct"] = round(daily_decay_pct, 2)

                        if daily_decay_pct > 5:
                            urgency += 15
                            result["signals"]["theta_alert"] = f"severe_decay_{daily_decay_pct:.1f}%/day"
                        elif daily_decay_pct > 3:
                            urgency += 10
                            result["signals"]["theta_alert"] = f"heavy_decay_{daily_decay_pct:.1f}%/day"
                        elif daily_decay_pct > 1.5:
                            urgency += 5
                            result["signals"]["theta_alert"] = f"moderate_decay_{daily_decay_pct:.1f}%/day"

                    # Low delta = deep OTM, consider closing
                    if abs(greeks.delta or 0) < 0.15:
                        urgency += 10
                        result["signals"]["delta_alert"] = "deep_otm"
            except Exception as e:
                result["signals"]["greeks_error"] = str(e)[:100]

        result["exit_urgency"] = min(urgency, 40)
        result["signals"]["ibkr_status"] = "connected"

    except Exception as e:
        result["signals"]["ibkr_error"] = str(e)[:200]
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass

    return result


def main():
    parser = argparse.ArgumentParser(description="IBKR real-time data check for exit decisions")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--side", required=True, choices=["buy", "sell"])
    parser.add_argument("--option-contract", default=None, help="JSON string with strike, expiry, right")
    parser.add_argument("--output", default="ibkr.json")
    args = parser.parse_args()

    option_contract = None
    if args.option_contract:
        try:
            option_contract = json.loads(args.option_contract)
        except json.JSONDecodeError:
            pass

    result = check_ibkr_data(args.ticker, args.side, option_contract)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
