"""
Phoenix v2 Backend API — FastAPI application entrypoint.

M1.1: Minimal app with health endpoint. M1.3: Auth routes and JWT middleware.
Reference: ImplementationPlan.md Section 2, Section 5 M1.1, M1.3.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.src.config import settings
from apps.api.src.middleware.auth import JWTAuthMiddleware
from apps.api.src.middleware.error_handler import ErrorHandlerMiddleware
from apps.api.src.middleware.rate_limit import RateLimitMiddleware
from apps.api.src.middleware.logging import LoggingMiddleware
from apps.api.src.routes import auth as auth_routes
from apps.api.src.routes import connectors as connector_routes
from apps.api.src.routes import trades as trades_routes
from apps.api.src.routes import positions as positions_routes
from apps.api.src.routes import agents as agents_routes
from apps.api.src.routes import execution as execution_routes
from apps.api.src.routes import skills as skills_routes
from apps.api.src.routes import backtests as backtests_routes
from apps.api.src.routes import strategies as strategies_routes
from apps.api.src.routes import monitoring as monitoring_routes
from apps.api.src.routes import dev_agent as dev_agent_routes
from apps.api.src.routes import tasks as tasks_routes
from apps.api.src.routes import automations as automations_routes
from apps.api.src.routes import admin as admin_routes
from apps.api.src.routes import performance as performance_routes
from apps.api.src.routes import market as market_routes
from apps.api.src.routes import ws as ws_routes
from apps.api.src.routes import agent_learning as agent_learning_routes
from apps.api.src.routes import daily_signals as daily_signals_routes
from apps.api.src.routes import onchain_flow as onchain_flow_routes
from apps.api.src.routes import macro_pulse as macro_pulse_routes
from apps.api.src.routes import zero_dte as zero_dte_routes
from apps.api.src.routes import narrative_sentiment as narrative_sentiment_routes
from apps.api.src.routes import risk_compliance as risk_compliance_routes
from apps.api.src.routes import agent_messages as agent_messages_routes
from apps.api.src.routes import chat as chat_routes
from apps.api.src.routes import notifications as notifications_routes
from apps.api.src.routes import error_logs as error_logs_routes
from apps.api.src.routes import ai_expand as ai_expand_routes
from apps.api.src.routes import token_usage as token_usage_routes
from apps.api.src.routes import system_logs as system_logs_routes
from apps.api.src.routes import morning_routine as morning_routine_routes
from apps.api.src.routes import whatsapp_webhook as whatsapp_webhook_routes
from apps.api.src.routes import scheduler_status as scheduler_status_routes
from apps.api.src.routes import eod_analysis as eod_analysis_routes
from apps.api.src.routes import trade_signals as trade_signals_routes

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    import logging as _logging
    _log = _logging.getLogger(__name__)

    # Start scheduler (morning briefing, supervisor, EOD analysis, heartbeat)
    stop_scheduler_fn = None
    try:
        from apps.api.src.services.scheduler import start_scheduler, stop_scheduler
        start_scheduler()
        stop_scheduler_fn = stop_scheduler
    except Exception as exc:
        _log.exception("Failed to start scheduler: %s", exc)

    # Start message ingestion daemon (Discord listener → channel_messages + Redis)
    stop_ingestion_fn = None
    try:
        from apps.api.src.services.message_ingestion import start_ingestion, stop_ingestion
        await start_ingestion()
        stop_ingestion_fn = stop_ingestion
    except Exception as exc:
        _log.exception("Failed to start message ingestion: %s", exc)

    yield

    # Shutdown in reverse order
    if stop_ingestion_fn is not None:
        try:
            await stop_ingestion_fn()
        except Exception:
            _log.exception("Failed to stop ingestion")

    if stop_scheduler_fn is not None:
        try:
            await stop_scheduler_fn()
        except Exception:
            _log.exception("Failed to stop scheduler")


app = FastAPI(
    title="Phoenix v2 API",
    description="Backend API for Phoenix multi-agent trading platform",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(JWTAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(connector_routes.router)
app.include_router(trades_routes.router)
app.include_router(positions_routes.router)
app.include_router(agents_routes.router)
app.include_router(execution_routes.router)
app.include_router(skills_routes.router)
app.include_router(backtests_routes.router)
app.include_router(strategies_routes.router)
app.include_router(monitoring_routes.router)
app.include_router(dev_agent_routes.router)
app.include_router(tasks_routes.router)
app.include_router(automations_routes.router)
app.include_router(admin_routes.router)
app.include_router(performance_routes.router)
app.include_router(market_routes.router)
app.include_router(ws_routes.router)
app.include_router(daily_signals_routes.router)
app.include_router(agent_learning_routes.router)
app.include_router(onchain_flow_routes.router)
app.include_router(macro_pulse_routes.router)
app.include_router(zero_dte_routes.router)
app.include_router(narrative_sentiment_routes.router)
app.include_router(risk_compliance_routes.router)
app.include_router(agent_messages_routes.router)
app.include_router(chat_routes.router)
app.include_router(notifications_routes.router)
app.include_router(error_logs_routes.router)
app.include_router(ai_expand_routes.router)
app.include_router(token_usage_routes.router)
app.include_router(system_logs_routes.router)
app.include_router(morning_routine_routes.router)
app.include_router(whatsapp_webhook_routes.router)
app.include_router(scheduler_status_routes.router)
app.include_router(eod_analysis_routes.router)
app.include_router(trade_signals_routes.router)


@app.get("/health")
async def health() -> dict:
    """Health check for load balancers and CI. Returns 200 when service is ready."""
    return {"status": "ready", "service": "phoenix-api"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.api.src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
