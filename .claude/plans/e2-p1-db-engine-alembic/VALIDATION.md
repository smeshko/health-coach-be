# Validation Summary — e2-p1-db-engine-alembic

**Rounds:** 3 (cap reached)
**Plan status at validation:** draft
**Run on:** 2026-06-03

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 4        | 4       | 0        | 0        |
| 2     | 3        | 3       | 0        | 0        |
| 3     | 1        | 1       | 0        | 0        |

## Applied

### Round 1
- TASK-001, TASK-004, PLAN.md:Decisions/Risks — made the runtime engine **lazy** (`get_engine()`, not
  built at import) and `set_sqlite_pragmas` **side-effect-free**, so Alembic's `env.py` imports the pragma
  helper without binding `app_db_path` at import time (round-1 #1).
- TASK-004, TASK-005, PLAN.md:Acceptance/Risks — `resolve_url()` is owned by `settings.app_db_path`; a
  static/stale `sqlalchemy.url` is **ignored**; the only override is an explicit test-only
  `config.attributes["test_db_url"]`; added a negative test (round-1 #2).
- TASK-003, TASK-005, PLAN.md:Acceptance — added a `store_ts()` storage helper that returns the **exact**
  ISO-8601 string (`store_ts(s) == s`) and tests string-identity across offset forms, proving verbatim
  TEXT preservation (not just offset semantics) (round-1 #3).
- TASK-001, TASK-005, PLAN.md:Acceptance — added an **import-isolated** test asserting
  `get_engine().url.database` follows an overridden `app_db_path`, separate from the `make_engine(temp)`
  factory-arg test (round-1 #4).

### Round 2
- TASK-004, TASK-005, PLAN.md:Acceptance — mapped WAL to the **Alembic upgrade path**: after
  `upgrade head` the migrated temp file must report `PRAGMA journal_mode == 'wal'`, so a broken `env.py`
  (no listener) fails validation instead of silently creating a non-WAL `app.db` (round-2 #1).
- PLAN.md:Scope, RESEARCH.md — removed the stale module-level `engine` re-export/usage that contradicted
  the lazy `get_engine()` fix; the public API is now `make_engine`/`get_engine`/`set_sqlite_pragmas`
  consistently (round-2 #2).
- TASK-003, TASK-005, PLAN.md:Decisions/Acceptance — added an **aware-datetime guard** so
  `to_sofia`/`period_date`/`iso_week` raise `ValueError` on a naive `datetime` (no host-tz fallback →
  reproducible cache keys), with a test (round-2 #3).

### Round 3
- TASK-004, TASK-005, PLAN.md:Acceptance — made the Alembic WAL assertion **non-circular**: the migrated
  file must be inspected with a **raw `sqlite3.connect` (no listener)**, so the check can only pass if
  `env.py` itself attached `set_sqlite_pragmas` during the migration (a listener-bearing inspection
  connection would flip WAL on and mask a broken `env.py`) (round-3 #1).

## Deferred

- None.

## Rejected

- None.
