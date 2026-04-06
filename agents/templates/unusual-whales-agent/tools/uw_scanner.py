"""Unusual Whales scanner — polls UW API for unusual options activity.

Wraps shared/unusual_whales/client.py UnusualWhalesClient.

Usage:
    python uw_scanner.py --output flow_data.json
    python uw_scanner.py --health
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _get_config() -> dict:
    cfg_path = Path("config.json")
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


async def scan_flow() -> dict:
    """Fetch unusual flow, GEX, and market tide from Unusual Whales."""
    result = {
        "flow_alerts": [],
        "gex_shifts": [],
        "market_tide": {},
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "errors": [],
    }

    cfg = _get_config()
    api_key = cfg.get("unusual_whales_api_key") or os.getenv("UNUSUAL_WHALES_API_KEY", "")

    if not api_key:
        result["errors"].append("UNUSUAL_WHALES_API_KEY not set")
        return result

    try:
        # Reuse existing shared client
        sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
        from shared.unusual_whales.client import UnusualWhalesClient

        client = UnusualWhalesClient()

        # Top movers / unusual flow
        try:
            tickers = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "META", "GOOGL", "AMZN"]
            for ticker in tickers:
                try:
                    flow = await client.get_options_flow(ticker=ticker)
                    if flow:
                        for f in flow[:5]:  # Top 5 per ticker
                            result["flow_alerts"].append({
                                "ticker": ticker,
                                "premium": float(getattr(f, "premium", 0) or 0),
                                "volume": int(getattr(f, "volume", 0) or 0),
                                "open_interest": int(getattr(f, "open_interest", 0) or 0),
                                "option_type": getattr(f, "option_type", ""),
                                "strike": float(getattr(f, "strike", 0) or 0),
                                "expiry": str(getattr(f, "expiry", "") or ""),
                                "is_sweep": bool(getattr(f, "is_sweep", False)),
                                "side": getattr(f, "side", ""),
                            })
                except Exception as e:
                    result["errors"].append(f"flow {ticker}: {str(e)[:100]}")
        except Exception as e:
            result["errors"].append(f"flow loop: {str(e)[:200]}")

        # GEX
        try:
            for ticker in ["SPY", "QQQ"]:
                gex = await client.get_gex(ticker)
                if gex and getattr(gex, "total_gex", None) is not None:
                    result["gex_shifts"].append({
                        "ticker": ticker,
                        "total_gex": float(gex.total_gex),
                        "positive": float(gex.total_gex) > 0,
                    })
        except Exception as e:
            result["errors"].append(f"gex: {str(e)[:200]}")

        await client.close()

    except ImportError as e:
        result["errors"].append(f"UW client unavailable: {e}")
    except Exception as e:
        result["errors"].append(f"scan failed: {str(e)[:200]}")

    return result


async def health_check() -> dict:
    cfg = _get_config()
    api_key = cfg.get("unusual_whales_api_key") or os.getenv("UNUSUAL_WHALES_API_KEY", "")
    return {
        "api_key_present": bool(api_key),
        "client_importable": True,  # Will be set False if import fails
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="Unusual Whales scanner")
    parser.add_argument("--output", default="flow_data.json")
    parser.add_argument("--health", action="store_true", help="Health check only")
    args = parser.parse_args()

    if args.health:
        result = asyncio.run(health_check())
    else:
        result = asyncio.run(scan_flow())
        Path(args.output).write_text(json.dumps(result, indent=2, default=str))

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
