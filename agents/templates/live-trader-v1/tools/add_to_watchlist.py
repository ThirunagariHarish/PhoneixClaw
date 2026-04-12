"""Add one or more tickers to the Robinhood watchlist via the MCP server.

This is the canonical CLI entrypoint for the live agent to call when it
decides a signal should be monitored but not traded.  It uses
RobinhoodMCPClient (which starts robinhood_mcp.py as a subprocess) so the
actual Robinhood API call goes through the authenticated MCP server.

Usage:
    python3 tools/add_to_watchlist.py --ticker MSFT --config config.json
    python3 tools/add_to_watchlist.py --ticker MSFT AAPL --config config.json
    python3 tools/add_to_watchlist.py --ticker MSFT --watchlist-name "My List" --config config.json

Exit codes:
    0 — added (or paper-mode simulated successfully)
    1 — failed to add (error printed to stderr, details in stdout JSON)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from robinhood_mcp_client import RobinhoodMCPClient  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchlist] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


def add_to_watchlist(
    tickers: list[str],
    config: dict,
    watchlist_name: str = "Phoenix Paper",
) -> dict:
    """Call the MCP add_to_watchlist tool and return the result dict."""
    # R-001: pre-check credentials before starting MCP subprocess.
    # If no credentials are present and PAPER_MODE is not set, skip the MCP
    # call so we don't block the poll loop for the full 30-second timeout
    # waiting for a subprocess that will immediately fail _ensure_login().
    import os
    paper_mode = (
        isinstance(config.get("paper_mode"), bool) and config["paper_mode"]
    ) or os.environ.get("PAPER_MODE", "").lower() in ("1", "true", "yes")

    if not paper_mode:
        creds = config.get("robinhood_credentials") or config.get("robinhood") or {}
        has_creds = (
            os.environ.get("RH_USERNAME") and os.environ.get("RH_PASSWORD")
        ) or (creds.get("username") and creds.get("password"))
        if not has_creds:
            log.warning(
                "No Robinhood credentials in config — skipping actual watchlist add. "
                "Tickers logged to Phoenix dashboard only."
            )
            return {
                "status": "skipped_no_credentials",
                "symbols": tickers,
                "watchlist_name": watchlist_name,
            }

    client = RobinhoodMCPClient(config)
    try:
        # R-003: catch start() failures (e.g. MCP script missing) gracefully
        try:
            client.start()
        except Exception as start_exc:
            log.error("MCP server failed to start: %s", start_exc)
            return {"error": f"MCP start failed: {start_exc}", "skipped": True}
        result = client.call(
            "add_to_watchlist",
            {
                "symbols": [t.upper() for t in tickers],
                "watchlist_name": watchlist_name,
            },
        )
        return result
    finally:
        client.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Add tickers to Robinhood watchlist via MCP")
    parser.add_argument("--ticker", nargs="+", required=True, help="One or more ticker symbols")
    parser.add_argument("--config", default="config.json", help="Path to agent config.json")
    parser.add_argument("--watchlist-name", default="Phoenix Paper", help="Robinhood watchlist name")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        log.error("Config file not found: %s", config_path.resolve())
        print(json.dumps({"ok": False, "error": f"Config not found: {args.config}"}))
        sys.exit(1)

    try:
        config = json.loads(config_path.read_text())
    except Exception as exc:
        log.error("Failed to parse config: %s", exc)
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)

    tickers = [t.upper() for t in args.ticker]
    log.info("Adding to watchlist '%s': %s", args.watchlist_name, tickers)

    result = add_to_watchlist(tickers, config, watchlist_name=args.watchlist_name)

    if result.get("error"):
        log.error("add_to_watchlist failed: %s", result["error"])
        print(json.dumps({"ok": False, "tickers": tickers, **result}))
        sys.exit(1)

    log.info("Watchlist result: %s", result)
    print(json.dumps({"ok": True, "tickers": tickers, **result}))


if __name__ == "__main__":
    main()
