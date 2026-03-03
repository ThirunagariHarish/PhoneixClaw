# OpenClaw Bridge Service. M1.7.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app
ENV AGENTS_ROOT=/data/agents

RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY requirements.txt .

EXPOSE 18800
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "18800"]
