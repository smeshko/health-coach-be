"""Shared `INSERT … ON CONFLICT(uuid) DO NOTHING` partition helper (E5·P2).

`records` and `workouts` both dedupe by the HealthKit `uuid` so re-syncing
overlapping ranges never double-inserts (DB.md §1 write rule; epic R5). A bulk
`executemany` can't report per-row conflicts portably, so the split count is driven
by a one-query pre-select of the already-present `uuid`s; intra-batch duplicates are
folded in too, so the count is exact and a replay flips every row to ``duplicate``.
The `on_conflict_do_nothing` on the insert is belt-and-suspenders against a
concurrent writer — the pre-select drives the numbers.

Pure: it ``flush()``es but never commits (the `/sync` route owns the transaction).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session


def insert_new_by_uuid(
    session: Session, model: Any, rows: Sequence[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int, int]:
    """Insert only the rows whose ``uuid`` is net-new; return (new_rows, upserted, duplicate).

    ``new_rows`` is the deduplicated subset actually inserted (preserving order), so a
    caller that needs the inserted ids (workouts → child statistics) can re-select by
    those ``uuid``s after the flush.
    """
    rows = list(rows)
    if not rows:
        return [], 0, 0

    batch_uuids = [r["uuid"] for r in rows]
    existing: set[str] = set(
        session.execute(select(model.uuid).where(model.uuid.in_(batch_uuids))).scalars()
    )

    new_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        uuid = row["uuid"]
        if uuid in existing or uuid in seen:
            continue
        seen.add(uuid)
        new_rows.append(row)

    if new_rows:
        session.execute(
            sqlite_insert(model).values(new_rows).on_conflict_do_nothing(index_elements=["uuid"])
        )
        session.flush()

    upserted = len(new_rows)
    duplicate = len(rows) - upserted
    return new_rows, upserted, duplicate
