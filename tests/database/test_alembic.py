"""Alembic scaffolding tests (E2·P1 TASK-004).

Alembic targets the runtime database **only** — the URL is owned by
`settings.app_db_path`, a static `.ini` `sqlalchemy.url` is ignored, and the only
override is the explicit test-only `config.attributes["test_db_url"]`. The initial
migration is empty (no tables yet) but must round-trip, and `env.py` must attach
the WAL/FK listener so the migrated file ends up in WAL.
"""

import importlib.util
import sqlite3
import subprocess
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.core.settings import get_settings
from app.database.base import Base

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / "alembic" / "env.py"
VALID_TOKEN = "test-api-token-0123456789"


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _load_env():
    # Load alembic/env.py without running migrations: outside an Alembic command the
    # module-level dispatch is guarded off, so resolve_url/target_metadata are usable.
    spec = importlib.util.spec_from_file_location("alembic_env_under_test", ENV_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_cfg(db_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.attributes["test_db_url"] = f"sqlite:///{db_path}"
    return cfg


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {r[0] for r in rows}


def test_round_trip_on_temp_file_db(tmp_path):
    db_path = tmp_path / "app.db"
    cfg = _make_cfg(db_path)

    command.upgrade(cfg, "head")
    with sqlite3.connect(db_path) as conn:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    assert version == [("0001",)]

    command.downgrade(cfg, "base")
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    assert rows == []  # version row removed at base

    command.upgrade(cfg, "head")  # round-trips back to head
    with sqlite3.connect(db_path) as conn:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchall()
    assert version == [("0001",)]


def test_no_application_tables_after_upgrade(tmp_path):
    db_path = tmp_path / "app.db"
    command.upgrade(_make_cfg(db_path), "head")
    # The initial migration is empty: only Alembic's bookkeeping table exists.
    assert _table_names(db_path) == {"alembic_version"}


def test_migrated_file_is_wal_via_raw_connection(tmp_path):
    # Non-circular (round-3 #1): open the migrated file with a RAW sqlite3.connect
    # (no listener, not via make_engine) — it can only report 'wal' if env.py itself
    # attached set_sqlite_pragmas during the migration.
    db_path = tmp_path / "app.db"
    command.upgrade(_make_cfg(db_path), "head")
    with sqlite3.connect(db_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_resolve_url_uses_settings_without_override(tmp_path, monkeypatch):
    db_path = tmp_path / "settings_app.db"
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", str(db_path))
    get_settings.cache_clear()
    env = _load_env()
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    assert env.resolve_url(cfg) == f"sqlite:///{db_path}"


def test_resolve_url_prefers_test_override(tmp_path):
    env = _load_env()
    db_path = tmp_path / "override.db"
    cfg = _make_cfg(db_path)
    assert env.resolve_url(cfg) == f"sqlite:///{db_path}"


def test_static_sqlalchemy_url_is_ignored(tmp_path, monkeypatch):
    # A stale/static .ini url must never redirect a migration (round-1 #2).
    db_path = tmp_path / "settings_app.db"
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", str(db_path))
    get_settings.cache_clear()
    env = _load_env()
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", "sqlite:///bogus.db")
    # Planted bogus url is ignored: resolve_url still returns the settings path.
    assert env.resolve_url(cfg) == f"sqlite:///{db_path}"
    assert "bogus" not in env.resolve_url(cfg)


def test_target_metadata_is_base_metadata():
    env = _load_env()
    assert env.target_metadata is Base.metadata


def test_no_baseline_reference_in_alembic():
    # Alembic must never name the read-only build input.
    result = subprocess.run(
        ["grep", "-rn", "baseline", "alembic", "alembic.ini"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, f"unexpected match:\n{result.stdout}"
