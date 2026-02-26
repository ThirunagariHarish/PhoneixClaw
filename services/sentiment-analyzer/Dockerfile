# syntax=docker/dockerfile:1
FROM python:3.13-slim AS builder
WORKDIR /app
COPY shared/requirements-base.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements-base.txt
COPY services/sentiment-analyzer/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements.txt

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY shared/ /app/shared/
COPY services/sentiment-analyzer/ /app/services/sentiment-analyzer/
RUN ln -s /app/services/sentiment-analyzer /app/services/sentiment_analyzer && touch /app/services/__init__.py
ENV PYTHONPATH=/app
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8021/health')" || exit 1
CMD ["python", "services/sentiment-analyzer/main.py"]
