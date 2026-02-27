import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.api_gateway.src.middleware import JWTMiddleware
from services.api_gateway.src.routes.accounts import router as accounts_router
from services.api_gateway.src.routes.admin import router as admin_router
from services.api_gateway.src.routes.advanced_pipelines import router as advanced_pipelines_router
from services.api_gateway.src.routes.backtest import router as backtest_router
from services.api_gateway.src.routes.board import router as board_router
from services.api_gateway.src.routes.chat import router as chat_router
from services.api_gateway.src.routes.chat import set_kafka_producer
from services.api_gateway.src.routes.mappings import router as mappings_router
from services.api_gateway.src.routes.messages import router as messages_router
from services.api_gateway.src.routes.metrics import router as metrics_router
from services.api_gateway.src.routes.models import router as models_router
from services.api_gateway.src.routes.news import router as news_router
from services.api_gateway.src.routes.notifications import router as notifications_router
from services.api_gateway.src.routes.pipelines import ai_router
from services.api_gateway.src.routes.pipelines import router as pipelines_router
from services.api_gateway.src.routes.positions import router as positions_router
from services.api_gateway.src.routes.sentiment import router as sentiment_router
from services.api_gateway.src.routes.sources import router as sources_router
from services.api_gateway.src.routes.strategies import router as strategies_router
from services.api_gateway.src.routes.system import router as system_router
from services.api_gateway.src.routes.trades import router as trades_router
from services.api_gateway.src.routes.watchlist import router as watchlist_router
from services.api_gateway.src.websocket import router as ws_router
from services.api_gateway.src.websocket import run_ws_consumer
from services.auth_service.src.auth import router as auth_router
from shared.graceful_shutdown import shutdown
from shared.metrics import create_metrics_route

SERVICE_NAME = "api-gateway"
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


_kafka_producer = None


async def _run_migrations():
    """Run DB schema creation and any needed migrations."""
    import sqlalchemy as sa

    from shared.models.database import engine, init_db

    await init_db()
    migrations = [
        "ALTER TABLE trades ALTER COLUMN trading_account_id DROP NOT NULL",
        # ── Ensure all User model columns exist ──
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS name VARCHAR(100)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone VARCHAR(50) NOT NULL DEFAULT 'UTC'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS notification_prefs JSONB NOT NULL DEFAULT '{\"email_enabled\": true}'::jsonb",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(30) NOT NULL DEFAULT 'trader'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE channels ADD COLUMN IF NOT EXISTS guild_id VARCHAR(100)",
        "ALTER TABLE channels ADD COLUMN IF NOT EXISTS guild_name VARCHAR(200)",
        "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS server_id VARCHAR(100)",
        "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS server_name VARCHAR(200)",
        "UPDATE trades SET status = 'IN_PROGRESS' WHERE status = 'APPROVED'",
        "DELETE FROM chat_messages WHERE created_at < '2026-02-21'",
        "DELETE FROM trades WHERE created_at < '2026-02-21'",
        "DELETE FROM positions WHERE opened_at < '2026-02-21'",
        "DELETE FROM raw_messages WHERE created_at < '2026-02-21'",
        "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS data_purpose VARCHAR(20) NOT NULL DEFAULT 'trades'",
        # ── Phase 2 column additions ──
        "ALTER TABLE trade_pipelines ADD COLUMN IF NOT EXISTS pipeline_type VARCHAR(20) NOT NULL DEFAULT 'trade'",
        "ALTER TABLE trade_pipelines ADD COLUMN IF NOT EXISTS trigger_config JSONB NOT NULL DEFAULT '{}'::jsonb",
        (
            "ALTER TABLE trade_pipelines ADD COLUMN IF NOT EXISTS"
            " market_hours_mode VARCHAR(20) NOT NULL DEFAULT 'regular_only'"
        ),
        # ── Phase 2 new tables ──
        """CREATE TABLE IF NOT EXISTS user_watchlist (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            ticker VARCHAR(10) NOT NULL,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(user_id, ticker)
        )""",
        """CREATE TABLE IF NOT EXISTS model_registry (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) NOT NULL UNIQUE,
            model_type VARCHAR(30) NOT NULL,
            provider VARCHAR(30) NOT NULL,
            model_identifier VARCHAR(200) NOT NULL,
            version VARCHAR(30),
            description TEXT,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            input_schema JSONB,
            output_schema JSONB,
            status VARCHAR(20) NOT NULL DEFAULT 'available',
            health_status VARCHAR(20) NOT NULL DEFAULT 'unknown',
            last_health_check TIMESTAMPTZ,
            performance_metrics JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        """CREATE TABLE IF NOT EXISTS sentiment_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            data_source_id UUID REFERENCES data_sources(id) ON DELETE SET NULL,
            channel_name VARCHAR(200),
            author VARCHAR(200),
            content TEXT NOT NULL,
            ticker VARCHAR(10),
            sentiment_label VARCHAR(20),
            sentiment_score NUMERIC(6,4),
            confidence NUMERIC(5,4),
            source_message_id VARCHAR(100),
            raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            message_timestamp TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_sentiment_msg_ticker ON sentiment_messages(ticker, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_sentiment_msg_user ON sentiment_messages(user_id, created_at)",
        """CREATE TABLE IF NOT EXISTS ticker_sentiment (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ticker VARCHAR(10) NOT NULL,
            period_start TIMESTAMPTZ NOT NULL,
            period_end TIMESTAMPTZ NOT NULL,
            sentiment_label VARCHAR(20) NOT NULL,
            sentiment_score NUMERIC(6,4) NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0,
            bullish_count INTEGER NOT NULL DEFAULT 0,
            bearish_count INTEGER NOT NULL DEFAULT 0,
            neutral_count INTEGER NOT NULL DEFAULT 0,
            mention_change_pct NUMERIC(8,2),
            sources JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(ticker, period_start)
        )""",
        """CREATE TABLE IF NOT EXISTS sentiment_alerts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            ticker VARCHAR(10),
            alert_type VARCHAR(30) NOT NULL,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            last_triggered_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        """CREATE TABLE IF NOT EXISTS news_headlines (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_api VARCHAR(30) NOT NULL,
            title TEXT NOT NULL,
            summary TEXT,
            url TEXT,
            image_url TEXT,
            author VARCHAR(200),
            tickers JSONB NOT NULL DEFAULT '[]'::jsonb,
            category VARCHAR(50),
            sentiment_label VARCHAR(20),
            sentiment_score NUMERIC(6,4),
            importance_score NUMERIC(5,2),
            cluster_id VARCHAR(100),
            cluster_size INTEGER NOT NULL DEFAULT 1,
            published_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_news_created ON news_headlines(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_news_cluster ON news_headlines(cluster_id)",
        """CREATE TABLE IF NOT EXISTS news_connections (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            source_api VARCHAR(30) NOT NULL,
            display_name VARCHAR(100) NOT NULL,
            api_key_encrypted BYTEA,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            last_poll_at TIMESTAMPTZ,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(user_id, source_api)
        )""",
        """CREATE TABLE IF NOT EXISTS advanced_pipelines (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            flow_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            last_run_at TIMESTAMPTZ,
            error_message TEXT,
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        """CREATE TABLE IF NOT EXISTS advanced_pipeline_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pipeline_id UUID NOT NULL REFERENCES advanced_pipelines(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            flow_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            change_summary TEXT,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(pipeline_id, version)
        )""",
        """CREATE TABLE IF NOT EXISTS strategy_models (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            strategy_text TEXT NOT NULL,
            parsed_config JSONB NOT NULL DEFAULT '{}'::jsonb,
            features JSONB NOT NULL DEFAULT '[]'::jsonb,
            backtest_summary JSONB,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            deployed_pipeline_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        """CREATE TABLE IF NOT EXISTS option_analysis_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            ticker VARCHAR(10) NOT NULL,
            direction VARCHAR(10) NOT NULL,
            input_context JSONB NOT NULL DEFAULT '{}'::jsonb,
            recommended_contracts JSONB NOT NULL DEFAULT '[]'::jsonb,
            multi_leg_suggestions JSONB NOT NULL DEFAULT '[]'::jsonb,
            gex_snapshot JSONB,
            rationale TEXT,
            outcome JSONB,
            user_feedback VARCHAR(20),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_option_analysis_ticker ON option_analysis_log(ticker, created_at)",
        """CREATE TABLE IF NOT EXISTS ai_trade_decisions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            pipeline_id UUID,
            trigger_type VARCHAR(30) NOT NULL,
            trigger_data JSONB NOT NULL DEFAULT '{}'::jsonb,
            ticker VARCHAR(10),
            decision VARCHAR(20) NOT NULL,
            decision_rationale TEXT,
            trade_params JSONB,
            option_analysis_id UUID,
            trade_id UUID,
            outcome JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ai_decision_user ON ai_trade_decisions(user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_ai_decision_ticker ON ai_trade_decisions(ticker, created_at)",
        # ── Seed model_registry with system models ──
        """INSERT INTO model_registry (
            id, name, model_type, provider, model_identifier,
            version, description, config, status, health_status
        ) VALUES
            (gen_random_uuid(), 'FinBERT', 'sentiment',
             'huggingface', 'ProsusAI/finbert', '1.0',
             'Financial sentiment analysis model'
             ' (3-class: positive/neutral/negative,'
             ' mapped to 5-class)',
             '{"max_length": 512, "device": "cpu"}'::jsonb,
             'available', 'unknown'),
            (gen_random_uuid(), 'Mistral 7B', 'llm', 'ollama',
             'mistral', '7b',
             'General-purpose LLM for trade analysis,'
             ' summaries, and strategy parsing',
             '{"temperature": 0.7, "context_length": 8192}'::jsonb,
             'available', 'unknown'),
            (gen_random_uuid(), 'Llama 3.1 8B', 'llm', 'ollama',
             'llama3.1', '8b',
             'Fallback LLM model for trade analysis and reasoning',
             '{"temperature": 0.7, "context_length": 8192}'::jsonb,
             'available', 'unknown'),
            (gen_random_uuid(), 'Option Chain Analyzer',
             'option_analyzer', 'custom',
             'option-chain-analyzer', '1.0',
             'Analyzes Unusual Whales option chains'
             ' to recommend optimal contracts',
             '{"top_k": 3}'::jsonb, 'available', 'unknown'),
            (gen_random_uuid(), 'AI Trade Recommender',
             'trade_recommender', 'custom',
             'ai-trade-recommender', '1.0',
             'Converts sentiment/news signals into'
             ' trade recommendations via LLM + UW',
             '{}'::jsonb, 'available', 'unknown'),
            (gen_random_uuid(), 'Strategy Agent', 'strategy',
             'custom', 'strategy-agent', '1.0',
             'Natural language strategy parser and backtester',
             '{}'::jsonb, 'available', 'unknown'),
            (gen_random_uuid(), 'spaCy NER', 'nlp', 'spacy',
             'en_core_web_sm', '3.x',
             'Named entity recognition for ticker'
             ' and financial entity extraction',
             '{}'::jsonb, 'available', 'unknown')
        ON CONFLICT (name) DO NOTHING""",
        "ALTER TABLE ai_trade_decisions ALTER COLUMN user_id DROP NOT NULL",
        # ── Email verification & MFA ──
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_expires TIMESTAMPTZ",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_secret VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ",
        "UPDATE users SET email_verified = TRUE WHERE email_verified = FALSE",
    ]
    for sql in migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(sa.text(sql))
        except Exception:
            pass
    logger.info("Database schema ready")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _kafka_producer
    try:
        await _run_migrations()
    except Exception:
        logger.warning("DB migration step skipped (may already be applied)", exc_info=True)
    try:
        from shared.kafka_utils.producer import KafkaProducerWrapper

        _kafka_producer = KafkaProducerWrapper()
        await _kafka_producer.start()
        set_kafka_producer(_kafka_producer)
        logger.info("Kafka producer initialized for chat")
    except Exception:
        logger.warning("Kafka producer unavailable — chat messages will not be routed to trade pipeline")
    import asyncio

    _ws_task = None
    _retention_task = None
    try:
        _ws_task = asyncio.create_task(run_ws_consumer())
        logger.info("WebSocket consumer started")
    except Exception:
        logger.warning("WebSocket consumer not started")

    async def _retention_loop():
        from shared.retention import purge_old_records
        while True:
            await asyncio.sleep(86400)
            try:
                results = await purge_old_records()
                logger.info("Retention purge completed: %s", results)
            except Exception:
                logger.exception("Retention purge failed")

    try:
        _retention_task = asyncio.create_task(_retention_loop())
    except Exception:
        pass
    logger.info("%s ready", SERVICE_NAME)
    yield
    if _retention_task:
        _retention_task.cancel()
    if _ws_task:
        _ws_task.cancel()
    if _kafka_producer:
        await _kafka_producer.stop()
    await shutdown.run_cleanup()


app = FastAPI(title="Phoenix Trade Bot API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(JWTMiddleware)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(accounts_router)
app.include_router(backtest_router)
app.include_router(board_router)
app.include_router(sources_router)
app.include_router(pipelines_router)
app.include_router(ai_router)
app.include_router(mappings_router)
app.include_router(trades_router)
app.include_router(positions_router)
app.include_router(metrics_router)
app.include_router(notifications_router)
app.include_router(system_router)
app.include_router(chat_router)
app.include_router(messages_router)
app.include_router(advanced_pipelines_router)
app.include_router(news_router)
app.include_router(sentiment_router)
app.include_router(strategies_router)
app.include_router(models_router)
app.include_router(watchlist_router)
app.include_router(ws_router)


create_metrics_route(app)


@app.get("/health")
async def health():
    return {"status": "ready", "service": SERVICE_NAME}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8011)
