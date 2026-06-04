"""7/28-day rollups over `daily_metrics` (E6·P3) — pure read-side aggregates.

The last E6 phase: a set of **windowed-sum** queries over the already-materialized
`daily_metrics` cache (E6·P1/P2 own the writes), plus the public `Aggregates`
dataclass + accessor that E10's `LoadAggregatesNode` and the E11 daily context
consume. It writes **nothing** (DB.md §7 #3 "rollups = windowed sums"; ARCHITECTURE
§3) — the aggregates land in `plans.inputs_snapshot` only when E10/E11 cache a brief.

Two rollup families over a 7- and a 28-day **Europe/Sofia** window ending on an
anchor date:
- **Training load** — summed zone-minutes Z1–Z5, active energy, hard-day count.
- **Nutrition intake (consumed)** — the seven dietary aggregates, plus a
  target-injection seam (`NutritionTarget`) the caller fills to get adherence.

The window is a lexical `date BETWEEN start AND end` over the `daily_metrics.date`
TEXT PK — already a `YYYY-MM-DD` Europe/Sofia string (E6·P1 fixed day attribution at
write time), so a contiguous PK range **is** the Sofia-day window with **no** read-time
tz parse (DECISIONS Decision 2). Sums are NULL-safe (`COALESCE(SUM, 0.0)`) — the
inverse of E6·P1's per-day null rule, because a rollup is an additive total
(DECISIONS Decision 3). Pure service — no FastAPI/HTTP, no `daily_metrics_engine`,
no profile/macro import, no DB write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.database.models import DailyMetrics

# The summed training columns, in DB.md §2 order.
_ZONE_ENERGY_COLUMNS: tuple[str, ...] = (
    "z1_min",
    "z2_min",
    "z3_min",
    "z4_min",
    "z5_min",
    "active_energy",
)


def window_bounds(anchor: date, days: int) -> tuple[str, str]:
    """Inclusive `[anchor - (days-1), anchor]` Sofia-date bounds as `YYYY-MM-DD` TEXT.

    A 7-day window is the anchor and the 6 days before it (7 calendar Sofia days, both
    ends inclusive — DECISIONS Decision 2), compared against the already-Sofia `date`
    PK via SQL `BETWEEN` (inclusive). Pure `date` arithmetic — no tz parse, no offset.
    """
    end = anchor.isoformat()
    start = (anchor - timedelta(days=days - 1)).isoformat()
    return start, end


def _window_select(anchor: date, days: int, *columns: ColumnElement):
    """A `select(*columns)` restricted to the inclusive Sofia-day window around `anchor`."""
    start, end = window_bounds(anchor, days)
    return select(*columns).where(DailyMetrics.date.between(start, end))


def _sum0(column: str) -> ColumnElement:
    """`COALESCE(SUM(col), 0.0)` — a NULL/missing per-day cell adds 0, empty window → 0."""
    return func.coalesce(func.sum(getattr(DailyMetrics, column)), 0.0)


# ---------------------------------------------------------------------------
# Training-load rollups (TASK-001).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TrainingRollup:
    """One window's training aggregates over `daily_metrics`."""

    days: int
    z1_min: float
    z2_min: float
    z3_min: float
    z4_min: float
    z5_min: float
    active_energy: float
    hard_days: int
    n_days: int  # rows present in the window — the coverage denominator


def training_rollup(session: Session, anchor: date, days: int) -> TrainingRollup:
    """The NULL-safe windowed-sum training rollup over `[anchor-(days-1), anchor]`.

    Sums `z1_min`…`z5_min`/`active_energy` (`COALESCE(SUM, 0.0)`), counts hard days
    (`COALESCE(SUM(hard_day), 0)` — `hard_day` is 0/1, so this is the count of hard
    days), and `COUNT(*)` for `n_days`. One aggregate query; no write.
    """
    stmt = _window_select(
        anchor,
        days,
        *[_sum0(col) for col in _ZONE_ENERGY_COLUMNS],
        func.coalesce(func.sum(DailyMetrics.hard_day), 0),
        func.count(),
    )
    z1, z2, z3, z4, z5, active_energy, hard_days, n_days = session.execute(stmt).one()
    return TrainingRollup(
        days=days,
        z1_min=z1,
        z2_min=z2,
        z3_min=z3,
        z4_min=z4,
        z5_min=z5,
        active_energy=active_energy,
        hard_days=int(hard_days),
        n_days=int(n_days),
    )
