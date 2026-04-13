FROM python:3.12-slim
WORKDIR /app
COPY services/broker-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ shared/
COPY services/__init__.py services/
COPY services/broker-gateway/ services/broker-gateway/
RUN mkdir -p /app/data/.tokens
ENV PYTHONPATH=/app
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8040/health')" || exit 1
EXPOSE 8040
CMD ["uvicorn", "services.broker_gateway.src.main:app", "--host", "0.0.0.0", "--port", "8040"]
