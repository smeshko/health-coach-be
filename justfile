# Local-dev runner for the Coach App backend (no Docker — that's deployment, E12).
# Bare `just` lists every recipe. See the README "Local development" section.

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
