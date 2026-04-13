FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/backtesting/requirements.txt /app/services/backtesting/requirements.txt
RUN pip install --no-cache-dir -r /app/services/backtesting/requirements.txt

COPY shared/ /app/shared/
COPY agents/backtesting/ /app/agents/backtesting/
COPY services/__init__.py /app/services/__init__.py
COPY services/backtesting/ /app/services/backtesting/

RUN mkdir -p /app/data/backtests

ENV PYTHONPATH=/app
EXPOSE 8085

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8085/health || exit 1

CMD ["uvicorn", "services.backtesting.src.main:app", "--host", "0.0.0.0", "--port", "8085"]
