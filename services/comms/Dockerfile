FROM python:3.12-slim
WORKDIR /app
COPY services/comms/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY shared/ shared/
COPY services/__init__.py services/
COPY services/comms/ services/comms/
ENV PYTHONPATH=/app
EXPOSE 8025
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8025/health || exit 1
CMD ["uvicorn", "services.comms.src.main:app", "--host", "0.0.0.0", "--port", "8025"]
