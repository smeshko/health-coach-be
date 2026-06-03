# Coach App — Backend

FastAPI workflow engine that produces deterministic + LLM health-coaching briefs.
See [`docs/architecture/ARCHITECTURE.md`](./docs/architecture/ARCHITECTURE.md) for the design and
[`EPICS.md`](./EPICS.md) for the phased build plan.

## Stack

Python **3.13**, managed with [`uv`](https://docs.astral.sh/uv/). Kept stack only: FastAPI · Uvicorn ·
Pydantic / pydantic-settings · SQLAlchemy · Alembic · PydanticAI · Jinja2. No Postgres/Celery/Redis/
pgvector/Supabase (ARCHITECTURE §1 stack note).

## Setup

```bash
uv sync                 # create the venv and install deps (Python 3.13)
```

## Run

```bash
uv run uvicorn app.main:app --reload
```

The server reads its configuration from the environment (see `app/core/config.py`). Required vars must be
set or the app fails fast at startup.

## Test & lint

```bash
uv run pytest           # test suite
uv run ruff check .     # lint
```
