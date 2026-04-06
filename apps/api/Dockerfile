# ── Stage 1: Dependencies ────────────────────────────────────────────────
FROM python:3.12-slim AS deps

WORKDIR /app

COPY pyproject.toml .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
    -e . 2>/dev/null || \
    pip install --extra-index-url https://download.pytorch.org/whl/cpu -e .

# ── Stage 2: Runtime ────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl openssh-client gnupg libgomp1 && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 -s /bin/bash phoenix

COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY shared/ shared/
COPY apps/api/ apps/api/
COPY agents/ agents/
COPY scripts/ scripts/
COPY pyproject.toml .

RUN pip install --no-deps -e . 2>/dev/null || true

RUN mkdir -p /app/data && chown -R phoenix:phoenix /app/data

ENV PYTHONPATH=/app
EXPOSE 8011

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8011/health || exit 1

CMD ["uvicorn", "apps.api.src.main:app", "--host", "0.0.0.0", "--port", "8011"]
