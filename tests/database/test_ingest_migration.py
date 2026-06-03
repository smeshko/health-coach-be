"""Ingest-table migration schema tests (E2·P2).

Runs E2·P1's Alembic config against a temp **file** DB (test-only `test_db_url`
override) and introspects the migrated schema with `PRAGMA`. Column types are
asserted by **SQLite affinity** (the contract is "REAL/INTEGER/TEXT affinity",
not a literal declared-type string). Extended task by task: records (TASK-001),
workouts + workout_statistics (TASK-002), activity_summary (TASK-003).
"""

import sqlite3

import pytest
from alembic import command
from alembic.config import Config

INGEST_TABLES = {"records", "workouts", "workout_statistics", "activity_summary"}


def _make_cfg(db_path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.attributes["test_db_url"] = f"sqlite:///{db_path}"
    return cfg


def _affinity(declared_type: str) -> str:
    # SQLite type-affinity algorithm (order matters). DB.md talks in affinities.
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
    # name -> {"affinity", "notnull", "pk"}
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {
        r[1]: {"affinity": _affinity(r[2]), "notnull": r[3], "pk": r[5]}
        for r in rows
    }


def _indexes(conn, table):
    # list of (unique: bool, [columns])
    out = []
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        idx_name, unique = row[1], bool(row[2])
        cols = [r[2] for r in conn.execute(f"PRAGMA index_info({idx_name})").fetchall()]
        out.append((unique, cols))
    return out


def _has_index(conn, table, cols, *, unique):
    return any(u == unique and c == list(cols) for u, c in _indexes(conn, table))


def _table_names(conn):
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


@pytest.fixture
def migrated_db(tmp_path):
    db_path = tmp_path / "app.db"
    command.upgrade(_make_cfg(db_path), "head")
    with sqlite3.connect(db_path) as conn:
        yield conn


# ----------------------------- records (TASK-001) -----------------------------

def test_records_table_exists(migrated_db):
    assert "records" in _table_names(migrated_db)


def test_records_columns_and_types(migrated_db):
    info = _table_info(migrated_db, "records")
    assert info["id"]["affinity"] == "INTEGER"
    assert info["id"]["pk"] == 1
    assert info["uuid"]["affinity"] == "TEXT"
    assert info["uuid"]["notnull"] == 0
    assert info["type"]["affinity"] == "TEXT"
    assert info["type"]["notnull"] == 1
    assert info["unit"]["affinity"] == "TEXT"
    assert info["unit"]["notnull"] == 0
    assert info["value"]["affinity"] == "REAL"
    assert info["value_text"]["affinity"] == "TEXT"
    for prov in ("source_name", "source_version", "device", "creation_date"):
        assert info[prov]["affinity"] == "TEXT"
    assert info["start_date"]["affinity"] == "TEXT"
    assert info["start_date"]["notnull"] == 1
    assert info["end_date"]["affinity"] == "TEXT"
    assert info["end_date"]["notnull"] == 0
    assert info["origin"]["affinity"] == "TEXT"
    assert info["origin"]["notnull"] == 1


def test_records_indexes(migrated_db):
    assert _has_index(migrated_db, "records", ["uuid"], unique=True)
    assert _has_index(migrated_db, "records", ["type", "start_date"], unique=False)
    assert _has_index(migrated_db, "records", ["start_date"], unique=False)


def test_round_trip_with_ingest_tables(tmp_path):
    db_path = tmp_path / "rt.db"
    cfg = _make_cfg(db_path)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    with sqlite3.connect(db_path) as conn:
        # After downgrade base, none of the ingest tables remain.
        assert not (_table_names(conn) & INGEST_TABLES)
    command.upgrade(cfg, "head")  # round-trips back cleanly (FK drop order safe)
    with sqlite3.connect(db_path) as conn:
        assert "records" in _table_names(conn)
