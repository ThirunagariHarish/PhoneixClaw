FROM python:3.12-slim
WORKDIR /app
COPY services/feature-extraction/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
COPY shared/ shared/
COPY services/__init__.py services/
COPY agents/backtesting/tools/enrich.py agents/backtesting/tools/
COPY services/feature-extraction/ services/feature-extraction/
ENV PYTHONPATH=/app
CMD ["python", "-m", "services.feature_extraction.src.main"]
