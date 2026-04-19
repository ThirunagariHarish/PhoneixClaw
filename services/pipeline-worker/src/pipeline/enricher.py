"""Feature enrichment via HTTP call to the feature-pipeline service."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def enrich_signal(
    ticker: str,
    http_client: httpx.AsyncClient,
    feature_url: str,
) -> dict:
    """GET features from feature-pipeline. Returns empty dict on failure (non-blocking)."""
    try:
        resp = await http_client.get(
            f"{feature_url}/features/{ticker}",
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.debug("Enriched %s with %d features", ticker, len(data))
        return data
    except Exception as exc:
        logger.warning("Feature enrichment failed for %s: %s", ticker, exc)
        return {}
