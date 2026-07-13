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


# --------------------------------------------------------------------------- #
# Phase 19.4 (0004): canonicalize plans.iso_week to zero-padded %G-W%V.
# --------------------------------------------------------------------------- #
def _insert_plan(conn, *, iso_week, created_at, payload="{}"):
    conn.execute(
        "INSERT INTO plans (iso_week, payload, model, constitution_version, created_at) "
        "VALUES (?, ?, 'test', 'v1', ?)",
        (iso_week, payload, created_at),
    )


def test_0004_canonicalizes_unpadded_iso_week(tmp_path):
    db_path = tmp_path / "canon.db"
    cfg = _make_cfg(db_path)
    command.upgrade(cfg, "0003")  # stop BEFORE the canonicalization migration
    with sqlite3.connect(db_path) as conn:
        _insert_plan(conn, iso_week="2026-W1", created_at="2026-01-05T00:00:00+02:00")
        _insert_plan(conn, iso_week="2026-W02", created_at="2026-01-12T00:00:00+02:00")  # already canonical
        conn.commit()

    command.upgrade(cfg, "0004")

    with sqlite3.connect(db_path) as conn:
        weeks = {r[0] for r in conn.execute("SELECT iso_week FROM plans").fetchall()}
    assert weeks == {"2026-W01", "2026-W02"}  # W1 padded, W02 untouched


def test_0004_resolves_padded_unpadded_collision_keeping_newest(tmp_path):
    db_path = tmp_path / "collide.db"
    cfg = _make_cfg(db_path)
    command.upgrade(cfg, "0003")
    with sqlite3.connect(db_path) as conn:
        _insert_plan(conn, iso_week="2026-W1", created_at="2026-01-05T00:00:00+02:00", payload='{"old":1}')
        _insert_plan(conn, iso_week="2026-W01", created_at="2026-01-06T00:00:00+02:00", payload='{"new":1}')
        conn.commit()

    command.upgrade(cfg, "0004")  # must not violate UNIQUE(iso_week)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT iso_week, payload FROM plans").fetchall()
    assert rows == [("2026-W01", '{"new":1}')]  # collision resolved, newest kept


def test_0004_collision_survivor_is_dst_safe(tmp_path):
    # Across Sofia's autumn DST rollback, the raw offset string misleads: the LATER instant
    # carries +02:00 and sorts lexicographically BELOW the earlier +03:00 one. The survivor
    # must be chosen by the actual UTC instant (review #2.1), so the +02:00 row wins.
    db_path = tmp_path / "dst.db"
    cfg = _make_cfg(db_path)
    command.upgrade(cfg, "0003")
    with sqlite3.connect(db_path) as conn:
        _insert_plan(conn, iso_week="2026-W43", created_at="2026-10-25T03:50:00+03:00", payload='{"earlier":1}')
        _insert_plan(conn, iso_week="2026-W043", created_at="2026-10-25T03:10:00+02:00", payload='{"later":1}')
        conn.commit()

    command.upgrade(cfg, "0004")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT iso_week, payload FROM plans").fetchall()
    # 2026-10-25T03:10+02:00 == 01:10 UTC is LATER than 03:50+03:00 == 00:50 UTC → later wins.
    assert rows == [("2026-W43", '{"later":1}')]


def test_0004_collision_null_created_at_falls_back_to_id(tmp_path):
    # Null/missing timestamps must not make the survivor SELECT-order-dependent: a real
    # timestamp outranks a null, and among equals the higher id wins (deterministic).
    db_path = tmp_path / "nulls.db"
    cfg = _make_cfg(db_path)
    command.upgrade(cfg, "0003")
    with sqlite3.connect(db_path) as conn:
        _insert_plan(conn, iso_week="2026-W1", created_at=None, payload='{"null":1}')
        _insert_plan(conn, iso_week="2026-W01", created_at="2026-01-06T00:00:00+02:00", payload='{"dated":1}')
        conn.commit()

    command.upgrade(cfg, "0004")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT iso_week, payload FROM plans").fetchall()
    assert rows == [("2026-W01", '{"dated":1}')]  # the real timestamp beats the null


def test_0004_three_alias_collision_keeps_one(tmp_path):
    db_path = tmp_path / "three.db"
    cfg = _make_cfg(db_path)
    command.upgrade(cfg, "0003")
    with sqlite3.connect(db_path) as conn:
        _insert_plan(conn, iso_week="2026-W3", created_at="2026-01-12T00:00:00+02:00")
        _insert_plan(conn, iso_week="2026-W03", created_at="2026-01-14T00:00:00+02:00", payload='{"win":1}')
        _insert_plan(conn, iso_week="2026-W003", created_at="2026-01-13T00:00:00+02:00")
        conn.commit()

    command.upgrade(cfg, "0004")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT iso_week, payload FROM plans").fetchall()
    assert rows == [("2026-W03", '{"win":1}')]


def test_0004_empty_table_and_idempotent(tmp_path):
    db_path = tmp_path / "empty.db"
    cfg = _make_cfg(db_path)
    command.upgrade(cfg, "head")  # empty table through 0004 — no error
    with sqlite3.connect(db_path) as conn:
        _insert_plan(conn, iso_week="2026-W05", created_at="2026-01-26T00:00:00+02:00")
        conn.commit()
    # Re-running the canonicalization logic over already-canonical rows is a no-op.
    command.downgrade(cfg, "0003")
    command.upgrade(cfg, "0004")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT iso_week FROM plans").fetchall() == [("2026-W05",)]
