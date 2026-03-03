"""
Phoenix v2 Backend API — FastAPI application entrypoint.

M1.1: Minimal app with health endpoint. M1.3: Auth routes and JWT middleware.
Reference: ImplementationPlan.md Section 2, Section 5 M1.1, M1.3.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.src.config import settings
from apps.api.src.middleware.auth import JWTAuthMiddleware
from apps.api.src.routes import auth as auth_routes

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown. DB/Redis connections in M1.3+."""
    yield


app = FastAPI(
    title="Phoenix v2 API",
    description="Backend API for Phoenix multi-agent trading platform",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(JWTAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)


@app.get("/health")
async def health() -> dict:
    """Health check for load balancers and CI. Returns 200 when service is ready."""
    return {"status": "ready", "service": "phoenix-api"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.api.src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
