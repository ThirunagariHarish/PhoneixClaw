# syntax=docker/dockerfile:1

# ─── Dependencies stage (cached unless requirements.txt changes) ─────
FROM python:3.12-slim AS deps
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# ─── Models stage (cached unless deps change) ────────────────────────
FROM deps AS models

RUN python -m spacy download en_core_web_sm

RUN python -c "from transformers import AutoModelForSequenceClassification, AutoTokenizer; \
    AutoTokenizer.from_pretrained('ProsusAI/finbert'); \
    AutoModelForSequenceClassification.from_pretrained('ProsusAI/finbert')"

RUN python -c "from transformers import AutoModelForSeq2SeqLM, AutoTokenizer; \
    AutoTokenizer.from_pretrained('google/flan-t5-small'); \
    AutoModelForSeq2SeqLM.from_pretrained('google/flan-t5-small')"

# ─── Runtime stage ───────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

COPY --from=models /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=models /usr/local/bin /usr/local/bin
COPY --from=models /root/.cache/huggingface /root/.cache/huggingface

COPY . .

EXPOSE 8020

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8020"]
