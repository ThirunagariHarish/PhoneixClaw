# ── Build: install deps with pip cache ────────────────────────────────────
FROM python:3.12-slim AS builder
WORKDIR /app
COPY services/inference-service/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install -r requirements.txt

# ── Runtime ───────────────────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY shared/ shared/
COPY services/__init__.py services/
COPY services/inference-service/ services/inference-service/
ENV PYTHONPATH=/app
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8045/health')" || exit 1
EXPOSE 8045
CMD ["uvicorn", "services.inference_service.src.main:app", "--host", "0.0.0.0", "--port", "8045"]
