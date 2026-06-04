"""Shared fixtures for the `/sync` upsert-service tests (E5·P2).

Each test runs against a fresh temp-file `app.db` with the real E2·P2 ingest schema
applied via the Alembic migration, opened through ``make_engine`` so E2·P1's WAL +
``foreign_keys=ON`` connect listener is active — the actual ``ON CONFLICT`` and FK
paths run, not an in-memory shortcut.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

from app.database import make_engine


def migrate(db_path) -> None:
    """Apply the E2·P2 ingest migration to a temp ``app.db`` (real schema)."""
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.attributes["test_db_url"] = f"sqlite:///{db_path}"
    command.upgrade(cfg, "head")


@pytest.fixture
def session(tmp_path) -> Iterator[Session]:
    """A Session bound to a migrated temp-file ``app.db`` (WAL + FK on)."""
    db_path = tmp_path / "app.db"
    migrate(db_path)
    engine = make_engine(db_path)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()
