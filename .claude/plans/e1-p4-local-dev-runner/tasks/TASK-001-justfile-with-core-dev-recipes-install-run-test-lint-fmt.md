# TASK-001: justfile with core dev recipes (install, run, test, lint, fmt)

Depends on: None
Suggested commit: `feat(dev): add justfile with core dev recipes`

## Goal

Create `backend/justfile` with a `_default` recipe (so bare `just` lists recipes) and the five core
recipes that work against the E1 scaffold today: `install`, `run`, `test`, `lint`, `fmt`.

## Files

- `justfile` (repo root, `backend/justfile`) — new. Contains:
  - `_default:` → `@just --list` (first recipe; runs when `just` is called with no args; `_` hides it from
    the listing)
  - `install:` → `uv sync`
  - `run:` → `uv run uvicorn app.main:app --reload` (the E1·P1 canonical entry point + dev `--reload`)
  - `test:` → `uv run pytest`
  - `lint:` → `uv run ruff check .`
  - `fmt:` → `uv run ruff format .`
  - A short header comment naming the file as the local-dev runner and pointing at the README.

## Acceptance

- [ ] `just` (no args) and `just --list` both print the recipe list including `install`, `run`, `test`,
      `lint`, `fmt` (and `_default` is hidden because of the `_` prefix).
- [ ] `just --show run` prints exactly `uv run uvicorn app.main:app --reload` (the E1·P1 entry point with
      `--reload`); `just --show install` → `uv sync`; `just --show lint` → `uv run ruff check .`;
      `just --show test` → `uv run pytest`; `just --show fmt` → `uv run ruff format .`.
- [ ] `just -n install`, `just -n lint`, `just -n test`, `just -n fmt` dry-run-print the right command
      without executing it; running `just install`, `just lint`, `just test` actually succeeds against the
      E1 scaffold.
- [ ] `just --evaluate` / `just --list` exits 0 (the justfile parses with no syntax errors).

## Steps

### RED
- [ ] Write the observable check first: with no justfile (or a stub), `just --list` fails / does not list
      the five recipes, and `just --show run` does not yield the `app.main:app --reload` command. Capture
      these as the assertions the recipes must satisfy.

### GREEN
- [ ] Author `justfile` with `_default` + `install`/`run`/`test`/`lint`/`fmt` exactly as in **Files**.
- [ ] Confirm `just --list` lists them, `just --show <recipe>` prints the expected command, and
      `just install`/`just lint`/`just test` run green against the scaffold.

### REFACTOR
- [ ] Tidy spacing/comments; ensure the header comment references the README "Local development" section.
      Run `just fmt` then `just lint` to confirm the recipes themselves leave the tree clean.

## Notes

`just` runs the **first** recipe when invoked with no arguments — so `_default` must be first in the file.
`run` wraps, not replaces, the E1·P1 entry point (`uv run uvicorn app.main:app`); the bare form stays the
production/E12 invocation. No Docker here (ARCHITECTURE §1; deployment is E12·P2).
