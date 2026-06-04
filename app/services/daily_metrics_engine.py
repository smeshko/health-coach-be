"""`daily_metrics` recompute engine (E6·P1) — the deterministic per-day half.

This is the **engine** behind the E5·P3 seam: `DailyMetricsEngine.__call__(dates)`
rebuilds each affected Europe/Sofia day's `daily_metrics` row from the committed
`records`/`workouts` rows (sleep / HRV / RHR / zone-minutes / steps / active energy /
the seven nutrition aggregates / latest body weight / `hard_day`) and **idempotently
upserts** it with a fresh `computed_at`. It is wired into `/sync` by swapping the
E5·P3 recompute *provider* — no route logic changes.

Two whole families of columns are deliberately left untouched here: the 30-day
rolling baselines `hrv_30d_mean`/`hrv_30d_sd`/`rhr_30d_mean` (E6·P2) and
`readiness_score`/`band` (E8/E11). The `ON CONFLICT(date) DO UPDATE` `set_`
**excludes** those five so a per-day re-run never clobbers a value a later phase
wrote (DB.md §2 note; epic §3/§7).

Recompute-from-source (DECISIONS.md Decision 1): a day's metrics are a pure function
of that day's stored rows, so a re-run is idempotent and a late/duplicate sync
self-heals. Pure service — no FastAPI/HTTP imports (mirrors E5·P2/E5·P3).

The per-metric helpers (`sleep_h`, `hrv_sdnn`, …) are filled by TASK-002/003; this
module lands the engine shape + the idempotent upsert + the provider swap.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.core.profile import Profile, load_profile
from app.core.time import now_sofia
from app.database.engine import SessionLocal
from app.database.models import DailyMetrics
from app.services.recompute import RecomputeDailyMetrics

# The seven nutrition-intake columns, in DB.md §2 order (filled by TASK-003).
NUTRITION_COLUMNS: tuple[str, ...] = (
    "kcal_in",
    "protein_in_g",
    "carbs_in_g",
    "fat_in_g",
    "fiber_in_g",
    "sodium_in_mg",
    "water_in_l",
)
# The five HR zone-minute columns (filled by TASK-002).
ZONE_COLUMNS: tuple[str, ...] = ("z1_min", "z2_min", "z3_min", "z4_min", "z5_min")

# Columns a P1 recompute MUST NOT touch: the 30-day baselines (E6·P2) and the
# readiness verdict (E8/E11). They are never put in the upsert `values`, so they
# stay null on a first insert and survive every re-run (the `set_` is built from
# the computed `values`, so it can never reference these). Named here purely as
# the documented contract / a place a boundary test can assert against.
PRESERVED_COLUMNS: tuple[str, ...] = (
    "hrv_30d_mean",
    "hrv_30d_sd",
    "rhr_30d_mean",
    "readiness_score",
    "band",
)


# ---------------------------------------------------------------------------
# Per-metric helpers — stubbed here (return the no-data shape); TASK-002/003 fill
# the bodies. Keeping the call signatures stable means those tasks only edit the
# helper bodies, not `recompute_day`'s assembly.
# ---------------------------------------------------------------------------
def sleep_h(session: Session, day: date) -> float | None:
    """Last night's asleep hours, anchored to the wake/end Sofia day (TASK-002)."""
    return None


def hrv_sdnn(session: Session, day: date) -> float | None:
    """This-morning HRV SDNN (TASK-002)."""
    return None


def rhr(session: Session, day: date) -> float | None:
    """This-morning resting HR (TASK-002)."""
    return None


def steps(session: Session, day: date) -> int | None:
    """Source-deduped sum of the day's `step_count` records (TASK-002)."""
    return None


def active_energy(session: Session, day: date) -> float | None:
    """Source-deduped sum of the day's `active_energy_burned` records (TASK-002)."""
    return None


def zone_minutes(session: Session, day: date, *, profile: Profile) -> dict[str, float | None]:
    """HR zone-minutes bucketed against `profile.zone_bounds()` (TASK-002)."""
    return {col: None for col in ZONE_COLUMNS}


def nutrition_intake(session: Session, day: date) -> dict[str, float | None]:
    """The seven nutrition-intake aggregates from the dominant app (TASK-003)."""
    return {col: None for col in NUTRITION_COLUMNS}


def body_weight(session: Session, day: date) -> float | None:
    """Latest `body_mass` of the day by actual instant (TASK-003)."""
    return None


def hard_day(session: Session, day: date) -> int:
    """Deterministic 0/1 hard-session flag from the day's `workouts` (TASK-003)."""
    return 0


def expand_affected_dates(session: Session, dates: set[date]) -> set[date]:
    """Expand the handed dates to every Sofia day an overlapping interval reaches.

    E5·P3's `affected_dates` is **start-date** based, so a cross-midnight interval
    record (an HR sample / a sleep block) can touch a Sofia day it did not fan out.
    The engine owns its work-set, so it widens `dates` here before recomputing
    (round-2 #1). TASK-002 adds the interval reads; until then this is identity.
    """
    return set(dates)


# ---------------------------------------------------------------------------
# Per-day assembly + idempotent upsert.
# ---------------------------------------------------------------------------
def _compute_day_values(session: Session, day: date, *, profile: Profile) -> dict[str, object]:
    """Assemble the P1 column values for one Sofia `day` from its source rows.

    Returns only the columns this phase computes (every `daily_metrics` write
    column **except** the five `PRESERVED_COLUMNS` and `date`/`computed_at`, which
    `recompute_day` adds). The per-metric helpers own each value.
    """
    values: dict[str, object] = {
        "sleep_h": sleep_h(session, day),
        "hrv_sdnn": hrv_sdnn(session, day),
        "rhr": rhr(session, day),
        "steps": steps(session, day),
        "active_energy": active_energy(session, day),
        "body_weight": body_weight(session, day),
        "hard_day": hard_day(session, day),
    }
    values.update(zone_minutes(session, day, profile=profile))
    values.update(nutrition_intake(session, day))
    return values


def recompute_day(session: Session, day: date, *, profile: Profile) -> None:
    """Rebuild one Sofia day's `daily_metrics` row and idempotently upsert it.

    The row is a pure function of `day`'s stored rows (recompute-from-source), so a
    re-run rewrites the same computed columns with a fresh `computed_at`. The
    `ON CONFLICT(date) DO UPDATE` `set_` rewrites every computed column plus
    `computed_at` and **excludes** the five `PRESERVED_COLUMNS` (built from
    `values`, which never contains them). No commit — the engine entry point owns
    the transaction.
    """
    values = _compute_day_values(session, day, profile=profile)
    values["date"] = day.isoformat()
    values["computed_at"] = now_sofia().isoformat()

    stmt = insert(DailyMetrics).values(**values)
    update_set = {col: stmt.excluded[col] for col in values if col != "date"}
    stmt = stmt.on_conflict_do_update(index_elements=["date"], set_=update_set)
    session.execute(stmt)


class DailyMetricsEngine:
    """Concrete `RecomputeDailyMetrics` (E5·P3 protocol) — the real `/sync` engine.

    Opens its **own** `SessionLocal()` and commits there: E5·P3 fires recompute
    **after** `/sync`'s commit, so an engine error can't roll back a good ingest
    (the failure instead surfaces as a 5xx; the day re-derives on the next sync —
    round-2 #4). An empty `dates` set returns **before** any DB/profile I/O so an
    empty affected set cannot fail on a DB/settings or `profile.yaml` problem
    (round-1 #1).
    """

    def __call__(self, dates: set[date]) -> None:
        if not dates:
            return
        session = SessionLocal()
        try:
            profile = load_profile()
            for day in sorted(expand_affected_dates(session, dates)):
                recompute_day(session, day, profile=profile)
            session.commit()
        finally:
            session.close()


def get_engine_recompute() -> RecomputeDailyMetrics:
    """Provider that replaces E5·P3's `noop_recompute` default with the real engine."""
    return DailyMetricsEngine()
