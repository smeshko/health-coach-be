"""Ingest-model constraint tests (E2·P2).

Exercises UNIQUE / FK / NOT-NULL behaviour over a `make_engine(temp)` connection —
which carries E2·P1's WAL + `foreign_keys=ON` listener, so the FK is actually
enforced. The schema is created by running the real Alembic migration on the temp
file, then the same file is opened via `make_engine`. These are constraint checks
(raw duplicate inserts), not the `/sync` upsert write path (that is E5).
"""

import sqlite3

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from app.database import make_engine


def _migrate(db_path):
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.attributes["test_db_url"] = f"sqlite:///{db_path}"
    command.upgrade(cfg, "head")


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "models.db"
    _migrate(db_path)
    eng = make_engine(db_path)
    yield eng
    eng.dispose()


# ----------------------------- records (TASK-001) -----------------------------

def test_records_null_uuid_rows_both_insert(engine):
    # Seeded rows (E4) carry no HealthKit UUID; NULLs are distinct under UNIQUE.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO records (type, start_date, origin) VALUES ('HKt', '2026-01-01T00:00:00+02:00', 'seed')"
        )
        conn.exec_driver_sql(
            "INSERT INTO records (type, start_date, origin) VALUES ('HKt', '2026-01-02T00:00:00+02:00', 'seed')"
        )
    with sqlite3.connect(engine.url.database) as raw:
        assert raw.execute("SELECT COUNT(*) FROM records WHERE uuid IS NULL").fetchone()[0] == 2


def test_records_duplicate_non_null_uuid_rejected(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO records (uuid, type, start_date, origin) VALUES ('U1', 'HKt', '2026-01-01T00:00:00+02:00', 'sync')"
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO records (uuid, type, start_date, origin) VALUES ('U1', 'HKt', '2026-01-02T00:00:00+02:00', 'sync')"
        )


# ------------------- workouts + workout_statistics (TASK-002) -----------------

def test_workouts_null_uuid_rows_both_insert(engine):
    # The E4 90-day seed path: workouts mirror records (NULL uuid is seedable).
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO workouts (activity_type, start_date, origin) VALUES ('running', '2026-01-01T06:00:00+02:00', 'seed')"
        )
        conn.exec_driver_sql(
            "INSERT INTO workouts (activity_type, start_date, origin) VALUES ('boxing', '2026-01-02T06:00:00+02:00', 'seed')"
        )
    with sqlite3.connect(engine.url.database) as raw:
        assert raw.execute("SELECT COUNT(*) FROM workouts WHERE uuid IS NULL").fetchone()[0] == 2


def test_workouts_duplicate_non_null_uuid_rejected(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO workouts (uuid, activity_type, start_date, origin) VALUES ('W1', 'running', '2026-01-01T06:00:00+02:00', 'sync')"
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO workouts (uuid, activity_type, start_date, origin) VALUES ('W1', 'boxing', '2026-01-02T06:00:00+02:00', 'sync')"
        )


def test_workout_statistics_orphan_workout_id_rejected(engine):
    # FK enforced via E2·P1's PRAGMA foreign_keys=ON (carried by make_engine).
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO workout_statistics (workout_id, type) VALUES (9999, 'HKQuantityTypeIdentifierHeartRate')"
        )
