# TASK-001: Initialize uv project, pin Python 3.13, declare deps, create package layout

Depends on: None
Suggested commit: `chore(project): init uv project, deps, and package layout`

## Goal

Create the `uv` project pinned to Python 3.13 with the kept-stack dependencies and the package layout the
later epics import.

## Files

- `pyproject.toml` — project metadata, `requires-python = ">=3.13,<3.14"` (bounded — not a bare floor),
  dependencies (allowlist) + dev deps (incl. `httpx` for FastAPI `TestClient`)
- `.python-version` — `3.13`
- `app/__init__.py`, `app/api/__init__.py`, `app/core/__init__.py`, `app/database/__init__.py`,
  `app/services/__init__.py` — package skeleton
- `tests/__init__.py`, `tests/test_layout.py` — import-boundary smoke test
- `README.md` — run instructions (`uv sync`, `uv run uvicorn …`)

## Acceptance

- [ ] `uv sync` succeeds on Python 3.13; `requires-python` is bounded `>=3.13,<3.14` (not a bare `>=3.13`).
- [ ] Runtime dependencies are exactly the kept stack (fastapi, uvicorn, pydantic, pydantic-settings,
      sqlalchemy, alembic, pydantic-ai, jinja2); dev deps add `pytest`, `ruff`, `httpx` (TestClient). **No**
      psycopg/asyncpg/celery/redis/pgvector/vecs/supabase anywhere in the lock.
- [ ] `python -c "import app.api, app.core, app.database, app.services"` succeeds.

## Steps

### RED
- [ ] Add `tests/test_layout.py` asserting the four subpackages import and that forbidden deps are not
      importable / not in the locked manifest.

### GREEN
- [ ] Author `pyproject.toml` (allowlist deps), `.python-version`, the package `__init__.py` files, README.
- [ ] `uv sync`.

### REFACTOR
- [ ] Run `ruff` and tidy; confirm the test passes.

## Notes

Stack allowlist is mandated by ARCHITECTURE §1 (drop Postgres/Celery/Redis/pgvector/vecs/Supabase).
Mirror `../genai-launchpad-main/app/` layout for parity with the `core/` primitives adopted in E1·P3.
