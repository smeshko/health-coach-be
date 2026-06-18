"""`POST /sync` — authenticated HealthKit ingest endpoint (E5·P2 + E5·P3).

The thin HTTP shell: it opens **one transaction**, runs the five pure upsert
services (records / workouts+statistics / activity_summary / check-in /
strength-test), commits, then fires the `daily_metrics` recompute seam **after**
commit for exactly the affected Europe/Sofia dates, and shapes a `SyncResponse`
whose split counts make idempotency observable (DB.md §1, §6; epic R5).

The recompute **engine** is E6 — this route injects a `RecomputeDailyMetrics`
provider defaulting to `noop_recompute`, so E6 swaps in the real engine by
overriding the provider with no route change. `/sync` does **no** readiness
computation (MODELS "SyncResponse").
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends

from app.api.auth import require_auth
from app.api.schemas.sync import SyncRequest, SyncResponse
from app.core.time import get_clock, now_sofia
from app.database.engine import SessionLocal
from app.services.activity_upsert import upsert_activity
from app.services.checkin_upsert import upsert_checkin
from app.services.daily_metrics_engine import get_engine_recompute
from app.services.recompute import RecomputeDailyMetrics, affected_dates
from app.services.record_upsert import upsert_records
from app.services.strength_test_upsert import upsert_strength_test
from app.services.workout_upsert import upsert_workouts

logger = logging.getLogger(__name__)

router = APIRouter()


def get_recompute() -> RecomputeDailyMetrics:
    """Provider for the `daily_metrics` recompute callable.

    Returns the real E6 engine (E5·P3 shipped a `noop_recompute` default behind this
    seam precisely so E6 swaps it in with no route change). Tests still override this
    provider with a spy. If the engine raises (post-commit), the route **catches** it,
    logs it, and returns `200` with `recomputeOk=False` — the already-committed ingest
    is durable and the affected day's `daily_metrics` is re-derived on the next sync or
    brief (data-safety hardening: a failed recompute must not report durable ingest as a
    failure, nor let one poison day permanently block the client's brief).
    """
    return get_engine_recompute()


@router.post("/sync", response_model=SyncResponse, dependencies=[Depends(require_auth)])
def sync(
    body: SyncRequest,
    clock: Callable[[], datetime] = Depends(get_clock),
    recompute: RecomputeDailyMetrics = Depends(get_recompute),
) -> SyncResponse:
    """Run the ingest upserts in one transaction, recompute affected days, respond."""
    session = SessionLocal()
    try:
        records = upsert_records(session, body.records)
        workouts = upsert_workouts(session, body.workouts)
        activity_days = upsert_activity(session, body.activity_summary)
        checkin_saved = upsert_checkin(session, body.checkin)
        strength_test_saved = upsert_strength_test(session, body.strength_test)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # Fire the recompute seam AFTER commit (so the engine reads committed rows and a
    # recompute error can't roll back a good ingest) — unconditionally, even on an
    # empty affected set (noop and a real E6 engine both treat set() as "nothing").
    # A recompute failure does NOT fail the request: the ingest is already durable and
    # idempotent, so we ack 200 with recomputeOk=False and let the next sync/brief
    # re-derive the affected day, rather than 5xx-ing durable data into a retry loop.
    recompute_ok = True
    try:
        recompute(affected_dates(body))
    except Exception:  # noqa: BLE001 — recompute is best-effort; ingest is already committed
        recompute_ok = False
        logger.exception("daily_metrics recompute failed after a committed /sync ingest")

    return SyncResponse(
        records_upserted=records.upserted,
        records_duplicate=records.duplicate,
        workouts_upserted=workouts.upserted,
        activity_days_upserted=activity_days,
        checkin_saved=checkin_saved,
        strength_test_saved=strength_test_saved,
        server_time=now_sofia(clock),
        recompute_ok=recompute_ok,
    )
