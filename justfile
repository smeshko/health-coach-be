# Local-dev runner for the Coach App backend — just `uv` + `just`, no containers.
# Bare `just` lists every recipe. See the README "Local development" section.

# Load .env into recipe env (process env still wins) so recipes resolve APP_DB_PATH
# from the SAME source the app/Alembic do — e.g. db-reset deletes the configured DB.
set dotenv-load := true

# List all recipes (runs when `just` is invoked with no arguments).
_default:
    @just --list

# Install / sync dependencies (uv-managed, Python 3.13).
install:
    uv sync

# Run the dev server with auto-reload (production/E12 uses the bare entry point).
run:
    uv run uvicorn app.main:app --reload

# Run the test suite.
test:
    uv run pytest

# Lint the project.
lint:
    uv run ruff check .

# Format the project.
fmt:
    uv run ruff format .

# --- Lifecycle (forward-declared; light up as E2/E4 land) --------------------

# Apply DB migrations. (E2·P1 — runnable once Alembic lands.)
migrate:
    uv run alembic upgrade head

# Build + derive + seed the local DB from the offline sources. (E4 — runnable once the scripts land.)
seed:
    uv run python scripts/build_db.py
    uv run python scripts/derive_constants.py
    uv run python scripts/seed_app_db.py

# Full first-run bootstrap: install, migrate, then seed. (E2+E4.)
bootstrap: install migrate seed

# Delete the local app.db (+ -wal/-shm) for the configured APP_DB_PATH, then re-migrate.
db-reset:
    #!/usr/bin/env bash
    set -euo pipefail
    # ${VAR-default}: unset -> app.db; an explicitly empty APP_DB_PATH stays empty (refused below).
    DB="${APP_DB_PATH-app.db}"
    [ -n "$DB" ] || { echo "db-reset: APP_DB_PATH is empty; refusing" >&2; exit 1; }
    # Mirror the settings forbidden-basename guard (read-only build inputs, ARCHITECTURE §3).
    case "$(basename "$DB")" in
        baseline.db|health.db) echo "db-reset: refusing to delete the read-only build DB ($DB)" >&2; exit 1 ;;
    esac
    rm -f -- "$DB" "$DB-wal" "$DB-shm"
    just migrate

# --- Environment -------------------------------------------------------------

# Create .env from .env.example (only when .env is absent; never overwrites).
env:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -f .env ]; then
        echo "env: kept existing .env"
    else
        cp .env.example .env
        echo "env: created .env from .env.example — set API_TOKEN before running"
    fi
