"""Engine / session / WAL-pragma tests (E2·P1 TASK-001).

The runtime engine is **lazy** (`get_engine()`), never built at import — so these
tests clear the `get_settings`/`get_engine` caches around each case and exercise a
real **file** DB (in-memory SQLite can report a different journal mode).
"""

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.settings import get_settings
from app.database import (
    SessionLocal,
    get_engine,
    get_session,
    make_engine,
    set_sqlite_pragmas,
)

VALID_TOKEN = "test-api-token-0123456789"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clear_caches():
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()


def _set_required_env(monkeypatch, db_path):
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", str(db_path))


def test_public_api_imports():
    # Re-exports resolve from the package root (round-1 #1 surface).
    assert callable(make_engine)
    assert callable(get_engine)
    assert callable(set_sqlite_pragmas)
    assert callable(SessionLocal)
    assert callable(get_session)


def test_make_engine_sets_wal_and_foreign_keys(tmp_path):
    # Factory-arg path: a fresh connection is in WAL and enforces FKs.
    engine = make_engine(tmp_path / "app.db")
    try:
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    finally:
        engine.dispose()


def test_get_engine_reads_app_db_path_from_settings(tmp_path, monkeypatch):
    # Separate from the factory-arg test: proves the runtime engine is sourced
    # from settings.app_db_path, not a literal or the make_engine arg (round-1 #4).
    db_path = tmp_path / "from_settings.db"
    _set_required_env(monkeypatch, db_path)
    get_settings.cache_clear()
    get_engine.cache_clear()
    assert get_engine().url.database == str(db_path)


def test_session_local_yields_usable_session(tmp_path, monkeypatch):
    db_path = tmp_path / "sess.db"
    _set_required_env(monkeypatch, db_path)
    get_settings.cache_clear()
    get_engine.cache_clear()
    session = SessionLocal()
    try:
        assert session.execute(text("SELECT 1")).scalar() == 1
    finally:
        session.close()


def test_get_session_opens_and_closes(tmp_path, monkeypatch):
    db_path = tmp_path / "ctx.db"
    _set_required_env(monkeypatch, db_path)
    get_settings.cache_clear()
    get_engine.cache_clear()
    # get_session is a generator dependency; drive it as a context manager.
    with contextmanager(get_session)() as session:
        assert session.execute(text("SELECT 1")).scalar() == 1
        assert session.is_active
    # After the block the session is closed (no leak).
    assert not session.in_transaction()


def test_importing_engine_without_app_db_path_does_not_raise(tmp_path):
    # Import-isolated (round-1 #1): in a clean subprocess with APP_DB_PATH unset and
    # no .env discoverable (cwd is a temp dir), importing the engine module must NOT
    # raise — i.e. no runtime engine / settings access happens at import time, and
    # set_sqlite_pragmas is referenceable on its own for Alembic to reuse.
    code = (
        "import app.database.engine as e\n"
        "assert callable(e.set_sqlite_pragmas)\n"
        "print('OK')\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "APP_DB_PATH"}
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
