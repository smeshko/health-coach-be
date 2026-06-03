# Plan: E1·P1 — Project scaffold & config

Status: in-progress
Branch: feature/e1-p1-project-scaffold
Risk: small
Created: 2026-06-03

> Epic **E1 — Foundation & API Skeleton**, phase **P1**. Source of truth:
> [`epics/E01-foundation.md`](../../../epics/E01-foundation.md) · grounded in
> [`docs/architecture/ARCHITECTURE.md`](../../../docs/architecture/ARCHITECTURE.md) §1 and
> [`docs/architecture/MODELS.md`](../../../docs/architecture/MODELS.md) "Conventions".

## Goal

Stand up the runnable `uv`/FastAPI project skeleton — package layout, typed env settings, and the
camelCase Pydantic base — so every later epic has a chassis to build on.

## Scope

- A `uv`-managed project pinned to **Python 3.13** (bounded `requires-python = ">=3.13,<3.14"`, not a bare
  floor) with a dependency manifest containing only the kept stack: `fastapi`, `uvicorn`, `pydantic`,
  `pydantic-settings`, `sqlalchemy`, `alembic`, `pydantic-ai`, `jinja2` (+ `pytest`, `ruff`, `httpx` for
  dev/testing). **No** Postgres/Celery/Redis/pgvector/`vecs` deps (ARCHITECTURE §1 stack note).
- Package layout: `app/` (or top-level packages) `api/`, `core/`, `database/`, `services/`, plus `tests/`.
- A FastAPI **app factory** (`create_app()`) and a `uvicorn` entrypoint.
- A typed **settings** module (`pydantic-settings`) reading env: `api_token`, `app_db_path`, `model_id`,
  `langfuse_*` (optional), `constitution_version`; fail fast on missing required vars.
- A **camelCase Pydantic base model** (`alias_generator=to_camel`, `populate_by_name=True`) all wire
  models will inherit (MODELS "Conventions → Casing").

## Out of Scope

- Auth, error envelope, health endpoint (E1·P2).
- Workflow engine primitives (E1·P3).
- DB models/migrations (E2), real endpoints (E5/E10/E11), Docker/Langfuse wiring (E12).

## Research Summary

The backend reuses Datalumina's GenAI Launchpad (`../genai-launchpad-main`) but keeps **only** its FastAPI
app, `core/` workflow primitives, PydanticAI, Jinja2, and Alembic; Postgres/pgvector, Celery, Redis,
Supabase, streaming and RAG are dropped (ARCHITECTURE §1 stack note). Single synchronous process, no
workers/scheduler. Wire JSON is camelCase, Python stays snake_case behind a Pydantic `alias_generator`
(MODELS "Conventions"). The Launchpad layout under `../genai-launchpad-main/app/` is a reference for the
package structure to mirror (minus the dropped pieces).

## Decisions

- **Mirror the Launchpad package layout (`api/core/database/services`), minus dropped deps** — keeps
  parity with the boilerplate the `core/` primitives come from (E1·P3) while shedding Postgres/Celery/Redis.
- **`pydantic-settings` for config, env-driven** — matches the deployment model (one process, env config;
  ARCHITECTURE §1) and fails fast at startup.
- **One shared camelCase base model now** — every later wire model (E5/E10/E11) inherits it, so casing is
  defined once (MODELS "Conventions").

## Risks

- **Carrying over dropped deps from the Launchpad** — mitigation: the manifest is an explicit allowlist;
  TASK-001 acceptance asserts no Postgres/Celery/Redis/pgvector imports.
- **Python version drift** — mitigation: pin 3.13 in `pyproject.toml`/`.python-version`.

## Acceptance Criteria

- [ ] `uv sync` installs the project on Python **3.13** (`requires-python` bounded `>=3.13,<3.14`);
      the locked dependency set contains none of Postgres/Celery/Redis/pgvector/`vecs`.
- [ ] `uvicorn` starts the app via the factory entrypoint without error when env is complete.
- [ ] Settings load from env and **fail fast at app startup** (`create_app()` raises) when a required var
      is missing — proven by a negative app-factory smoke, not only an isolated settings test.
- [ ] A sample model inheriting the base emits camelCase from raw `model_dump_json()` **and** over the
      wire (FastAPI route), and accepts both snake_case and camelCase input.
- [ ] The package layout (`api/`, `core/`, `database/`, `services/`, `tests/`) exists and is importable.

## Tasks

Task state lives here. Tasks are appended by `scripts/add_task.py` and
`scripts/add_final_task.py`. Update the checkboxes as work progresses.

- [x] TASK-001: Initialize uv project, pin Python 3.13, declare deps, create package layout
- [ ] TASK-002: FastAPI app factory and uvicorn entrypoint
- [ ] TASK-003: Typed settings module loaded from environment
- [ ] TASK-004: camelCase Pydantic base model
- [ ] TASK-005: Final Validation
