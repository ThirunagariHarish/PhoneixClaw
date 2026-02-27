import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from shared.graceful_shutdown import shutdown
from shared.metrics import create_metrics_route

SERVICE_NAME = "strategy-agent"
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class ParseRequest(BaseModel):
    strategy_text: str


class BacktestRequest(BaseModel):
    strategy_text: str
    parsed_config: dict = {}
    ticker: str = "SPY"
    period_years: int = 2


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("%s ready", SERVICE_NAME)
    yield
    await shutdown.run_cleanup()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)
create_metrics_route(app)


@app.get("/health")
async def health():
    return {"status": "ready", "service": SERVICE_NAME}


@app.post("/parse")
async def parse(req: ParseRequest):
    from services.strategy_agent.src.parser import parse_strategy
    result = await parse_strategy(req.strategy_text)
    return {"parsed_config": result}


@app.post("/backtest")
async def backtest(req: BacktestRequest):
    from services.strategy_agent.src.backtest_engine import run_backtest
    from services.strategy_agent.src.benchmark_comparer import compare_with_benchmarks
    from services.strategy_agent.src.data_fetcher import fetch_historical_data
    from services.strategy_agent.src.parser import parse_strategy
    from services.strategy_agent.src.report_generator import generate_report

    config = req.parsed_config
    if not config:
        config = await parse_strategy(req.strategy_text)

    ticker = config.get("ticker") or req.ticker
    data = await fetch_historical_data(ticker, req.period_years)

    if data.empty:
        return {"error": f"No historical data available for {ticker}"}

    backtest_result = run_backtest(data, config)
    benchmarks = await compare_with_benchmarks(backtest_result, ticker, req.period_years)
    report = await generate_report(req.strategy_text, config, backtest_result, benchmarks)

    return {
        "strategy_text": req.strategy_text,
        "parsed_config": config,
        "ticker": ticker,
        "report": report,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8025)
