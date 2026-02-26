# syntax=docker/dockerfile:1
FROM python:3.13-slim AS builder
WORKDIR /app
COPY shared/requirements-base.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements-base.txt
COPY services/source-orchestrator/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements.txt

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY shared/ /app/shared/
COPY services/source-orchestrator/ /app/services/source-orchestrator/
COPY services/discord-ingestor/ /app/services/discord-ingestor/
RUN ln -s /app/services/source-orchestrator /app/services/source_orchestrator && \
    ln -s /app/services/discord-ingestor /app/services/discord_ingestor && \
    touch /app/services/__init__.py
ENV PYTHONPATH=/app
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/health')" || exit 1
CMD ["python", "services/source-orchestrator/main.py"]
