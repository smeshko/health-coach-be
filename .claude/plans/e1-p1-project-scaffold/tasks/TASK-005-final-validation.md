# TASK-005: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e1-p1-project-scaffold`

## Goal

Confirm the plan is fully implemented and production-ready.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked
- [ ] `uv run ruff check .` passes with no issues
- [ ] `uv run pytest` passes
- [ ] `uv sync` resolves cleanly and `uv run python --version` prints **3.13.x**; `requires-python` is
      `>=3.13,<3.14`; the lock contains none of Postgres/Celery/Redis/pgvector/vecs/Supabase
- [ ] **Settings — fail fast:** `test_settings.py` proves a missing required var raises; **and** the
      negative app-factory smoke (`test_app_factory.py`) proves `create_app()` fails at boot when a
      required var is unset
- [ ] **Settings — load:** env present → `get_settings()` returns a valid cached `Settings`
- [ ] **camelCase in:** a `CamelModel` accepts both snake_case and camelCase input
- [ ] **camelCase out:** raw `model_dump_json()` is camelCase **and** a `TestClient` route returns
      camelCase wire JSON
- [ ] **Null-vs-absent:** an optional `T | None = None` field accepts both omission and explicit `null`
- [ ] **Importability:** `python -c "import app.api, app.core, app.database, app.services"` succeeds
- [ ] `uv run uvicorn app.main:app` boots (manual smoke), `create_app()` returns a `FastAPI`, OpenAPI at
      `/openapi.json`
- [ ] `PLAN.md` acceptance criteria all met
