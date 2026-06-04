"""Offline ETL: stream-parse Apple Health export.xml into the read-only corpus.

`baseline.db` is a raw historical dump regenerated *wholesale* from `export.xml`
and **never opened at runtime** (DB.md §0, §3; ARCHITECTURE §3, §6) — the runtime
reads `app.db` only. So this is a standalone offline script: stdlib `sqlite3` +
`xml.etree.ElementTree` only, **no** `app/` / FastAPI / SQLAlchemy / Alembic
import.

Four raw tables mirror the `app.db` ingest shape *minus* the runtime-only deltas
(`uuid` / `origin` / `effort_score` / `physical_effort`, the `records` PK, and the
`date_components`→`date` rename — all of which arrive only at the E4·P3 seed):

  records            - all HKQuantityType / HKCategoryType records (no PK)
  workouts           - one row per <Workout> (local autoincrement id is the
                       child-statistics FK target only, not the runtime uuid)
  workout_statistics - <WorkoutStatistics> children, keyed to a workout
  activity_summary   - daily Apple Watch rings (keeps Apple's date_components)

Timestamps are stored as ISO-8601 TEXT exactly as Apple emits them
(e.g. "2025-04-15 07:32:11 +0300"), offset preserved — they sort correctly and
stay debuggable (DB.md §0).

The corpus is large (~3.5M records, 2019→2026), so the parse MUST stream:
`ET.iterparse(events=("end",))` + `elem.clear()` after each element. Never load
the whole DOM.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Sequence
from pathlib import Path

# Repo root is `backend/`; the corpus lives in the sibling `../db/` (DB.md §6).
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XML = REPO_ROOT.parent / "db" / "export.xml"
DEFAULT_DB = REPO_ROOT.parent / "db" / "baseline.db"

# The four raw tables, defined once so the DROP list and the count report can
# never drift apart.
TABLES = ("records", "workouts", "workout_statistics", "activity_summary")

# Flush threshold for batched executemany — bounds peak memory to one batch.
BATCH = 10_000

# Distance statistic types used to backfill workouts.total_distance when recent
# watchOS stashes distance in the child element instead of the Workout attribute.
_DISTANCE_STAT_TYPES = (
    "HKQuantityTypeIdentifierDistanceWalkingRunning",
    "HKQuantityTypeIdentifierDistanceCycling",
    "HKQuantityTypeIdentifierDistanceSwimming",
    "HKQuantityTypeIdentifierDistanceDownhillSnowSports",
)


def to_float(v: str | None) -> float | None:
    """Coerce an attribute string to float; blank/non-numeric → None."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def to_int(v: str | None) -> int | None:
    """Coerce an attribute string to int; blank/non-numeric → None."""
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _record_row(attrib: dict[str, str]) -> dict[str, object | None]:
    raw_value = attrib.get("value")
    return {
        "type": attrib.get("type"),
        "unit": attrib.get("unit"),
        # Quantity types are numeric; category types carry an enum string
        # (e.g. HKCategoryValueSleepAnalysisAsleepCore) a REAL column can't hold,
        # so keep both a coerced float and the raw value_text (DB.md §1).
        "value": to_float(raw_value),
        "value_text": raw_value,
        "source_name": attrib.get("sourceName"),
        "source_version": attrib.get("sourceVersion"),
        "device": attrib.get("device"),
        "creation_date": attrib.get("creationDate"),
        "start_date": attrib.get("startDate"),
        "end_date": attrib.get("endDate"),
    }


def _statistics_row(attrib: dict[str, str]) -> dict[str, object | None]:
    return {
        "type": attrib.get("type"),
        "start_date": attrib.get("startDate"),
        "end_date": attrib.get("endDate"),
        "sum": to_float(attrib.get("sum")),
        "average": to_float(attrib.get("average")),
        "minimum": to_float(attrib.get("minimum")),
        "maximum": to_float(attrib.get("maximum")),
        "unit": attrib.get("unit"),
    }


def _workout_row(elem: ET.Element) -> dict[str, object | None]:
    attrib = elem.attrib
    return {
        "activity_type": attrib.get("workoutActivityType"),
        "duration": to_float(attrib.get("duration")),
        "duration_unit": attrib.get("durationUnit"),
        "total_distance": to_float(attrib.get("totalDistance")),
        "total_distance_unit": attrib.get("totalDistanceUnit"),
        "total_energy_burned": to_float(attrib.get("totalEnergyBurned")),
        "total_energy_burned_unit": attrib.get("totalEnergyBurnedUnit"),
        "source_name": attrib.get("sourceName"),
        "source_version": attrib.get("sourceVersion"),
        "device": attrib.get("device"),
        "creation_date": attrib.get("creationDate"),
        "start_date": attrib.get("startDate"),
        "end_date": attrib.get("endDate"),
        # <WorkoutStatistics> is a child element — read it inside the workout's
        # `end` event, before elem.clear(), and key it to the parent in build().
        "statistics": [
            _statistics_row(st.attrib) for st in elem.findall("WorkoutStatistics")
        ],
    }


def _activity_summary_row(attrib: dict[str, str]) -> dict[str, object | None]:
    return {
        "date_components": attrib.get("dateComponents"),
        "active_energy_burned": to_float(attrib.get("activeEnergyBurned")),
        "active_energy_burned_goal": to_float(attrib.get("activeEnergyBurnedGoal")),
        "active_energy_burned_unit": attrib.get("activeEnergyBurnedUnit"),
        "apple_exercise_time": to_float(attrib.get("appleExerciseTime")),
        "apple_exercise_time_goal": to_float(attrib.get("appleExerciseTimeGoal")),
        "apple_stand_hours": to_int(attrib.get("appleStandHours")),
        "apple_stand_hours_goal": to_int(attrib.get("appleStandHoursGoal")),
        "apple_move_time": to_float(attrib.get("appleMoveTime")),
        "apple_move_time_goal": to_float(attrib.get("appleMoveTimeGoal")),
    }


def iter_health_elements(
    xml_path: str | Path,
) -> Iterator[tuple[str, dict[str, object | None]]]:
    """Stream `export.xml`, yielding `(kind, row)` for each top-level element.

    `kind` is one of `"record"`, `"workout"`, `"activity_summary"`. Workout rows
    carry their child `WorkoutStatistics` under `row["statistics"]`.

    Memory-bounded by construction: `iterparse(events=("end",))` reads each
    element as it closes, and `elem.clear()` drops it (and its children) right
    after — the DOM is never materialized.
    """
    for _, elem in ET.iterparse(str(xml_path), events=("end",)):
        tag = elem.tag
        if tag == "Record":
            yield "record", _record_row(elem.attrib)
            elem.clear()
        elif tag == "Workout":
            yield "workout", _workout_row(elem)
            elem.clear()
        elif tag == "ActivitySummary":
            yield "activity_summary", _activity_summary_row(elem.attrib)
            elem.clear()


def init_schema(conn: sqlite3.Connection) -> None:
    """Drop + recreate the four raw tables (wholesale, idempotent rebuild).

    DROP TABLE also clears each table's `sqlite_sequence` row, so the recreated
    AUTOINCREMENT `workouts.id` restarts at 1 and a deterministic re-parse
    re-assigns the same ids — making re-runs content-identical (DB.md §0; epic R1).
    """
    conn.executescript(
        """
        DROP TABLE IF EXISTS records;
        DROP TABLE IF EXISTS workouts;
        DROP TABLE IF EXISTS workout_statistics;
        DROP TABLE IF EXISTS activity_summary;

        CREATE TABLE records (
            type           TEXT NOT NULL,
            unit           TEXT,
            value          REAL,
            -- Raw value as Apple emits it. For HKQuantityType the numeric string;
            -- for HKCategoryType the enum (e.g. HKCategoryValueSleepAnalysisAsleepCore)
            -- which `value` cannot hold. Query value_text for sleep stages etc.
            value_text     TEXT,
            source_name    TEXT,
            source_version TEXT,
            device         TEXT,
            creation_date  TEXT,
            start_date     TEXT NOT NULL,
            end_date       TEXT
        );

        CREATE TABLE workouts (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_type            TEXT NOT NULL,
            duration                 REAL,
            duration_unit            TEXT,
            total_distance           REAL,
            total_distance_unit      TEXT,
            total_energy_burned      REAL,
            total_energy_burned_unit TEXT,
            source_name              TEXT,
            source_version           TEXT,
            device                   TEXT,
            creation_date            TEXT,
            start_date               TEXT NOT NULL,
            end_date                 TEXT
        );

        CREATE TABLE workout_statistics (
            workout_id INTEGER NOT NULL,
            type       TEXT NOT NULL,
            start_date TEXT,
            end_date   TEXT,
            sum        REAL,
            average    REAL,
            minimum    REAL,
            maximum    REAL,
            unit       TEXT,
            FOREIGN KEY (workout_id) REFERENCES workouts(id)
        );

        CREATE TABLE activity_summary (
            date_components            TEXT NOT NULL,
            active_energy_burned       REAL,
            active_energy_burned_goal  REAL,
            active_energy_burned_unit  TEXT,
            apple_exercise_time        REAL,
            apple_exercise_time_goal   REAL,
            apple_stand_hours          INTEGER,
            apple_stand_hours_goal     INTEGER,
            apple_move_time            REAL,
            apple_move_time_goal       REAL
        );
        """
    )
    conn.commit()


def build_indexes(conn: sqlite3.Connection) -> None:
    """Create read-path indexes mirroring the existing dump (minus workout_events)."""
    conn.executescript(
        """
        CREATE INDEX idx_records_type_start  ON records (type, start_date);
        CREATE INDEX idx_records_start       ON records (start_date);
        CREATE INDEX idx_workouts_type_start ON workouts (activity_type, start_date);
        CREATE INDEX idx_workouts_start      ON workouts (start_date);
        CREATE INDEX idx_workout_stats_wid   ON workout_statistics (workout_id, type);
        CREATE INDEX idx_activity_summary_dt ON activity_summary (date_components);
        """
    )
    conn.commit()


def _backfill_total_distance(conn: sqlite3.Connection) -> int:
    """Fill workouts.total_distance from a distance WorkoutStatistics child when
    Apple omits the top-level attribute (recent watchOS). Deterministic, so it
    reproduces on every rebuild. Returns the number of rows updated."""
    placeholders = ",".join("?" for _ in _DISTANCE_STAT_TYPES)
    cur = conn.execute(
        f"""
        UPDATE workouts
           SET total_distance = (
                   SELECT ws.sum FROM workout_statistics ws
                    WHERE ws.workout_id = workouts.id
                      AND ws.type IN ({placeholders})
                    LIMIT 1
               ),
               total_distance_unit = COALESCE(
                   total_distance_unit,
                   (SELECT ws.unit FROM workout_statistics ws
                     WHERE ws.workout_id = workouts.id
                       AND ws.type IN ({placeholders})
                     LIMIT 1)
               )
         WHERE total_distance IS NULL
           AND EXISTS (
                   SELECT 1 FROM workout_statistics ws
                    WHERE ws.workout_id = workouts.id
                      AND ws.type IN ({placeholders})
               );
        """,
        _DISTANCE_STAT_TYPES * 3,
    )
    conn.commit()
    return cur.rowcount


def summarize(conn: sqlite3.Connection) -> dict[str, int]:
    """Per-table row counts for the four tables — the build's sanity-check report.

    Reuses the single `TABLES` constant so the report can never drift from the
    schema's DROP/CREATE list (epic §3 E4·P1; §4 "non-zero counts").
    """
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}


def build(xml_path: str | Path, db_path: str | Path) -> dict[str, int]:
    """Stream `xml_path` into `db_path` as a raw wholesale rebuild; return counts.

    Idempotent: `init_schema` drops + recreates the four tables, so a re-run over
    the same input yields identical contents (no stale rows, no duplication).
    """
    conn = sqlite3.connect(str(db_path))
    # Tuned for bulk insert; durability mid-import is unnecessary (rebuildable).
    conn.execute("PRAGMA journal_mode = OFF;")
    conn.execute("PRAGMA synchronous = OFF;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    try:
        init_schema(conn)
        cur = conn.cursor()

        rec_buf: list[tuple] = []
        wstat_buf: list[tuple] = []
        summary_buf: list[tuple] = []

        def flush_records() -> None:
            if rec_buf:
                cur.executemany(
                    "INSERT INTO records (type, unit, value, value_text, source_name, "
                    "source_version, device, creation_date, start_date, end_date) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    rec_buf,
                )
                rec_buf.clear()

        def flush_stats() -> None:
            if wstat_buf:
                cur.executemany(
                    "INSERT INTO workout_statistics (workout_id, type, start_date, end_date, "
                    "sum, average, minimum, maximum, unit) VALUES (?,?,?,?,?,?,?,?,?)",
                    wstat_buf,
                )
                wstat_buf.clear()

        def flush_summaries() -> None:
            if summary_buf:
                cur.executemany(
                    "INSERT INTO activity_summary (date_components, active_energy_burned, "
                    "active_energy_burned_goal, active_energy_burned_unit, apple_exercise_time, "
                    "apple_exercise_time_goal, apple_stand_hours, apple_stand_hours_goal, "
                    "apple_move_time, apple_move_time_goal) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    summary_buf,
                )
                summary_buf.clear()

        for kind, row in iter_health_elements(xml_path):
            if kind == "record":
                rec_buf.append(
                    (
                        row["type"],
                        row["unit"],
                        row["value"],
                        row["value_text"],
                        row["source_name"],
                        row["source_version"],
                        row["device"],
                        row["creation_date"],
                        row["start_date"],
                        row["end_date"],
                    )
                )
                if len(rec_buf) >= BATCH:
                    flush_records()
            elif kind == "workout":
                cur.execute(
                    "INSERT INTO workouts (activity_type, duration, duration_unit, "
                    "total_distance, total_distance_unit, total_energy_burned, "
                    "total_energy_burned_unit, source_name, source_version, device, "
                    "creation_date, start_date, end_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        row["activity_type"],
                        row["duration"],
                        row["duration_unit"],
                        row["total_distance"],
                        row["total_distance_unit"],
                        row["total_energy_burned"],
                        row["total_energy_burned_unit"],
                        row["source_name"],
                        row["source_version"],
                        row["device"],
                        row["creation_date"],
                        row["start_date"],
                        row["end_date"],
                    ),
                )
                wid = cur.lastrowid
                for st in row["statistics"]:  # type: ignore[union-attr]
                    wstat_buf.append(
                        (
                            wid,
                            st["type"],
                            st["start_date"],
                            st["end_date"],
                            st["sum"],
                            st["average"],
                            st["minimum"],
                            st["maximum"],
                            st["unit"],
                        )
                    )
                if len(wstat_buf) >= BATCH:
                    flush_stats()
            elif kind == "activity_summary":
                summary_buf.append(
                    (
                        row["date_components"],
                        row["active_energy_burned"],
                        row["active_energy_burned_goal"],
                        row["active_energy_burned_unit"],
                        row["apple_exercise_time"],
                        row["apple_exercise_time_goal"],
                        row["apple_stand_hours"],
                        row["apple_stand_hours_goal"],
                        row["apple_move_time"],
                        row["apple_move_time_goal"],
                    )
                )
                if len(summary_buf) >= BATCH:
                    flush_summaries()

        flush_records()
        flush_stats()
        flush_summaries()
        conn.commit()

        build_indexes(conn)
        _backfill_total_distance(conn)
        conn.execute("ANALYZE;")
        conn.commit()

        return summarize(conn)
    finally:
        conn.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the read-only baseline.db corpus from Apple Health export.xml."
    )
    parser.add_argument("--xml", type=Path, default=DEFAULT_XML, help="source export.xml")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="target baseline.db")
    args = parser.parse_args(argv)

    if not args.xml.exists():
        print(f"error: {args.xml} not found", file=sys.stderr)
        return 1

    counts = build(args.xml, args.db)
    print(" ".join(f"{table}={counts[table]}" for table in TABLES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
