# TASK-002: Forward-declared lifecycle recipes (migrate, seed, bootstrap, db-reset) and .env handling

Depends on: TASK-001
Suggested commit: `feat(dev): add forward lifecycle recipes and .env bootstrap`

## Goal

Add the forward-declared lifecycle recipes (`migrate`, `seed`, `bootstrap`, `db-reset`) calling the exact
future E2/E4 commands, plus an `env` recipe that bootstraps `.env` from `.env.example` without clobbering.

## Files

- `justfile` (repo root) — extend with:
  - `migrate:` → `uv run alembic upgrade head`  `# (E2·P1) — lights up once Alembic lands`
  - `seed:` → run the E4 bootstrap scripts in order:
    `uv run python scripts/build_db.py` (E4·P1), `uv run python scripts/derive_constants.py` (E4·P2),
    `uv run python scripts/seed_app_db.py` (E4·P3)  `# (E4) — lights up once the scripts land`
  - `bootstrap:` → chain `install` → `migrate` → `seed` (via recipe dependencies, e.g.
    `bootstrap: install migrate seed`, or explicit `just install && just migrate && just seed`)
  - `db-reset:` → a **single-shell-block shebang recipe** (so all lines share one shell — `just` runs plain
    recipe lines in separate processes, which would drop `DB` before the guard/`rm`):
    ```
    db-reset:
        #!/usr/bin/env bash
        set -euo pipefail
        DB="${APP_DB_PATH-app.db}"            # unset → app.db; explicit-empty stays empty
        [ -n "$DB" ] || { echo "db-reset: APP_DB_PATH is empty; refusing" >&2; exit 1; }
        case "$(basename "$DB")" in baseline.db) echo "db-reset: refusing baseline.db" >&2; exit 1;; esac
        rm -f -- "$DB" "$DB-wal" "$DB-shm"
        just migrate
    ```
    Reads `APP_DB_PATH` so it targets the **configured** DB (the Alembic/settings source of truth,
    E1·P1/E2·P1), not a hard-coded name. Note `${APP_DB_PATH-app.db}` (not `:-`) so an **explicitly empty**
    value is refused rather than collapsing to `app.db`; `rm -f --` stops option parsing; explicit siblings,
    never a glob, never `baseline.db` (round-1 #2, round-2 #1)
  - `env:` → copy `.env.example` → `.env` **only if `.env` is missing**
    (`test -f .env || cp .env.example .env`), with an `@echo` notice either way
- `.env.example` (owned by E1·P1) — **only if** a variable required by `just run`/`just migrate` is missing
  (e.g. `APP_DB_PATH=app.db`), append it; do not rewrite the file. (Confirm during impl; default is to
  leave it untouched and rely on E1·P1's content.)

## Acceptance

- [ ] `just --show migrate` → `uv run alembic upgrade head`.
- [ ] `just --show seed` references all three E4 scripts (`scripts/build_db.py`,
      `scripts/derive_constants.py`, `scripts/seed_app_db.py`) via `uv run python`.
- [ ] `just --show bootstrap` shows it chains `install` → `migrate` → `seed` (dependency line or explicit
      sequence).
- [ ] `just --show db-reset` shows the shebang single-block recipe: `set -euo pipefail`,
      `DB="${APP_DB_PATH-app.db}"`, the `-z`/empty refusal, the `baseline.db` refusal,
      `rm -f -- "$DB" "$DB-wal" "$DB-shm"`, then `just migrate`; grep proves no glob (`*.db`) is used.
      Behaviour checks (the `migrate` tail may fail pre-E2 — that's fine; assert the `rm` happened first):
      (a) unset `APP_DB_PATH` + sentinel `app.db`/`-wal`/`-shm` → all three removed; (b) `APP_DB_PATH=` (empty)
      → recipe refuses with non-zero exit, deletes nothing; (c) `APP_DB_PATH=/tmp/coachtest.db` + sentinels →
      those three removed; (d) `APP_DB_PATH=baseline.db` → refuses, deletes nothing.
- [ ] `just env` creates `.env` from `.env.example` when `.env` is absent; re-running `just env` with an
      existing `.env` does **not** overwrite it (content unchanged, exit 0, prints "kept existing .env").
- [ ] The forward recipes are asserted via `just --show`/`just -n` (not by running them end-to-end), since
      Alembic (E2) and the E4 scripts do not exist yet.

## Steps

### RED
- [ ] Capture the observable assertions: before this task, `just --show migrate`/`seed`/`bootstrap`/
      `db-reset`/`env` either error (recipe absent) or do not print the expected commands; and a temp `.env`
      with sentinel content would be clobbered by a naive `cp`. These are the conditions the recipes fix.

### GREEN
- [ ] Add the five recipes to `justfile` exactly as in **Files** (forward recipes carry inline `# (E2)`/
      `# (E4)` epic markers).
- [ ] Verify each via `just --show <recipe>` / `just -n <recipe>`; verify `just env` create-vs-keep
      behaviour against a temp HOME/cwd (create when missing, no-op + notice when present).
- [ ] If `just run`/`just migrate` need a var absent from E1·P1's `.env.example`, append it; otherwise leave
      `.env.example` untouched.

### REFACTOR
- [ ] Order recipes logically (core, then lifecycle, then env); ensure every forward recipe has an epic
      marker comment; `just fmt` + `just lint` leave the tree clean; `just --list` still lists everything.

## Notes

`db-reset` must run as a **single shebang shell block** (`#!/usr/bin/env bash`), because `just` executes
each plain recipe line in its own process — a multi-line `DB=…` / guard / `rm` split across lines would lose
`DB` before the guard runs (round-2 #1). It resolves `DB="${APP_DB_PATH-app.db}"` (the configured DB path —
Alembic/settings source of truth, E1·P1/E2·P1; `-` not `:-` so explicit-empty is refused, not collapsed)
and deletes only `"$DB"`/`"$DB-wal"`/`"$DB-shm"` via `rm -f --` (`.gitignore` covers
`*.db`/`*.db-wal`/`*.db-shm`), guarding against an empty path and against `baseline.db` (a read-only build
input, ARCHITECTURE §3). `.env` is gitignored — `env` bootstraps it locally but it is never committed. The
forward commands are grounded: `alembic upgrade head` (E2·P1 plan), `scripts/build_db.py` (E4·P1),
`scripts/derive_constants.py` (E4·P2), `scripts/seed_app_db.py` (E4·P3). No Docker/litestream (E12·P2).
