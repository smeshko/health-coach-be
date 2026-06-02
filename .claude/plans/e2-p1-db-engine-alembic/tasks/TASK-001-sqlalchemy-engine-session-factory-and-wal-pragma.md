# TASK-001: SQLAlchemy engine, session factory and WAL pragma

Depends on: None
Suggested commit: `feat(database): add SQLite engine, session factory and WAL connect listener`

## Goal

Create the SQLAlchemy `Engine` against `settings.app_db_path` with a `connect` event listener that puts
every SQLite connection into **WAL** mode (and enables foreign keys), plus a `SessionLocal` factory and a
`get_session()` provider.

## Files

- `pyproject.toml` — add `alembic` and `tzdata` to dependencies (SQLAlchemy is already present from
  E1·P1). No Postgres/psycopg/celery/redis/supabase/vecs.
- `app/database/engine.py` — new:
  - `set_sqlite_pragmas(dbapi_conn, _connection_record) -> None` — **side-effect-free, module-level**
    function (no engine/settings access) that runs `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON`
    on a raw DBAPI connection. Importable on its own so Alembic's `env.py` (TASK-004) can reuse it
    **without** constructing the runtime engine.
  - `make_engine(db_path: str | Path) -> Engine` — `create_engine(f"sqlite:///{path}", future=True)` then
    `event.listen(engine, "connect", set_sqlite_pragmas)`.
  - **Lazy** runtime engine: do **not** build a module-level engine at import. Provide `get_engine()`
    (cached, e.g. `@lru_cache`) that calls `make_engine(get_settings().app_db_path)` on first use, plus a
    lazily-bound `SessionLocal` / `get_session()` that resolve the engine through `get_engine()`. This
    keeps `import app.database.engine` (and thus Alembic's helper import) free of a hard
    `app_db_path`-at-import-time dependency — closes round-1 #1.
  - `get_session()` — context-manager / FastAPI-dependency yielding a `Session`, closing it in `finally`.
- `app/database/__init__.py` — new: re-export `make_engine`, `get_engine`, `set_sqlite_pragmas`,
  `SessionLocal`, `get_session`.
- `tests/database/__init__.py` — new (package marker).
- `tests/database/test_engine_wal.py` — new: WAL + foreign-keys pragma assertions on a temp file engine,
  plus the import-isolated settings test below.

## Acceptance

- [ ] `make_engine(<temp file path>)` builds an engine whose fresh connection returns `wal` from
      `PRAGMA journal_mode` and `1` from `PRAGMA foreign_keys`.
- [ ] **`set_sqlite_pragmas` is importable without building the runtime engine** — `import
      app.database.engine` with `app_db_path` unset/cleared does **not** raise (no engine constructed at
      import), and `set_sqlite_pragmas` can be referenced directly (round-1 #1).
- [ ] **Import-time engine reads settings (isolated test):** set `app_db_path` to a temp path, clear the
      `get_settings` / `get_engine` caches, then `get_engine().url.database` equals that temp path — proving
      the runtime engine is sourced from `settings.app_db_path`, not a literal or the factory arg
      (round-1 #4). Kept **separate** from the `make_engine(temp_path)` factory-arg test.
- [ ] `SessionLocal()` yields a usable `Session`; `get_session()` opens and closes one (no leak).
- [ ] `from app.database import make_engine, get_engine, set_sqlite_pragmas, SessionLocal, get_session`
      resolves.
- [ ] No Postgres/celery/redis/supabase/vecs import in `app/database/engine.py`.

## Steps

### RED
- [ ] `tests/database/test_engine_wal.py`: build `make_engine(tmp_path/"app.db")`, open a connection, assert
      `PRAGMA journal_mode` == `wal` and `PRAGMA foreign_keys` == `1`; assert `get_session()` round-trips a
      trivial `SELECT 1`.
- [ ] Import-isolation test: monkeypatch `app_db_path` env to a temp path, clear `get_settings`/`get_engine`
      caches, assert `get_engine().url.database == <temp path>` (round-1 #4); and assert that importing
      `app.database.engine` with `app_db_path` cleared does **not** raise (no engine built at import,
      round-1 #1).

### GREEN
- [ ] Implement `app/database/engine.py` (`set_sqlite_pragmas`, `make_engine`, lazy `get_engine`,
      `SessionLocal`, `get_session`) and the `__init__.py` re-exports; add `alembic`/`tzdata` to
      `pyproject.toml`.

### REFACTOR
- [ ] Keep `set_sqlite_pragmas` free of engine/settings access so Alembic's `env.py` (TASK-004) imports it
      without triggering runtime-engine construction.

## Notes

WAL via a `connect` listener (not a one-off) guarantees every pooled connection — and every fresh temp DB
in tests — is in WAL (epic R1; DB.md §0). `foreign_keys=ON` is set here because SQLite defaults it OFF
**per connection** and E2·P2 adds the `workout_statistics.workout_id → workouts(id)` FK (DB.md §1). Test
against a **file** DB, not `:memory:` — in-memory SQLite can report a different journal mode. The runtime
engine is **lazy** (`get_engine()`), not built at import: `set_sqlite_pragmas` must be importable on its
own so Alembic reuses it without binding `app_db_path` at import time (round-1 #1).
