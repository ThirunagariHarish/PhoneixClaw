FROM python:3.12-slim
WORKDIR /app
COPY services/orchestrator/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
COPY shared/ shared/
COPY services/__init__.py services/
COPY services/orchestrator/ services/orchestrator/
ENV PYTHONPATH=/app
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "print('ok')" || exit 1
CMD ["uvicorn", "services.orchestrator.src.main:app", "--host", "0.0.0.0", "--port", "8042"]
