"""Write a wiki entry to the Agent Knowledge Wiki via Phoenix API.

Categories:
    TRADE_OBSERVATION  — notes about a specific trade (is_shared defaults to False)
    MARKET_PATTERN     — recurring market pattern observed (is_shared defaults to True)
    STRATEGY_LEARNING  — strategy-level lesson learned (is_shared defaults to True)
    RISK_NOTE          — risk management insight (is_shared defaults to True)
    SECTOR_INSIGHT     — sector/macro observation (is_shared defaults to True)
    INDICATOR_NOTE     — indicator behavior note (is_shared defaults to True)
    EARNINGS_PLAYBOOK  — earnings trade setup (is_shared defaults to True)
    GENERAL            — any other knowledge (is_shared defaults to False)

Usage by agent:
    result = await write_wiki_entry(config, {
        "category": "TRADE_OBSERVATION",
        "title": "AAPL bearish reversal at resistance",
        "content": "Observed clean bearish engulfing at $185 resistance...",
        "tags": ["bearish", "reversal", "resistance"],
        "symbols": ["AAPL"],
        "confidence_score": 0.7,
        "trade_ref_ids": ["uuid-of-closed-trade"],
    })
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

import httpx

logger = logging.getLogger(__name__)

# Categories where entries should default to shared (community knowledge)
_SHARED_BY_DEFAULT = {
    "MARKET_PATTERN",
    "STRATEGY_LEARNING",
    "RISK_NOTE",
    "SECTOR_INSIGHT",
    "INDICATOR_NOTE",
    "EARNINGS_PLAYBOOK",
}


def _default_is_shared(category: str) -> bool:
    """Return True if this category should be shared with the Phoenix Brain by default."""
    return category.upper() in _SHARED_BY_DEFAULT


async def write_wiki_entry(config: dict, entry: dict) -> dict:
    """Write a wiki entry to the Phoenix API.

    Args:
        config: Agent config dict with keys:
            - phoenix_api_url: Base URL of Phoenix API (e.g. http://localhost:8011)
            - agent_id: UUID of the agent writing the entry
            - phoenix_api_key: Bearer token for auth
        entry: Dict with wiki entry fields:
            - category (str, required): One of the 8 categories above
            - title (str, required): Short descriptive title
            - content (str, required): Full knowledge content
            - tags (list[str], optional): Searchable tags
            - symbols (list[str], optional): Related ticker symbols
            - confidence_score (float, optional): 0.0-1.0 confidence in this observation
            - trade_ref_ids (list[str], optional): UUIDs of trades this entry references
            - is_shared (bool, optional): Override default sharing behaviour
            - subcategory (str, optional): Further categorisation

    Returns:
        The created wiki entry dict from the API response.

    Raises:
        httpx.HTTPStatusError: If the API call fails (4xx / 5xx).
    """
    category = entry.get("category", "GENERAL")
    payload = {
        "category": category,
        "title": entry["title"],
        "content": entry["content"],
        "tags": entry.get("tags", []),
        "symbols": entry.get("symbols", []),
        "confidence_score": entry.get("confidence_score", 0.5),
        "trade_ref_ids": entry.get("trade_ref_ids", []),
        "is_shared": entry.get("is_shared", _default_is_shared(category)),
        "subcategory": entry.get("subcategory"),
    }
    # Remove None values
    payload = {k: v for k, v in payload.items() if v is not None}

    url = f"{config['phoenix_api_url']}/api/v2/agents/{config['agent_id']}/wiki"
    headers = {"Authorization": f"Bearer {config.get('phoenix_api_key', '')}"}

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


async def query_wiki(
    config: dict,
    query_text: str,
    category: str | None = None,
    top_k: int = 10,
    include_shared: bool = True,
) -> list[dict]:
    """Query the wiki for relevant entries.

    Used by the agent before making decisions to retrieve prior learnings.

    Args:
        config: Agent config dict (phoenix_api_url, agent_id, phoenix_api_key).
        query_text: Free-text search string.
        category: Optional category filter (e.g. "TRADE_OBSERVATION").
        top_k: Maximum number of results to return.
        include_shared: If True, also returns shared entries from other agents.

    Returns:
        List of wiki entry dicts ordered by relevance.
    """
    params: dict = {
        "search": query_text,
        "per_page": top_k,
        "include_shared": str(include_shared).lower(),
    }
    if category:
        params["category"] = category

    url = f"{config['phoenix_api_url']}/api/v2/agents/{config['agent_id']}/wiki"
    headers = {"Authorization": f"Bearer {config.get('phoenix_api_key', '')}"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        entries: list[dict] = data.get("entries", data) if isinstance(data, dict) else data
        logger.debug("Wiki query returned %d entries for %r", len(entries), query_text)
        return entries


async def get_wiki_summary(
    config: dict,
    categories: list[str] | None = None,
) -> dict:
    """Get a summary of wiki entries grouped by category count.

    Used in the morning briefing to show the agent's accumulated knowledge.

    Args:
        config: Agent config dict (phoenix_api_url, agent_id, phoenix_api_key).
        categories: Optional list of categories to include. None = all.

    Returns:
        Dict with structure::

            {
                "total": 42,
                "by_category": {
                    "TRADE_OBSERVATION": 20,
                    "MARKET_PATTERN": 8,
                    ...
                }
            }
    """
    url = f"{config['phoenix_api_url']}/api/v2/agents/{config['agent_id']}/wiki/summary"
    params: dict = {}
    if categories:
        params["categories"] = ",".join(categories)

    headers = {"Authorization": f"Bearer {config.get('phoenix_api_key', '')}"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# CLI entry-point (for manual testing / smoke-checks)
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Write a wiki entry to Phoenix API")
    parser.add_argument("--category", default="TRADE_OBSERVATION",
                        choices=[
                            "TRADE_OBSERVATION", "MARKET_PATTERN", "STRATEGY_LEARNING",
                            "RISK_NOTE", "SECTOR_INSIGHT", "INDICATOR_NOTE",
                            "EARNINGS_PLAYBOOK", "GENERAL",
                        ])
    parser.add_argument("--title", required=True, help="Short descriptive title")
    parser.add_argument("--content", required=True, help="Full knowledge content")
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--symbols", default="", help="Comma-separated ticker symbols")
    parser.add_argument("--confidence", type=float, default=0.5,
                        help="Confidence score 0.0-1.0")
    parser.add_argument("--agent-id", required=True, dest="agent_id")
    parser.add_argument("--api-url", required=True, dest="api_url",
                        help="Phoenix API base URL, e.g. http://localhost:8011")
    parser.add_argument("--api-key", default="", dest="api_key")
    parser.add_argument("--shared", action="store_true", default=None,
                        help="Override is_shared to True")
    args = parser.parse_args()

    config = {
        "phoenix_api_url": args.api_url,
        "agent_id": args.agent_id,
        "phoenix_api_key": args.api_key,
    }
    entry: dict = {
        "category": args.category,
        "title": args.title,
        "content": args.content,
        "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
        "symbols": [s.strip() for s in args.symbols.split(",") if s.strip()],
        "confidence_score": args.confidence,
    }
    if args.shared is not None:
        entry["is_shared"] = args.shared

    result = asyncio.run(write_wiki_entry(config, entry))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
