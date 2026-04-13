"""
Global monitor service entrypoint.
"""
from fastapi import FastAPI
from prometheus_client import generate_latest
from starlette.responses import Response

app = FastAPI(title="Phoenix Global Monitor", version="1.0.0")


@app.get("/health")
async def health():
    return {"status": "ready", "service": "phoenix-global-monitor"}


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8052)
