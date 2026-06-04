"""`POST /sync` — authenticated HealthKit ingest endpoint (E5·P2 TASK-003).

The thin HTTP shell: it opens **one transaction**, runs the three pure upsert
services (records / workouts+statistics / activity_summary), commits, and shapes a
`SyncResponse` whose split counts make idempotency observable (DB.md §1; epic R5).

`checkinSaved`/`strengthTestSaved` are deliberately `false` here — persisting the
check-in / strength-test (and the `daily_metrics` recompute fan-out) is **E5·P3**
(epic §3). No readiness, no recompute this phase (MODELS "SyncResponse").
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends

from app.api.auth import require_auth
from app.api.schemas.sync import SyncRequest, SyncResponse
from app.core.time import get_clock, now_sofia
from app.database.engine import SessionLocal
from app.services.activity_upsert import upsert_activity
from app.services.record_upsert import upsert_records
from app.services.workout_upsert import upsert_workouts

router = APIRouter()


@router.post("/sync", response_model=SyncResponse, dependencies=[Depends(require_auth)])
def sync(
    body: SyncRequest,
    clock: Callable[[], datetime] = Depends(get_clock),
) -> SyncResponse:
    """Run the ingest upserts in one transaction and return the `SyncResponse` counts."""
    session = SessionLocal()
    try:
        records = upsert_records(session, body.records)
        workouts = upsert_workouts(session, body.workouts)
        activity_days = upsert_activity(session, body.activity_summary)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return SyncResponse(
        records_upserted=records.upserted,
        records_duplicate=records.duplicate,
        workouts_upserted=workouts.upserted,
        activity_days_upserted=activity_days,
        # E5·P3 persists the check-in / strength test; stubbed false this phase.
        checkin_saved=False,
        strength_test_saved=False,
        server_time=now_sofia(clock),
    )
