# syntax=docker/dockerfile:1
FROM python:3.13-slim AS builder
WORKDIR /app
COPY shared/requirements-base.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements-base.txt
COPY services/api-gateway/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements.txt
COPY services/auth-service/requirements.txt auth-requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r auth-requirements.txt

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY shared/ /app/shared/
COPY services/api-gateway/ /app/services/api-gateway/
COPY services/auth-service/ /app/services/auth-service/
COPY services/trade-parser/ /app/services/trade-parser/
RUN ln -s /app/services/api-gateway /app/services/api_gateway && \
    ln -s /app/services/auth-service /app/services/auth_service && \
    ln -s /app/services/trade-parser /app/services/trade_parser
RUN touch /app/services/__init__.py
ENV PYTHONPATH=/app
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8011/health')" || exit 1
CMD ["python", "services/api-gateway/main.py"]
