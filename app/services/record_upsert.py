"""Idempotent `records` upsert service (E5·P2 TASK-001).

Maps each whitelisted `HealthRecord` wire model onto a `records` row and writes it
with `INSERT … ON CONFLICT(uuid) DO NOTHING`, returning an exact `upserted` /
`duplicate` split so `/sync`'s `SyncResponse` makes idempotency observable (DB.md §1
write rule; MODELS "SyncResponse"; epic R3/R4/R5).

Pure `(session, records) -> RecordUpsertResult` — no HTTP, no commit (the route owns
the transaction).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, NamedTuple

from app.api.schemas.sync import HealthRecord
from app.core.healthkit import filter_whitelisted_records
from app.database.models import Records
from app.services._upsert import insert_new_by_uuid


class RecordUpsertResult(NamedTuple):
    """Counts for `SyncResponse.recordsUpserted` / `recordsDuplicate`."""

    upserted: int
    duplicate: int


def _to_row(record: HealthRecord) -> dict[str, Any]:
    """Map a wire `HealthRecord` onto a `records` row (DB.md §1 column semantics).

    Quantity samples carry `value`+`unit`; category samples carry `category`, which
    lands in `value_text` (the column for enum/string categories). Timestamps are
    stored as ISO-8601 TEXT preserving the device offset verbatim.
    """
    return {
        "uuid": record.uuid,
        "type": record.type.value,
        "value": record.value,
        "value_text": record.category,
        "unit": record.unit,
        "start_date": record.start.isoformat(),
        "end_date": record.end.isoformat(),
        "source_name": record.source,
        "origin": "sync",
    }


def upsert_records(session, records: Iterable[HealthRecord]) -> RecordUpsertResult:
    """Filter to whitelisted types, map, and upsert by `uuid` (DO NOTHING)."""
    whitelisted = filter_whitelisted_records(records)
    rows = [_to_row(r) for r in whitelisted]
    _, upserted, duplicate = insert_new_by_uuid(session, Records, rows)
    return RecordUpsertResult(upserted=upserted, duplicate=duplicate)
