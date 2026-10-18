"""FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="LSE Pattern Lab",
    description=(
        "Local-first LSE equity research lab. No broker execution. "
        "Insufficient evidence is a valid output."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/")
def root() -> dict[str, str]:
    """Root redirect hint."""
    return {
        "app": "LSE Pattern Lab",
        "docs": "/docs",
        "health": "/api/health",
    }
