"""Alembic environment — targets the runtime database (`app.db`) only.

The production database URL is owned by ``settings.app_db_path``; any static
``sqlalchemy.url`` in ``alembic.ini`` is ignored so a stale value cannot redirect a
migration (round-1 #2). The only override is the explicit, test-only
``config.attributes["test_db_url"]``. The read-only build input is never targeted
(DB.md §0; ARCHITECTURE §3).

``set_sqlite_pragmas`` is imported side-effect-free (round-1 #1) and attached to the
migration engine so migrations run on a WAL + foreign-keys connection — proven by
opening the migrated file with a raw connection in the tests.
"""

from alembic import context
from sqlalchemy import create_engine, event, pool

from app.core.settings import get_settings
from app.database.base import Base
from app.database.engine import set_sqlite_pragmas

# Autogenerate diffs against the single declarative base (E2·P2/P3 attach tables).
target_metadata = Base.metadata


def resolve_url(config) -> str:
    """Resolve the migration DB URL: explicit test override, else settings.

    Any ``sqlalchemy.url`` set on the config is intentionally **not** consulted, so a
    stray ``.ini`` value can't take effect (round-1 #2).
    """
    test_url = config.attributes.get("test_db_url")
    if test_url:
        return test_url
    return f"sqlite:///{get_settings().app_db_path}"


def run_migrations_offline(config) -> None:
    context.configure(
        url=resolve_url(config),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online(config) -> None:
    connectable = create_engine(resolve_url(config), poolclass=pool.NullPool)
    # Reuse the shared listener so the migration runs on a WAL + FK connection
    # (round-1 #1) — duplicating the PRAGMA strings here would risk drift.
    event.listen(connectable, "connect", set_sqlite_pragmas)
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


def _context_active() -> bool:
    """True only inside a real Alembic command (so bare import has no side effects)."""
    try:
        context.is_offline_mode()
    except Exception:
        return False
    return True


def main() -> None:
    config = context.config
    if context.is_offline_mode():
        run_migrations_offline(config)
    else:
        run_migrations_online(config)


if _context_active():
    main()
