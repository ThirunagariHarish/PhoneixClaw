import asyncio
import logging
import sys
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from shared.graceful_shutdown import shutdown
from shared.metrics import create_metrics_route
from shared.unusual_whales.client import UnusualWhalesClient

SERVICE_NAME = "option-chain-analyzer"
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class AnalyzeRequest(BaseModel):
    ticker: str
    direction: str = "bullish"
    context: dict = {}


_uw_client: UnusualWhalesClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _uw_client
    _uw_client = UnusualWhalesClient()
    logger.info("%s ready", SERVICE_NAME)

    async def _daily_outcome_check():
        while True:
            await asyncio.sleep(86400)
            try:
                from services.option_chain_analyzer.src.outcome_tracker import check_past_recommendations
                await check_past_recommendations()
            except Exception:
                logger.exception("Outcome tracker failed")

    task = asyncio.create_task(_daily_outcome_check())
    yield
    task.cancel()
    await shutdown.run_cleanup()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)
create_metrics_route(app)


@app.get("/health")
async def health():
    return {"status": "ready", "service": SERVICE_NAME}


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    from services.option_chain_analyzer.src.analyzer import analyze_option_chain
    from services.option_chain_analyzer.src.strategy_suggester import suggest_strategy

    results = await analyze_option_chain(_uw_client, req.ticker, req.direction)
    strategies = suggest_strategy(req.ticker, req.direction)

    from shared.models.database import async_session_factory
    from shared.models.trade import OptionAnalysisLog

    contracts_data = []
    for r in results:
        c = r.contract
        contracts_data.append({
            "symbol": c.symbol,
            "strike": c.strike,
            "expiration": c.expiration,
            "option_type": c.option_type,
            "score": r.score,
            "rationale": r.rationale,
            "open_interest": c.open_interest,
            "volume": c.volume,
            "bid": c.bid,
            "ask": c.ask,
            "delta": c.delta,
            "implied_volatility": c.implied_volatility,
        })

    try:
        from shared.llm.client import OllamaClient
        llm = OllamaClient()
        rationale_prompt = (
            f"Analyze the following option contracts for {req.ticker} ({req.direction} outlook):\n"
            + "\n".join(r.rationale for r in results)
            + "\n\nProvide a concise 2-3 sentence recommendation."
        )
        ai_rationale = await llm.generate(
            prompt=rationale_prompt,
            system="You are an options trading analyst. Be concise and specific.",
        )
    except Exception:
        ai_rationale = None

    async with async_session_factory() as session:
        log = OptionAnalysisLog(
            id=uuid.uuid4(),
            ticker=req.ticker,
            direction=req.direction,
            input_context=req.context,
            recommended_contracts=contracts_data,
            multi_leg_suggestions=strategies,
            rationale=ai_rationale,
        )
        session.add(log)
        await session.commit()
        log_id = str(log.id)

    return {
        "analysis_id": log_id,
        "ticker": req.ticker,
        "direction": req.direction,
        "contracts": contracts_data,
        "strategies": strategies,
        "rationale": ai_rationale,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8024)
