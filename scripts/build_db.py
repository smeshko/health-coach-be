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

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

# Repo root is `backend/`; the corpus lives in the sibling `../db/` (DB.md §6).
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XML = REPO_ROOT.parent / "db" / "export.xml"
DEFAULT_DB = REPO_ROOT.parent / "db" / "baseline.db"


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
