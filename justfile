# Local-dev runner for the Coach App backend — just `uv` + `just`, no containers.
# Bare `just` lists every recipe. See the README "Local development" section.
#
# Note: no file-wide `dotenv-load` — that would promote a developer's local .env into
# every recipe's env and make `just test` non-deterministic. Only `db-reset` reads .env
# (scoped), to resolve the same DB path the app/Alembic use before deleting it.

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
    # Resolve APP_DB_PATH from the same sources as the app, same precedence (process env
    # wins, then .env, then app.db). Only this recipe reads .env — `just test` stays clean.
    if [ -n "${APP_DB_PATH+x}" ]; then
        DB="$APP_DB_PATH"                       # process env (possibly explicitly empty)
    elif [ -f .env ] && grep -qE '^[[:space:]]*APP_DB_PATH=' .env; then
        DB="$(sed -n 's/^[[:space:]]*APP_DB_PATH=[[:space:]]*//p' .env | tail -n1)"
        DB="${DB%\"}"; DB="${DB#\"}"; DB="${DB%\'}"; DB="${DB#\'}"   # strip surrounding quotes
    else
        DB="app.db"                             # unset everywhere -> default
    fi
    [ -n "$DB" ] || { echo "db-reset: APP_DB_PATH is empty; refusing" >&2; exit 1; }
    # Mirror app.core.settings._db_target_basename: drop query/fragment, strip a leading URL
    # scheme, basename, lowercase — so Baseline.db / sqlite:///baseline.db?x are caught too
    # (read-only build inputs, ARCHITECTURE §3).
    norm="${DB%%[?#]*}"
    norm="$(printf '%s' "$norm" | sed -E 's#^[A-Za-z][A-Za-z0-9+.-]*:(//)?##')"
    case "$(basename "$norm" | tr '[:upper:]' '[:lower:]')" in
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
