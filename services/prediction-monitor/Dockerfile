FROM python:3.12-slim
WORKDIR /app
COPY services/prediction-monitor/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
COPY shared/ shared/
COPY services/__init__.py services/
COPY services/prediction-monitor/ services/prediction-monitor/
ENV PYTHONPATH=/app
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8075/health')" || exit 1
EXPOSE 8075
CMD ["uvicorn", "services.prediction_monitor.src.main:app", "--host", "0.0.0.0", "--port", "8075"]
