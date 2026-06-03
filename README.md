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

The app loads and validates its configuration at startup (see `app/core/settings.py`), so the required
vars must be set first or the boot fails fast. For local dev, copy the example env and fill in the
required values:

```bash
cp .env.example .env       # then edit API_TOKEN and APP_DB_PATH
uv run uvicorn app.main:app --reload
```

Or export them inline:

```bash
API_TOKEN=<your-token> APP_DB_PATH=./app.db uv run uvicorn app.main:app --reload
```

## Test & lint

```bash
uv run pytest           # test suite
uv run ruff check .     # lint
```
