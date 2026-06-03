"""State-table migration tests (E2·P3) — completes app.db to its 9 tables.

Runs E2·P1's Alembic config against a temp **file** DB (test-only `test_db_url`),
introspects schema via PRAGMA, asserts the exact 9-table set (no `profile`), the
round-trip, the cache-key UNIQUE constraints, and migration↔metadata parity (an
empty `compare_metadata` diff after `upgrade head`).
"""

import sqlite3

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

import app.database.models  # noqa: F401 — register all nine models on Base.metadata
from app.database import Base, make_engine

NINE_TABLES = {
    "records",
    "workouts",
    "workout_statistics",
    "activity_summary",
    "daily_metrics",
    "checkins",
    "strength_tests",
    "plans",
    "suggestions",
}


def _make_cfg(db_path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.attributes["test_db_url"] = f"sqlite:///{db_path}"
    return cfg


def _affinity(declared_type: str) -> str:
    t = declared_type.upper()
    if "INT" in t:
        return "INTEGER"
    if any(s in t for s in ("CHAR", "CLOB", "TEXT")):
        return "TEXT"
    if "BLOB" in t or t == "":
        return "BLOB"
    if any(s in t for s in ("REAL", "FLOA", "DOUB")):
        return "REAL"
    return "NUMERIC"


def _table_info(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {
        r[1]: {"affinity": _affinity(r[2]), "notnull": r[3], "pk": r[5]}
        for r in rows
    }


def _has_unique_index(conn, table, cols):
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        if not row[2]:
            continue
        idx_cols = [r[2] for r in conn.execute(f"PRAGMA index_info({row[1]})").fetchall()]
        if idx_cols == list(cols):
            return True
    return False


def _user_tables(conn):
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
        ).fetchall()
    }


@pytest.fixture
def migrated_db(tmp_path):
    db_path = tmp_path / "app.db"
    command.upgrade(_make_cfg(db_path), "head")
    with sqlite3.connect(db_path) as conn:
        yield conn


def test_exactly_nine_tables_no_profile(migrated_db):
    tables = _user_tables(migrated_db)
    assert tables == NINE_TABLES
    assert "profile" not in tables


def test_round_trip_full_chain(tmp_path):
    db_path = tmp_path / "rt.db"
    cfg = _make_cfg(db_path)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    with sqlite3.connect(db_path) as conn:
        assert not (_user_tables(conn) & NINE_TABLES)  # none of the nine remain
    command.upgrade(cfg, "head")
    with sqlite3.connect(db_path) as conn:
        assert _user_tables(conn) == NINE_TABLES


def test_daily_metrics_migrated_columns(migrated_db):
    info = _table_info(migrated_db, "daily_metrics")
    assert info["date"]["pk"] == 1
    assert info["date"]["notnull"] == 1
    assert info["date"]["affinity"] == "TEXT"
    for col in ("steps", "hard_day", "readiness_score"):
        assert info[col]["affinity"] == "INTEGER", col
    for col in ("sleep_h", "active_energy", "z5_min", "water_in_l", "body_weight"):
        assert info[col]["affinity"] == "REAL", col
    assert info["band"]["affinity"] == "TEXT"


def test_checkins_migrated_columns(migrated_db):
    info = _table_info(migrated_db, "checkins")
    assert info["date"]["pk"] == 1
    assert info["date"]["notnull"] == 1
    assert "body_weight" not in info


def test_strength_tests_unique_iso_week(migrated_db):
    assert _has_unique_index(migrated_db, "strength_tests", ["iso_week"])


def test_plans_payload_not_null_and_unique_iso_week(migrated_db):
    info = _table_info(migrated_db, "plans")
    assert info["id"]["pk"] == 1
    assert info["iso_week"]["notnull"] == 1
    assert info["payload"]["notnull"] == 1
    assert _has_unique_index(migrated_db, "plans", ["iso_week"])


def test_suggestions_payload_not_null_unique_date_nullable_gate_reason(migrated_db):
    info = _table_info(migrated_db, "suggestions")
    assert info["id"]["pk"] == 1
    assert info["date"]["notnull"] == 1
    assert info["payload"]["notnull"] == 1
    assert info["gate_reason"]["notnull"] == 0
    assert info["safety_gate_tripped"]["affinity"] == "INTEGER"
    assert _has_unique_index(migrated_db, "suggestions", ["date"])


def test_migration_matches_metadata(tmp_path):
    # Parity: the completed state_tables revision matches Base.metadata exactly, so
    # no model table is missing from the migration (guards against a partial revision).
    db_path = tmp_path / "parity.db"
    command.upgrade(_make_cfg(db_path), "head")
    engine = make_engine(db_path)
    try:
        with engine.connect() as conn:
            mc = MigrationContext.configure(conn)
            diff = compare_metadata(mc, Base.metadata)
    finally:
        engine.dispose()
    assert diff == [], diff
