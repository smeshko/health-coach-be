# TASK-005: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e2-p1-db-engine-alembic`

## Goal

Confirm every PLAN.md acceptance criterion is met with a concrete, non-circular check (named command or
test), the engine/Alembic scaffolding ships clean, and no dropped-stack deps leaked in.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked.
- [ ] **Lint:** `uv run ruff check .` passes with no issues.
- [ ] **Tests:** `uv run pytest tests/database tests/core/test_time.py` passes (all engine, base, time, and
      Alembic tests green).

### Acceptance-criteria mapping (1:1, concrete)

- [ ] **WAL active (runtime engine)** — `uv run pytest tests/database/test_engine_wal.py` proves a fresh
      connection on a temp **file** engine returns `wal` from `PRAGMA journal_mode` and `1` from
      `PRAGMA foreign_keys`.
- [ ] **WAL active (Alembic-migrated file, non-circular)** — `uv run pytest tests/database/test_alembic.py
      -k "wal"` proves that after `command.upgrade(cfg, "head")` on the temp file DB, opening that file with
      a **raw `sqlite3.connect(db_path)` (no listener, not via `make_engine`)** reports `PRAGMA
      journal_mode == 'wal'` — so the check can only pass if `env.py` attached `set_sqlite_pragmas` during
      the migration, not because the inspection connection flipped WAL on (round-3 #1; round-2 #1;
      epic R1, §4).
- [ ] **Engine sourced from settings (import-isolated)** — `uv run pytest tests/database/test_engine_wal.py
      -k "settings or import or lazy"` proves importing `app.database.engine` with `app_db_path` cleared
      does not raise (lazy engine), and that with `app_db_path` set to a temp path + caches cleared,
      `get_engine().url.database` equals that path (round-1 #1, #4) — separate from the `make_engine(temp)`
      factory-arg test.
- [ ] **Alembic targets app.db only** — `uv run pytest tests/database/test_alembic.py -k "target or
      baseline or stale"` proves `resolve_url()` is the settings/test-override app DB path, a planted static
      `sqlalchemy.url` is **ignored** (round-1 #2), **and** `! grep -rn baseline alembic alembic.ini`
      (no match).
- [ ] **Round-trip** — `uv run pytest tests/database/test_alembic.py -k "round or upgrade"` proves
      `upgrade head` → `downgrade base` → `upgrade head` succeeds on a temp file DB, `alembic_version`
      holds head afterwards and is empty after `downgrade base`.
- [ ] **No tables yet** — `uv run pytest tests/database/test_alembic.py -k "no_tables or empty"` proves
      that after `upgrade head` the only table in `sqlite_master` is `alembic_version` (initial migration
      empty).
- [ ] **Declarative base + naming convention** — `uv run pytest tests/database/test_base.py` proves
      `Base.metadata.naming_convention` has the `ix`/`uq`/`ck`/`fk`/`pk` keys+templates, `Base.metadata is
      metadata`, and `Base.metadata.tables == {}`.
- [ ] **Period date (Europe/Sofia)** — `uv run pytest tests/core/test_time.py -k "period_date or dst"`
      proves `period_date` returns the Sofia-local `YYYY-MM-DD` across both DST boundaries and for a
      non-Sofia travel offset.
- [ ] **ISO week (`YYYY-Www`)** — `uv run pytest tests/core/test_time.py -k "iso_week or week"` proves
      `iso_week` returns zero-padded `YYYY-Www` (e.g. `2026-W23`), correct across a DST boundary, a travel
      offset, and an ISO year-boundary week.
- [ ] **Timestamp stored verbatim (string identity)** — `uv run pytest tests/core/test_time.py -k "store or
      offset or parse"` proves `store_ts(s) == s` (exact string) for `+02:00`, `+03:00`, compact `+0300`, a
      non-Sofia offset, and a fractional-seconds case; `parse_ts` preserves the offset and raises on a naive
      string — never normalizing to UTC or `+03:00` (round-1 #3).
- [ ] **Naive datetime rejected** — `uv run pytest tests/core/test_time.py -k "naive or aware"` proves
      `to_sofia`/`period_date`/`iso_week` raise `ValueError` on a naive `datetime` (no host-tz fallback;
      round-2 #3).
- [ ] **tz data available** — `uv run python -c "from zoneinfo import ZoneInfo; ZoneInfo('Europe/Sofia')"`
      succeeds (tzdata dep present); also covered by `tests/core/test_time.py`.
- [ ] **No dropped-stack deps** — `! grep -REn "psycopg|pgvector|celery|redis|supabase|vecs" app
      pyproject.toml` (no match) — ARCHITECTURE §1 stack note.
- [ ] **Public API** — `uv run python -c "from app.database import make_engine, get_engine,
      set_sqlite_pragmas, SessionLocal, get_session, Base, metadata; from app.core.time import period_date,
      iso_week, parse_ts, store_ts"` succeeds.

- [ ] `PLAN.md` acceptance criteria all met (each mapped above).
