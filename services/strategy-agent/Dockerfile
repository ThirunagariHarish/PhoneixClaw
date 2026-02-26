# syntax=docker/dockerfile:1
FROM python:3.13-slim AS builder
WORKDIR /app
COPY shared/requirements-base.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements-base.txt
COPY services/strategy-agent/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements.txt

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY shared/ /app/shared/
COPY services/strategy-agent/ /app/services/strategy-agent/
RUN ln -s /app/services/strategy-agent /app/services/strategy_agent && touch /app/services/__init__.py
ENV PYTHONPATH=/app
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8025/health')" || exit 1
CMD ["python", "services/strategy-agent/main.py"]
