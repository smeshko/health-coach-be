"""Shared fixtures for the `app/core` workflow tests (E10·P2).

A migrated temp-file ``app.db`` ``Session`` (mirrors ``tests/services/conftest.py``) so
the ``WEEKLY_PLANNER`` nodes — ``LoadAggregatesNode`` (read) / ``PersistPlanNode`` (write)
— run against the real E2 schema, opened through ``make_engine`` (WAL + ``foreign_keys=ON``).
The endpoint owns the transaction (E10·P3); the fixture hands the node an open session.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

from app.database import make_engine


def migrate(db_path) -> None:
    """Apply the E2 ingest migration to a temp ``app.db`` (real schema)."""
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
