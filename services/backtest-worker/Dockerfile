FROM python:3.12-slim
WORKDIR /app

# Install deps
COPY services/backtest-worker/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy shared libraries and service code
COPY shared/ shared/
COPY services/__init__.py services/
COPY services/backtest-worker/ services/backtest-worker/
COPY apps/api/src/services/backtest_orchestrator.py apps/api/src/services/
COPY agents/backtesting/tools/ agents/backtesting/tools/

ENV PYTHONPATH=/app

# No healthcheck — this is a long-running worker, not an HTTP server
CMD ["python3", "-m", "services.backtest_worker.src.main"]
