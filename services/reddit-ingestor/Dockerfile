# syntax=docker/dockerfile:1
FROM python:3.13-slim AS builder
WORKDIR /app
COPY shared/requirements-base.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements-base.txt

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY shared/ /app/shared/
COPY services/reddit-ingestor/ /app/services/reddit-ingestor/
ENV PYTHONPATH=/app
CMD ["python", "services/reddit-ingestor/main.py"]
