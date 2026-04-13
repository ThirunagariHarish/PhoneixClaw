FROM python:3.12-slim
WORKDIR /app
COPY services/automation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/automation/ .
ENV PYTHONPATH=/app
CMD ["python", "-m", "src.main"]
