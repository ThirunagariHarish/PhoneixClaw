# ── Stage 1: Node + Claude Code (cached independently) ───────────────────
FROM python:3.12-slim AS node-base

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    apt-get purge -y gnupg && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# ── Stage 2: Python dependencies ─────────────────────────────────────────
FROM python:3.12-slim AS deps

ARG INSTALL_ML=true

WORKDIR /app
COPY pyproject.toml .
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_ML" = "true" ]; then \
        pip install --extra-index-url https://download.pytorch.org/whl/cpu -e ".[ml]"; \
    else \
        pip install -e .; \
    fi

# ── Stage 3: Runtime ─────────────────────────────────────────────────────
FROM python:3.12-slim

ARG INSTALL_ML=true

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl openssh-client && \
    if [ "$INSTALL_ML" = "true" ]; then \
        apt-get install -y --no-install-recommends libgomp1; \
    fi && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 -s /bin/bash phoenix

COPY --from=node-base /usr/bin/node /usr/bin/node
COPY --from=node-base /usr/lib/node_modules /usr/lib/node_modules
RUN ln -sf /usr/lib/node_modules/.bin/claude /usr/local/bin/claude

COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY shared/ shared/
COPY apps/api/ apps/api/
COPY agents/ agents/
COPY services/ services/
COPY scripts/ scripts/
COPY pyproject.toml .

RUN pip install --no-deps -e . 2>/dev/null || true

RUN mkdir -p /app/data && chown -R phoenix:phoenix /app/data

COPY apps/api/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PYTHONPATH=/app
EXPOSE 8011

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8011/health/lite || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
