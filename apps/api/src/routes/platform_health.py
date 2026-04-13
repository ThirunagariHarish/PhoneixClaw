"""Platform Health API routes — aggregate health from all microservices.

Proxies health checks and key endpoints from the microservices layer
(feature-pipeline, inference-service, broker-gateway, discord-ingestion,
agent-orchestrator, prediction-monitor) into a single API surface.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/platform", tags=["platform-health"])

SERVICE_URLS: dict[str, str] = {
    "feature_pipeline": os.getenv(
        "FEATURE_PIPELINE_URL", "http://phoenix-feature-pipeline:8055"
    ),
    "inference_service": os.getenv(
        "INFERENCE_SERVICE_URL", "http://phoenix-inference-service:8045"
    ),
    "broker_gateway": os.getenv(
        "BROKER_GATEWAY_URL", "http://phoenix-broker-gateway:8040"
    ),
    "discord_ingestion": os.getenv(
        "DISCORD_INGESTION_URL", "http://phoenix-discord-ingestion:8060"
    ),
    "agent_orchestrator": os.getenv(
        "AGENT_ORCHESTRATOR_URL", "http://phoenix-agent-orchestrator:8070"
    ),
    "prediction_monitor": os.getenv(
        "PREDICTION_MONITOR_URL", "http://phoenix-prediction-monitor:8075"
    ),
    "backtesting": os.getenv(
        "BACKTESTING_URL", "http://phoenix-backtesting:8085"
    ),
}

HEALTH_TIMEOUT = 3.0


async def _check_service(
    client: httpx.AsyncClient, name: str, base_url: str
) -> dict[str, Any]:
    """Call /health on a single service, returning a status dict."""
    try:
        resp = await client.get(f"{base_url}/health", timeout=HEALTH_TIMEOUT)
        data = resp.json() if resp.status_code == 200 else {}
        return {
            "status": "ok" if resp.status_code == 200 else "degraded",
            "http_status": resp.status_code,
            "url": base_url,
            **data,
        }
    except httpx.TimeoutException:
        return {"status": "timeout", "url": base_url}
    except Exception as exc:
        logger.debug("Health check failed for %s: %s", name, exc)
        return {"status": "unreachable", "url": base_url, "error": str(exc)[:200]}


@router.get("/health")
async def platform_health() -> dict[str, Any]:
    """Aggregated health of all platform microservices."""
    async with httpx.AsyncClient() as client:
        results: dict[str, Any] = {}
        for name, url in SERVICE_URLS.items():
            results[name] = await _check_service(client, name, url)

    all_ok = all(s.get("status") == "ok" for s in results.values())
    return {
        "overall": "ok" if all_ok else "degraded",
        "services": results,
    }


@router.get("/features/{ticker}")
async def get_features(ticker: str) -> Any:
    """Proxy to feature-pipeline for ticker features."""
    base = SERVICE_URLS["feature_pipeline"]
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{base}/features/{ticker}", timeout=HEALTH_TIMEOUT * 3
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.text[:500],
                )
            return resp.json()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Feature pipeline unreachable: {exc}",
            ) from exc


@router.get("/predictions/{agent_id}")
async def get_predictions(agent_id: str) -> Any:
    """Proxy to prediction-monitor for agent predictions."""
    base = SERVICE_URLS["prediction_monitor"]
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{base}/predictions/{agent_id}", timeout=HEALTH_TIMEOUT * 3
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.text[:500],
                )
            return resp.json()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Prediction monitor unreachable: {exc}",
            ) from exc


@router.get("/accuracy/{agent_id}")
async def get_accuracy(agent_id: str) -> Any:
    """Proxy to prediction-monitor for agent accuracy."""
    base = SERVICE_URLS["prediction_monitor"]
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{base}/accuracy/{agent_id}", timeout=HEALTH_TIMEOUT * 3
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.text[:500],
                )
            return resp.json()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Prediction monitor unreachable: {exc}",
            ) from exc


@router.get("/broker/status")
async def broker_status() -> Any:
    """Proxy to broker-gateway auth status."""
    base = SERVICE_URLS["broker_gateway"]
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{base}/auth/status", timeout=HEALTH_TIMEOUT * 3
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.text[:500],
                )
            return resp.json()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Broker gateway unreachable: {exc}",
            ) from exc
