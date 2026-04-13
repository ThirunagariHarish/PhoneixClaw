FROM python:3.12-slim
WORKDIR /app
COPY services/backtest-runner/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY shared/ /app/shared/
COPY services/__init__.py /app/services/__init__.py
COPY services/backtest-runner/ .
ENV PYTHONPATH=/app
EXPOSE 8022
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8022/health || exit 1
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8022"]
