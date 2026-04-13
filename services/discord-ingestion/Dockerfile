FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY services/discord-ingestion/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
COPY shared/ shared/
COPY services/__init__.py services/
COPY services/discord-ingestion/ services/discord-ingestion/
ENV PYTHONPATH=/app
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8060/health || exit 1
EXPOSE 8060
CMD ["uvicorn", "services.discord_ingestion.src.main:app", "--host", "0.0.0.0", "--port", "8060"]
