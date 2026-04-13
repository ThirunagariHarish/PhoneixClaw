FROM python:3.12-slim
WORKDIR /app
COPY services/automation/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
COPY services/automation/ .
ENV PYTHONPATH=/app
CMD ["python", "-m", "src.main"]
