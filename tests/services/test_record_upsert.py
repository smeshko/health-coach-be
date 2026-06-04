"""E5·P2 TASK-001: idempotent records upsert service."""

from __future__ import annotations

from sqlalchemy import func, select

from app.api.schemas.sync import HealthRecord
from app.database.models import Records
from app.services.record_upsert import RecordUpsertResult, upsert_records


def _record(uuid: str, type_: str = "heart_rate", **over) -> HealthRecord:
    base = {
        "uuid": uuid,
        "type": type_,
        "start": "2026-06-01T08:00:00+03:00",
        "end": "2026-06-01T08:00:30+03:00",
        "value": 57.0,
        "unit": "count/min",
    }
    base.update(over)
    return HealthRecord.model_validate(base)


def _count(session) -> int:
    return session.execute(select(func.count()).select_from(Records)).scalar_one()


def test_first_upsert_counts_and_rows(session) -> None:
    recs = [_record(f"u{i}") for i in range(3)]
    result = upsert_records(session, recs)
    assert isinstance(result, RecordUpsertResult)
    assert result.upserted == 3
    assert result.duplicate == 0
    assert _count(session) == 3


def test_replay_is_idempotent(session) -> None:
    recs = [_record(f"u{i}") for i in range(3)]
    upsert_records(session, recs)
    before = _count(session)
    result = upsert_records(session, recs)
    assert result.upserted == 0
    assert result.duplicate == 3
    assert _count(session) == before  # unchanged


def test_overlapping_batches_insert_each_uuid_once(session) -> None:
    first = upsert_records(session, [_record("a"), _record("b")])
    assert first.upserted == 2
    # Second batch overlaps on "b", adds "c".
    second = upsert_records(session, [_record("b"), _record("c")])
    assert second.upserted == 1
    assert second.duplicate == 1
    assert _count(session) == 3  # a, b, c — b not double-inserted


def test_non_whitelisted_type_dropped(session) -> None:
    # respiratory_rate is a valid RecordType but absent from the storage whitelist.
    recs = [_record("keep", "body_mass", value=78.0, unit="kg"), _record("drop", "respiratory_rate")]
    result = upsert_records(session, recs)
    assert result.upserted == 1  # only the whitelisted body_mass row
    uuids = set(session.execute(select(Records.uuid)).scalars())
    assert "keep" in uuids
    assert "drop" not in uuids


def test_quantity_sample_mapping(session) -> None:
    upsert_records(session, [_record("q", "heart_rate", value=57.0, unit="count/min")])
    row = session.execute(select(Records).where(Records.uuid == "q")).scalar_one()
    assert row.value == 57.0
    assert row.unit == "count/min"
    assert row.value_text is None


def test_category_sample_mapping(session) -> None:
    rec = _record("c", "sleep_analysis", value=None, unit=None, category="asleepDeep")
    upsert_records(session, [rec])
    row = session.execute(select(Records).where(Records.uuid == "c")).scalar_one()
    assert row.value_text == "asleepDeep"
    assert row.value is None


def test_origin_is_sync_on_every_row(session) -> None:
    upsert_records(session, [_record("u1"), _record("u2")])
    origins = set(session.execute(select(Records.origin).distinct()).scalars())
    assert origins == {"sync"}


def test_column_mapping_start_end_source(session) -> None:
    rec = _record("m", source="Apple Watch")
    upsert_records(session, [rec])
    row = session.execute(select(Records).where(Records.uuid == "m")).scalar_one()
    assert row.type == "heart_rate"
    assert row.start_date == "2026-06-01T08:00:00+03:00"
    assert row.end_date == "2026-06-01T08:00:30+03:00"
    assert row.source_name == "Apple Watch"
