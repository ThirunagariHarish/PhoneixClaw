# Ollama AI Assist (Magic Wand)

The Phoenix dashboard uses a local Ollama model to expand short user notes into full descriptions (e.g. agent description, roles) when you click the magic wand next to a text field.

## 1. Install and run Ollama

**Option A — Host install**

- Install from [ollama.com](https://ollama.com) (macOS, Linux, Windows).
- Start Ollama (it runs as a service; default URL `http://localhost:11434`).

**Option B — Docker**

Add to your compose file (e.g. `infra/docker-compose.production.yml`):

```yaml
ollama:
  image: ollama/ollama:latest
  ports:
    - "11434:11434"
  volumes:
    - ollama_data:/root/.ollama
  # Optional: pull a model on first run via entrypoint or separate step

volumes:
  ollama_data:
```

Then run the stack and pull the model (see below).

## 2. Pull a small model for text expansion

Use a small model so responses are fast and resource use is low. Recommended:

- **llama3.2:1b** (default in the API): `ollama pull llama3.2:1b`
- **phi3:mini**: `ollama pull phi3:mini`

After pull, the model is used automatically by the Phoenix API.

## 3. Configure the Phoenix API

Set environment variables for the API (e.g. in `.env` or your deployment config):

- **OLLAMA_BASE_URL** — URL of the Ollama server (default: `http://localhost:11434`). In Docker, use the service name if Ollama is in the same compose (e.g. `http://ollama:11434`).
- **OLLAMA_EXPAND_MODEL** (optional) — Model used for the “expand” (magic wand) feature (default: `llama3.2:1b`). Use the same name you used in `ollama pull`.

## 4. Verify

- Open the dashboard, go to **Agents** → **New Agent** → **Basic Info**.
- Next to **Description**, click the magic wand, enter a short summary (e.g. “SPY scalper from Discord”), and click **Generate**.
- If Ollama is running and the model is pulled, the description field should fill with expanded text. If not, the UI will show that AI assist is unavailable (check API logs and Ollama).

## Troubleshooting

- **503 / “Ollama service is unavailable”** — Ollama is not running or not reachable at `OLLAMA_BASE_URL`. Start Ollama and ensure the API can reach it (firewall, Docker network).
- **Empty or failed response** — The model may not be pulled. Run `ollama pull llama3.2:1b` (or your chosen model) on the host where Ollama runs.
- **Slow first request** — The first request after startup may load the model into memory; subsequent requests are faster.
