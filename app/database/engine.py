"""SQLAlchemy engine, session factory and the SQLite WAL/FK connect listener.

The runtime engine is **lazy** (`get_engine()`), never constructed at import: this
keeps `import app.database.engine` — and Alembic's `env.py`, which imports
`set_sqlite_pragmas` from here — free of an `app_db_path`-at-import-time dependency
(round-1 #1, #4). `app.db` is the only database the running API touches; the path
comes from `settings.app_db_path`, never hard-coded (DB.md §0; ARCHITECTURE §3).

WAL + foreign-key enforcement are applied via a `connect` event listener so that
**every** pooled connection — and every fresh temp DB in tests — is in WAL with FKs
on (SQLite defaults `foreign_keys` OFF per connection, and E2·P2 adds the
`workout_statistics.workout_id → workouts(id)` FK) (epic R1; DB.md §0, §1).
"""

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import get_settings


def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """Put a freshly-opened SQLite connection in WAL mode and enforce foreign keys.

    Registered as a SQLAlchemy ``connect`` listener by :func:`make_engine`. Kept
    **side-effect-free** (no engine/settings access) and importable on its own so
    Alembic's ``env.py`` reuses it without constructing the runtime engine
    (round-1 #1).

    Two further pragmas harden the single-file runtime store:

    * ``busy_timeout=5000`` — FastAPI runs the sync `/sync` and `/brief` routes on a
      threadpool, so two requests can briefly contend for SQLite's single writer.
      Without a timeout the loser fails *immediately* with ``SQLITE_BUSY`` (a 5xx);
      with 5 s it waits for the writer to finish instead. (SQLite defaults to 0.)
    * ``synchronous=NORMAL`` — under WAL this is durable against application crashes
      and is the setting litestream recommends; combined with the deployment running
      on a battery-backed host (the laptop battery is an effective UPS), the residual
      power-loss window is negligible while avoiding FULL's per-commit fsync cost.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def make_engine(db_path: str | Path) -> Engine:
    """Build a SQLite :class:`Engine` for ``db_path`` with the WAL/FK listener attached."""
    engine = create_engine(f"sqlite:///{db_path}")
    event.listen(engine, "connect", set_sqlite_pragmas)
    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the cached runtime engine, built lazily from ``settings.app_db_path``.

    Lazy (not a module-level ``engine``) so importing this module never forces
    ``app_db_path`` to resolve, and a test override of the setting takes effect as
    long as both the ``get_settings`` and ``get_engine`` caches are cleared first.
    """
    return make_engine(get_settings().app_db_path)


# Unbound factory: the engine is resolved lazily at call time via get_engine(), so
# importing this module does not build the runtime engine.
_session_factory = sessionmaker(autoflush=False, expire_on_commit=False)


def SessionLocal(**kwargs) -> Session:  # noqa: N802 — session factory, mirrors sessionmaker()
    """Return a new :class:`Session` bound to the lazy runtime engine."""
    return _session_factory(bind=get_engine(), **kwargs)


def get_session() -> Iterator[Session]:
    """Yield a runtime :class:`Session`, closing it in ``finally`` (FastAPI dependency)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
