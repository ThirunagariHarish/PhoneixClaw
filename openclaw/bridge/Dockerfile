# OpenClaw Bridge Service. M1.7.
FROM python:3.12-slim
WORKDIR /app
COPY openclaw/bridge/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
COPY openclaw/bridge/src/ ./src/
ENV PYTHONPATH=/app
ENV AGENTS_ROOT=/data/agents
EXPOSE 18800
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "18800"]
