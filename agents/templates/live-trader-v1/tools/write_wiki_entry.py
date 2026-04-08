#!/usr/bin/env python3
"""write_wiki_entry.py — Write a knowledge entry to the agent's wiki.

Called by live trading agents after closing trades, discovering patterns,
or any session-end consolidation. Writes to the Phoenix API wiki endpoint.

Usage:
    python tools/write_wiki_entry.py --category MISTAKES --title "..." --content "..."
    python tools/write_wiki_entry.py --help

Exit codes:
    0 — entry written successfully
    1 — validation error (bad args)
    2 — API error (non-fatal warning logged to stderr)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid categories and default confidence scores
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {
    "MARKET_PATTERNS",
    "SYMBOL_PROFILES",
    "STRATEGY_LEARNINGS",
    "MISTAKES",
    "WINNING_CONDITIONS",
    "SECTOR_NOTES",
    "MACRO_CONTEXT",
    "TRADE_OBSERVATION",
}

DEFAULT_CONFIDENCE: dict[str, float] = {
    "TRADE_OBSERVATION": 0.5,
    "MISTAKES": 0.85,           # High — mistakes are certain
    "WINNING_CONDITIONS": 0.75,
    "MARKET_PATTERNS": 0.65,
    "STRATEGY_LEARNINGS": 0.70,
    "SYMBOL_PROFILES": 0.60,
    "SECTOR_NOTES": 0.55,
    "MACRO_CONTEXT": 0.55,
}

# Categories that default to shared (community knowledge)
_SHARED_BY_DEFAULT: set[str] = {
    "MARKET_PATTERNS",
    "WINNING_CONDITIONS",
    "STRATEGY_LEARNINGS",
    "SYMBOL_PROFILES",
    "SECTOR_NOTES",
    "MACRO_CONTEXT",
}


# ---------------------------------------------------------------------------
# Config / auth helpers
# ---------------------------------------------------------------------------

def _get_api_url(config: dict) -> str:
    """Return Phoenix API base URL from env override or config fallback."""
    return os.environ.get("PHOENIX_API_URL") or config.get("phoenix_api_url", "http://localhost:8011")


def _get_api_token(config: dict) -> str:
    """Return Bearer token: config.api_token -> PHOENIX_API_TOKEN env -> empty string."""
    return (
        config.get("api_token")
        or os.environ.get("PHOENIX_API_TOKEN", "")
    )


def _load_config() -> dict:
    """Load config.json from the agent root (parent directory of this script's folder).

    Agents run from their root directory where config.json lives alongside the
    ``tools/`` sub-directory.  Falls back to an empty dict so the tool can still
    work using environment variables alone.
    """
    # tools/ lives one level below the agent root
    agent_root = Path(__file__).resolve().parent.parent
    config_path = agent_root / "config.json"
    if config_path.exists():
        try:
            with open(config_path) as fh:
                return json.load(fh)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read %s: %s", config_path, exc)
    return {}


# ---------------------------------------------------------------------------
# Core async writer (also usable as a library by other tools)
# ---------------------------------------------------------------------------

async def write_wiki_entry(config: dict, entry: dict) -> dict:
    """Write a wiki entry to the Phoenix API.

    Args:
        config: Agent config dict with keys:
            - phoenix_api_url / api_token / agent_id (all optional if env vars set)
        entry: Dict with wiki entry fields (see CLI args for full list).

    Returns:
        The created wiki entry dict from the API response.

    Raises:
        httpx.HTTPStatusError: If the API call fails (4xx / 5xx).
    """
    category = entry.get("category", "TRADE_OBSERVATION").upper()
    confidence = entry.get(
        "confidence_score",
        DEFAULT_CONFIDENCE.get(category, 0.6),
    )
    payload: dict = {
        "category": category,
        "title": entry["title"],
        "content": entry["content"],
        "tags": entry.get("tags", []),
        "symbols": entry.get("symbols", []),
        "confidence_score": confidence,
        "trade_ref_ids": entry.get("trade_ref_ids", []),
        "is_shared": entry.get("is_shared", category in _SHARED_BY_DEFAULT),
    }
    if entry.get("subcategory"):
        payload["subcategory"] = entry["subcategory"]

    agent_id = config.get("agent_id", "")
    url = f"{_get_api_url(config)}/api/v2/agents/{agent_id}/wiki"
    token = _get_api_token(config)
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()
        logger.info(
            "Wiki entry created: id=%s category=%s title=%r",
            result.get("id"),
            category,
            payload["title"],
        )
        return result


# ---------------------------------------------------------------------------
# CLI entry-point — agents call this as a subprocess
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a knowledge entry to the agent's wiki.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes:\n"
            "  0 — entry written successfully\n"
            "  1 — validation error (bad args)\n"
            "  2 — API error (non-fatal warning logged to stderr)\n"
        ),
    )
    parser.add_argument(
        "--category",
        required=True,
        choices=sorted(VALID_CATEGORIES),
        metavar="CATEGORY",
        help=(
            "Knowledge category. One of: "
            + ", ".join(sorted(VALID_CATEGORIES))
        ),
    )
    parser.add_argument("--title", required=True, help="Short descriptive title (max 255 chars).")
    parser.add_argument("--content", required=True, help="The knowledge text.")
    parser.add_argument("--subcategory", default=None, help="Optional sub-category.")
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated ticker symbols, e.g. NVDA,TSLA.",
    )
    parser.add_argument(
        "--tags",
        default="",
        help="Comma-separated tags, e.g. earnings,options,loss.",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=None,
        help="Confidence score 0.0-1.0 (default varies by category).",
    )
    parser.add_argument(
        "--trade-id",
        dest="trade_id",
        default=None,
        help="UUID of the trade this entry is based on.",
    )
    parser.add_argument(
        "--is-shared",
        dest="is_shared",
        action="store_true",
        default=None,
        help="If present, marks entry as shared (visible to other agents).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be written without calling the API.",
    )
    return parser


def main() -> None:  # noqa: C901
    parser = _build_parser()
    args = parser.parse_args()

    # --- Validate title length ---
    if len(args.title) > 255:
        print(f"\u2717 --title exceeds 255 characters ({len(args.title)})", file=sys.stderr)
        sys.exit(1)

    # --- Validate confidence range ---
    if args.confidence is not None and not (0.0 <= args.confidence <= 1.0):
        print("\u2717 --confidence must be between 0.0 and 1.0", file=sys.stderr)
        sys.exit(1)

    # --- Load config ---
    config = _load_config()

    # --- Resolve confidence ---
    category = args.category.upper()
    confidence: float = (
        args.confidence
        if args.confidence is not None
        else DEFAULT_CONFIDENCE.get(category, 0.6)
    )

    # --- Build entry dict ---
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    tags = [t.strip().lower() for t in args.tags.split(",") if t.strip()]
    trade_ref_ids = [args.trade_id] if args.trade_id else []
    is_shared: bool = (
        args.is_shared
        if args.is_shared is not None
        else (category in _SHARED_BY_DEFAULT)
    )

    entry: dict = {
        "category": category,
        "title": args.title,
        "content": args.content,
        "tags": tags,
        "symbols": symbols,
        "confidence_score": confidence,
        "trade_ref_ids": trade_ref_ids,
        "is_shared": is_shared,
    }
    if args.subcategory:
        entry["subcategory"] = args.subcategory

    # --- Dry-run: print and exit ---
    if args.dry_run:
        print("DRY-RUN \u2014 would write:")
        print(json.dumps(entry, indent=2))
        sys.exit(0)

    # --- Call API (non-fatal on error) ---
    try:
        result = asyncio.run(write_wiki_entry(config, entry))
        entry_id = result.get("id", "?")
        print(
            f"\u2713 Wiki entry written: {entry_id} [{category}] "
            f'"{args.title}" (confidence: {confidence:.0%})'
        )
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"\u26a0 Wiki write failed (non-fatal): {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
