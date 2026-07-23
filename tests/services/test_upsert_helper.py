"""Regression tests for the shared uuid-partition helper (app/services/_upsert.py).

The first-ever iPhone sync shipped >32k records in one request and crashed the
live `/sync` with `sqlite3.OperationalError: too many SQL variables` — both the
per-uuid pre-select (`IN (?, ?, …)`) and the single multi-VALUES insert bound
more variables than SQLITE_MAX_VARIABLE_NUMBER allows. These tests run a batch
larger than the modern 32,766 cap through the real migrated schema, so a
reintroduced unchunked query fails loudly.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.database.models import Records
from app.services._upsert import UUID_CHUNK, insert_new_by_uuid, iter_uuid_chunks

# Above SQLITE_MAX_VARIABLE_NUMBER (32,766 since SQLite 3.32) — the observed
# first-sync failure size, kept minimal so the suite stays fast.
OVER_LIMIT = 33_000


def _row(i: int) -> dict:
    return {
        "uuid": f"uuid-{i:07d}",
        "type": "heart_rate",
        "unit": "count/min",
        "value": 60.0,
        "start_date": "2026-06-01T08:00:00+03:00",
        "end_date": "2026-06-01T08:00:30+03:00",
        "origin": "sync",
    }


def _count(session) -> int:
    return session.execute(select(func.count()).select_from(Records)).scalar_one()


def test_batch_larger_than_sqlite_variable_cap(session) -> None:
    rows = [_row(i) for i in range(OVER_LIMIT)]
    new_rows, upserted, duplicate = insert_new_by_uuid(session, Records, rows)
    assert (len(new_rows), upserted, duplicate) == (OVER_LIMIT, OVER_LIMIT, 0)
    assert _count(session) == OVER_LIMIT

    # Replay of the same oversized batch: the pre-select now scans >32k existing
    # uuids (chunked IN clauses) and every row must flip to duplicate.
    new_rows, upserted, duplicate = insert_new_by_uuid(session, Records, rows)
    assert (len(new_rows), upserted, duplicate) == (0, 0, OVER_LIMIT)
    assert _count(session) == OVER_LIMIT


def test_iter_uuid_chunks_partitions_exactly() -> None:
    uuids = [str(i) for i in range(2 * UUID_CHUNK + 1)]
    chunks = list(iter_uuid_chunks(uuids))
    assert [len(c) for c in chunks] == [UUID_CHUNK, UUID_CHUNK, 1]
    assert [u for chunk in chunks for u in chunk] == uuids  # order + completeness
    assert all(len(c) <= UUID_CHUNK for c in chunks)
