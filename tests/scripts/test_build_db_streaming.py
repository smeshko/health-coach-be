"""TASK-001: streaming parser over export.xml.

Asserts the parse layer yields the expected normalized rows and that the parser
is memory-bounded *by construction* (uses `iterparse` + `elem.clear()`, never
loads the whole DOM) — measuring RSS over the real 1.5 GB corpus is impractical,
so we assert the approach structurally from the source text.
"""

from __future__ import annotations

import gc
import xml.etree.ElementTree as ET


def _by_kind(items: list[tuple[str, dict]]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"record": [], "workout": [], "activity_summary": []}
    for kind, payload in items:
        out[kind].append(payload)
    return out


def test_iter_health_elements_counts(build_db, fixture_xml) -> None:
    items = list(build_db.iter_health_elements(fixture_xml))
    grouped = _by_kind(items)
    assert len(grouped["record"]) == 5
    assert len(grouped["workout"]) == 2
    assert len(grouped["activity_summary"]) == 2
    # Each workout carries its child statistics list.
    stats = [s for w in grouped["workout"] for s in w["statistics"]]
    assert len(stats) == 2


def test_category_vs_quantity_value_split(build_db, fixture_xml) -> None:
    records = _by_kind(list(build_db.iter_health_elements(fixture_xml)))["record"]
    sleep = next(r for r in records if r["type"] == "HKCategoryTypeIdentifierSleepAnalysis")
    # The category enum can't live in a REAL column: value is None, enum in value_text.
    assert sleep["value"] is None
    assert sleep["value_text"] == "HKCategoryValueSleepAnalysisAsleepCore"

    hr = next(r for r in records if r["type"] == "HKQuantityTypeIdentifierHeartRate")
    assert hr["value"] == 62.0
    assert hr["value_text"] == "62"


def test_timestamps_verbatim(build_db, fixture_xml) -> None:
    records = _by_kind(list(build_db.iter_health_elements(fixture_xml)))["record"]
    hr = next(r for r in records if r["type"] == "HKQuantityTypeIdentifierHeartRate")
    # Raw Apple string with offset, not normalized to UTC/DATETIME.
    assert hr["start_date"] == "2025-04-15 07:32:11 +0300"


def test_workout_statistics_attached_to_parent(build_db, fixture_xml) -> None:
    workouts = _by_kind(list(build_db.iter_health_elements(fixture_xml)))["workout"]
    running = next(w for w in workouts if w["activity_type"] == "HKWorkoutActivityTypeRunning")
    assert len(running["statistics"]) == 1
    assert running["statistics"][0]["type"] == "HKQuantityTypeIdentifierHeartRate"
    assert running["statistics"][0]["average"] == 150.0


def test_root_is_drained_during_iteration(build_db, tmp_path) -> None:
    """elem.clear() alone leaves empty shells on the root; the parser must also
    drain the root so live Element count stays bounded (review round-1 #1)."""
    n = 2000
    consume = 1500
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<HealthData>"]
    for i in range(n):
        parts.append(
            '<Record type="HKQuantityTypeIdentifierStepCount" unit="count" '
            'startDate="2025-01-01 00:00:00 +0000" '
            f'endDate="2025-01-01 00:00:00 +0000" value="{i}"/>'
        )
    parts.append("</HealthData>")
    xml_path = tmp_path / "many.xml"
    xml_path.write_text("".join(parts))

    gen = build_db.iter_health_elements(xml_path)
    for _ in range(consume):
        next(gen)
    gc.collect()
    live = sum(1 for obj in gc.get_objects() if isinstance(obj, ET.Element))
    # Drained: a tiny constant remains. Un-drained: ~`consume` shells survive.
    assert live < 100, f"root accumulated {live} elements — not memory-bounded"

    # Draining the root must not drop any data.
    remaining = sum(1 for _ in gen)
    assert consume + remaining == n


def test_source_is_memory_bounded_by_construction(build_db_source) -> None:
    src = build_db_source
    assert "iterparse" in src
    assert "elem.clear()" in src
    # The root must be drained too, not just each element.
    assert "root.clear()" in src
    # No whole-DOM load.
    assert "ET.parse(" not in src
    assert "fromstring" not in src
    assert ".read()" not in src


def test_source_imports_nothing_from_app(build_db_source) -> None:
    src = build_db_source
    assert "import app" not in src
    assert "from app" not in src
