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
from app.api.routes import daily, health, profile, sync, weekly
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

    # Debug observability (default-off): when REQUEST_LOG_PATH is set, every
    # request/response pair — bodies included, auth headers redacted — is written
    # as a JSON line to a rotating file for post-hoc wire-level debugging.
    if settings.request_log_path:
        from app.api.request_logging import install_request_logging

        install_request_logging(app, settings)

    # Routes: unauthenticated /health + the auth-gated /probe (E1·P2).
    app.include_router(health.router)
    # Authenticated HealthKit ingest: POST /sync (E5·P2).
    app.include_router(sync.router)
    # Authenticated weekly brief get-or-generate: POST /brief/weekly (E10·P3).
    app.include_router(weekly.router)
    # Authenticated daily brief get-or-generate: POST /brief/daily (E11·P3).
    app.include_router(daily.router)
    # Authenticated read-only profile constants: GET /profile (E14·P1).
    app.include_router(profile.router)

    # Local-testing escape hatch (default-off): when BRIEF_FIXTURES is set, swap the
    # LLM-backed brief generators for static-fixture ones so the brief endpoints serve
    # canned responses with no Anthropic call. Config-gated dependency_overrides — the
    # same seam the test suite uses — so this stays inert in any real deployment.
    if settings.brief_fixtures:
        from app.api.brief_fixtures import install_brief_fixtures

        install_brief_fixtures(app, settings)

    return app
