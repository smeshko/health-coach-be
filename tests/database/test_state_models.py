"""Derived + coaching-state model constraint tests (E2·P3).

Schema is built with `Base.metadata.create_all(engine)` over a `make_engine(temp)`
connection (carries E2·P1's WAL + `foreign_keys=ON` listener) — **not** Alembic; the
migration round-trip / parity / 9-table checks live in `test_state_migration.py`.
Column types are asserted by SQLite affinity. Extended task by task: daily_metrics
(TASK-001), checkins + strength_tests (TASK-002), plans + suggestions (TASK-003).
"""

import sqlite3

import pytest
from sqlalchemy.exc import IntegrityError

import app.database.models  # noqa: F401 — register all models on Base.metadata
from app.database import Base, make_engine


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


def _indexes(conn, table):
    out = []
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        cols = [r[2] for r in conn.execute(f"PRAGMA index_info({row[1]})").fetchall()]
        out.append((bool(row[2]), cols))
    return out


def _has_unique_index(conn, table, cols):
    return any(u and c == list(cols) for u, c in _indexes(conn, table))


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "state.db")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


# --------------------------- daily_metrics (TASK-001) -------------------------

DAILY_METRICS_REAL = (
    "sleep_h", "hrv_sdnn", "rhr", "hrv_30d_mean", "hrv_30d_sd", "rhr_30d_mean",
    "active_energy", "z1_min", "z2_min", "z3_min", "z4_min", "z5_min",
    "kcal_in", "protein_in_g", "carbs_in_g", "fat_in_g", "fiber_in_g",
    "sodium_in_mg", "water_in_l", "body_weight",
)


def test_daily_metrics_date_pk_not_null_and_affinities(engine):
    with sqlite3.connect(engine.url.database) as conn:
        info = _table_info(conn, "daily_metrics")
    assert info["date"]["affinity"] == "TEXT"
    assert info["date"]["pk"] == 1
    assert info["date"]["notnull"] == 1
    for col in DAILY_METRICS_REAL:
        assert info[col]["affinity"] == "REAL", col
    for col in ("steps", "hard_day", "readiness_score"):
        assert info[col]["affinity"] == "INTEGER", col
    assert info["band"]["affinity"] == "TEXT"
    assert info["computed_at"]["affinity"] == "TEXT"


def test_daily_metrics_readiness_and_band_nullable(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO daily_metrics (date, computed_at) VALUES ('2026-06-01', '2026-06-01T07:00:00+03:00')"
        )
    with sqlite3.connect(engine.url.database) as raw:
        row = raw.execute(
            "SELECT readiness_score, band FROM daily_metrics WHERE date='2026-06-01'"
        ).fetchone()
    assert row == (None, None)


def test_daily_metrics_null_date_rejected(engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO daily_metrics (date) VALUES (NULL)")


# ----------------- checkins + strength_tests (TASK-002) -----------------------

def test_checkins_columns_and_no_body_weight(engine):
    with sqlite3.connect(engine.url.database) as conn:
        info = _table_info(conn, "checkins")
    assert info["date"]["affinity"] == "TEXT"
    assert info["date"]["pk"] == 1
    assert info["date"]["notnull"] == 1
    for col in ("gi_symptoms", "illness", "knee_pain"):
        assert info[col]["affinity"] == "INTEGER", col
    assert info["created_at"]["affinity"] == "TEXT"
    assert info["updated_at"]["affinity"] == "TEXT"
    # Objective-only: weight comes from HealthKit body_mass → daily_metrics.body_weight.
    assert "body_weight" not in info


def test_checkins_null_date_rejected(engine):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO checkins (date) VALUES (NULL)")


def test_strength_tests_columns_and_unique_iso_week(engine):
    with sqlite3.connect(engine.url.database) as conn:
        info = _table_info(conn, "strength_tests")
        assert _has_unique_index(conn, "strength_tests", ["iso_week"])
    assert info["id"]["affinity"] == "INTEGER"
    assert info["id"]["pk"] == 1
    assert info["date"]["affinity"] == "TEXT"
    assert info["date"]["notnull"] == 1
    assert info["iso_week"]["affinity"] == "TEXT"
    assert info["iso_week"]["notnull"] == 1
    assert info["max_pushups"]["affinity"] == "INTEGER"
    assert info["max_pullups"]["affinity"] == "INTEGER"
    assert info["created_at"]["affinity"] == "TEXT"


def test_strength_tests_duplicate_iso_week_rejected(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO strength_tests (date, iso_week, max_pushups) VALUES ('2026-06-01', '2026-W23', 40)"
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO strength_tests (date, iso_week, max_pushups) VALUES ('2026-06-03', '2026-W23', 42)"
        )
