FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY services/execution/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
COPY shared/ shared/
COPY services/__init__.py services/
COPY services/execution/ services/execution/
ENV PYTHONPATH=/app
EXPOSE 8020
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8020/health || exit 1
CMD ["uvicorn", "services.execution.src.main:app", "--host", "0.0.0.0", "--port", "8020"]
