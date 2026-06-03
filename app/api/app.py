"""FastAPI application factory.

`create_app()` builds the configured `FastAPI` instance and loads `get_settings()`
*at construction time* (not in a lifespan hook), so a missing required env var
raises immediately — failing both `uv run uvicorn app.main:app` and any
`create_app()` caller fast (E1·P1; ARCHITECTURE §1).

Routers (health/errors in E1·P2, endpoints in later epics) are attached here via
`include_router`; the factory stays free of side effects beyond config validation.
"""

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.routes import health
from app.core.settings import Settings, get_settings


def create_app() -> FastAPI:
    """Return a configured FastAPI app, validating settings at startup."""
    settings: Settings = get_settings()

    app = FastAPI(
        title="Coach App Backend",
        version="0.1.0",
        summary="Deterministic + LLM health-coaching briefs.",
    )
    # Keep a handle on validated config for routers/dependencies added later.
    app.state.settings = settings

    # Every non-2xx response renders the single error envelope (E1·P2).
    register_exception_handlers(app)

    # Routes: unauthenticated /health + the auth-gated /probe (E1·P2).
    app.include_router(health.router)

    return app
