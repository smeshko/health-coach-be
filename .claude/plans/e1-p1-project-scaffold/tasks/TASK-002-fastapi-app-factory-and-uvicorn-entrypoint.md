# TASK-002: FastAPI app factory and uvicorn entrypoint

Depends on: TASK-001
Suggested commit: `feat(api): add FastAPI app factory and uvicorn entrypoint`

## Goal

Provide a `create_app()` factory returning a configured `FastAPI` instance that **loads and validates
settings at startup**, plus a `uvicorn`-runnable entry point.

## Files

- `app/api/app.py` — `create_app() -> FastAPI`; calls `get_settings()` **at construction time** (inside
  `create_app()` itself, before returning) so missing required env makes `create_app()` raise — not a
  lifespan-only hook that a non-context-managed `TestClient` could bypass
- `app/main.py` — module exposing `app = create_app()` for `uvicorn app.main:app`
- `tests/test_app_factory.py` — factory returns a `FastAPI`; `TestClient` builds (needs `httpx` dev dep
  from TASK-001); OpenAPI schema is exposed; **negative smoke**: `create_app()` with a required env var
  unset raises a clear error

## Acceptance

- [ ] `create_app()` returns a `FastAPI` instance and calls `get_settings()` **at construction time**.
- [ ] `TestClient(create_app())` builds and the app exposes its OpenAPI schema (`/openapi.json`).
- [ ] With a required env var unset, **`create_app()` itself raises** a clear `ValidationError`-derived
      error (asserted directly — not via lifespan) — so `uv run uvicorn app.main:app` also fails fast.
- [ ] `uv run uvicorn app.main:app` boots locally when env is complete (manual smoke).

## Steps

### RED
- [ ] `tests/test_app_factory.py`: `create_app()` returns `FastAPI`; `TestClient` builds; OpenAPI exposed;
      negative smoke — unset a required env var → **`create_app()` raises directly** (assert on the call,
      not on lifespan entry).

### GREEN
- [ ] Implement `create_app()` (load `get_settings()` at construction/startup) and `app/main.py`.

### REFACTOR
- [ ] Keep the factory free of unrelated side effects (only config validation at boot); tidy with `ruff`.

## Notes

Single synchronous process — no workers/scheduler (ARCHITECTURE §1). Routers/handlers are added in E1·P2
(health/errors) and later endpoint epics; keep the factory open for `include_router`.
