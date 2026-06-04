"""`strength_tests` upsert-by-derived-iso_week service (E5·P3 TASK-002).

The client sends only a `date`; the **server derives the ISO week** (Europe/Sofia)
via the E2·P1 `iso_week(...)` helper and upserts on the `UNIQUE(iso_week)` column —
one test per week (`ON CONFLICT(iso_week) DO UPDATE`); a re-test for the week
overwrites the one row (DB.md §3; epic R4; MODELS StrengthTest; ARCHITECTURE §4).

Pure `(session, test | None) -> bool` — no HTTP, no commit (the route owns the
transaction). `created_at` is set only on first insert (excluded from the conflict
`set_`).
"""

from __future__ import annotations

from datetime import datetime, time

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.api.schemas.sync import StrengthTest
from app.core.time import SOFIA, iso_week, now_sofia
from app.database.models import StrengthTests


def _derive_iso_week(test: StrengthTest) -> str:
    """Derive the Europe/Sofia ISO week (`YYYY-Www`) from the test's calendar date.

    The E2·P1 `iso_week` helper rejects naive datetimes, so the bare date is combined
    to **local midnight in Europe/Sofia** — combining at local midnight keeps the
    derived week equal to the calendar date's own ISO week (a UTC combine near the day
    boundary could shift the Sofia day and thus the week).
    """
    aware = datetime.combine(test.date, time.min, tzinfo=SOFIA)
    return iso_week(aware)


def upsert_strength_test(session, test: StrengthTest | None) -> bool:
    """Upsert the strength test by its server-derived `iso_week`; True iff written."""
    if test is None:
        return False

    values = {
        "date": str(test.date),
        "iso_week": _derive_iso_week(test),
        "max_pushups": test.max_pushups,
        "max_pullups": test.max_pullups,
        "created_at": now_sofia().isoformat(),
    }
    stmt = sqlite_insert(StrengthTests).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["iso_week"],
        set_={
            "date": values["date"],
            "max_pushups": values["max_pushups"],
            "max_pullups": values["max_pullups"],
            # created_at preserved (not in set_).
        },
    )
    session.execute(stmt)
    session.flush()
    return True
