FROM python:3.12-slim
WORKDIR /app
COPY services/ws-gateway/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
COPY services/ws-gateway/ .
ENV PYTHONPATH=/app
EXPOSE 8031
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('localhost', 8031)); s.close()" || exit 1
CMD ["python", "-m", "src.main"]
