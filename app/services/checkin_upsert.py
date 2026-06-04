"""`checkins` upsert-by-date service (E5·P3 TASK-001).

Persists the objective-only daily check-in. Upsert by the `date` TEXT PK
(`ON CONFLICT(date) DO UPDATE`) so a re-posted day corrects its flags in place —
one row per date (DB.md §3; epic R4/R7). `created_at` is set only on first insert
(excluded from the conflict `set_`); `updated_at` advances on every write.

Pure `(session, checkin | None) -> bool` — no HTTP, no commit (the route owns the
transaction). The check-in carries **no** body-weight field (weight is the HealthKit
`body_mass` record → `daily_metrics.body_weight`), so none is mapped here.
"""

from __future__ import annotations

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.api.schemas.sync import DailyCheckin
from app.core.time import now_sofia
from app.database.models import Checkins


def upsert_checkin(session, checkin: DailyCheckin | None) -> bool:
    """Upsert the check-in by `date`; return True iff a row was written."""
    if checkin is None:
        return False

    now = now_sofia().isoformat()
    values = {
        "date": str(checkin.date),
        "gi_symptoms": int(checkin.gi_symptoms),
        "illness": int(checkin.illness),
        "knee_pain": checkin.knee_pain,
        "created_at": now,
        "updated_at": now,
    }
    stmt = sqlite_insert(Checkins).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["date"],
        set_={
            "gi_symptoms": values["gi_symptoms"],
            "illness": values["illness"],
            "knee_pain": values["knee_pain"],
            "updated_at": now_sofia().isoformat(),  # created_at preserved (not in set_)
        },
    )
    session.execute(stmt)
    session.flush()
    return True
