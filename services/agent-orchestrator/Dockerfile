FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg openssh-client && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/agent-orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ shared/
COPY agents/ agents/
COPY services/__init__.py services/
COPY services/agent-orchestrator/ services/agent-orchestrator/
RUN mkdir -p /app/data/live_agents
ENV PYTHONPATH=/app
EXPOSE 8070
CMD ["uvicorn", "services.agent_orchestrator.src.main:app", "--host", "0.0.0.0", "--port", "8070"]
