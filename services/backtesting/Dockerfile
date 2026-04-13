# ── Node + Claude Code layer ──────────────────────────────────────────────
FROM python:3.12-slim AS node-base

RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    apt-get purge -y gnupg && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# ── Python deps ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS deps
WORKDIR /app
COPY services/backtesting/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install -r requirements.txt

# ── Runtime ──────────────────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

COPY --from=node-base /usr/bin/node /usr/bin/node
COPY --from=node-base /usr/lib/node_modules /usr/lib/node_modules
RUN ln -sf /usr/lib/node_modules/.bin/claude /usr/local/bin/claude

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY --from=deps /install /usr/local
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
