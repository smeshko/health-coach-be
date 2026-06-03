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

## Local development

Local dev is just `uv` + [`just`](https://github.com/casey/just) — **no Docker** (Docker/litestream are
deployment-only, E12). Run bare `just` to list every recipe.

**Prerequisites:** [`uv`](https://docs.astral.sh/uv/) and [`just`](https://github.com/casey/just) installed
(Python 3.13 is provided by `uv`).

### From a clean checkout — today (E1)

This boots the current scaffold and serves `GET /health`. It does **not** need `just migrate` (no DB
tables exist until E2):

```bash
just install            # uv sync
just env                # create .env from .env.example, then edit it and set API_TOKEN
just run                # uv run uvicorn app.main:app --reload
curl localhost:8000/health
```

### Full flow (once E2/E4 land)

Same start, but insert `just migrate` (or the all-in-one `just bootstrap`) after `just env` and before
`just run`. These are forward-declared now and only fully run after E2 (Alembic) and E4 (bootstrap scripts):

```bash
just install
just env
just migrate            # or: just bootstrap   (install → migrate → seed)
just run
```

### Recipe reference

| Recipe | Command | Notes |
|---|---|---|
| `install` | `uv sync` | install/sync deps |
| `run` | `uv run uvicorn app.main:app --reload` | dev server (auto-reload) |
| `test` | `uv run pytest` | test suite |
| `lint` | `uv run ruff check .` | lint |
| `fmt` | `uv run ruff format .` | format |
| `migrate` | `uv run alembic upgrade head` | **E2** — runnable once Alembic lands |
| `seed` | `build_db.py` → `derive_constants.py` → `seed_app_db.py` | **E4** — runnable once the scripts land |
| `bootstrap` | `install` → `migrate` → `seed` | **E2+E4** — full first-run, runnable once those land |
| `db-reset` | remove the configured `app.db`(+`-wal`/`-shm`), then `migrate` | resolves `APP_DB_PATH`; refuses `baseline.db` |
| `env` | copy `.env.example` → `.env` (only if absent) | never overwrites a real `.env` |

> `migrate`, `seed`, and `bootstrap` are **forward-declared**: they call the exact future commands but are
> not expected to fully run until **E2/E4** land.
