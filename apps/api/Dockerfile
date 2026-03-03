# Phoenix v2 API — Production image.
# M1.1. Reference: ImplementationPlan.md Section 2.
# Build from repo root: docker build -f apps/api/Dockerfile .

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY apps/api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/ ./apps/
ENV PYTHONPATH=/app

EXPOSE 8011

CMD ["uvicorn", "apps.api.src.main:app", "--host", "0.0.0.0", "--port", "8011"]
