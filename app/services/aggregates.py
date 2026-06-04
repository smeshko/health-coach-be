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

from dataclasses import asdict, dataclass
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
# The seven dietary intake columns (consumed side), in DB.md §2 order.
_DIETARY_COLUMNS: tuple[str, ...] = (
    "kcal_in",
    "protein_in_g",
    "carbs_in_g",
    "fat_in_g",
    "fiber_in_g",
    "sodium_in_mg",
    "water_in_l",
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


# ---------------------------------------------------------------------------
# Nutrition-intake (consumed) rollups + adherence seam (TASK-002).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NutritionConsumed:
    """One window's summed dietary intake + per-nutrient logged-day coverage.

    `n_days` is the count of `daily_metrics` rows present; the per-nutrient
    `*_n` counts (`COUNT(col)`, NULL-skipping) are the real adherence coverage — a
    window can have full `n_days` yet a nutrient never logged (E6·P1 stores a
    no-source dietary cell as NULL) — round-1 #1.
    """

    days: int
    kcal_in: float
    protein_in_g: float
    carbs_in_g: float
    fat_in_g: float
    fiber_in_g: float
    sodium_in_mg: float
    water_in_l: float
    n_days: int
    kcal_in_n: int
    protein_in_g_n: int
    carbs_in_g_n: int
    fat_in_g_n: int
    fiber_in_g_n: int
    sodium_in_mg_n: int
    water_in_l_n: int


def nutrition_consumed(session: Session, anchor: date, days: int) -> NutritionConsumed:
    """The windowed consumed-intake rollup: NULL-safe `SUM` of the seven dietary
    columns + each nutrient's logged-day count (`COUNT(col)`) + `n_days` (`COUNT(*)`)."""
    sums = [_sum0(col) for col in _DIETARY_COLUMNS]
    counts = [func.count(getattr(DailyMetrics, col)) for col in _DIETARY_COLUMNS]
    stmt = _window_select(anchor, days, *sums, *counts, func.count())
    row = session.execute(stmt).one()
    sum_vals = row[: len(_DIETARY_COLUMNS)]
    count_vals = row[len(_DIETARY_COLUMNS) : 2 * len(_DIETARY_COLUMNS)]
    n_days = row[-1]
    fields: dict[str, object] = {"days": days, "n_days": int(n_days)}
    for col, total, logged in zip(_DIETARY_COLUMNS, sum_vals, count_vals, strict=True):
        fields[col] = total
        fields[f"{col}_n"] = int(logged)
    return NutritionConsumed(**fields)  # type: ignore[arg-type]


@dataclass(frozen=True)
class NutritionTarget:
    """A caller-injected **PER-DAY** nutrition target, modelled on the documented
    `MacroFocus`/`WeeklyNutrition` contract (MODELS.md) — scalar daily kcal/protein/carbs,
    a fat range, and a hydration range, each optional. **No sodium/fiber target**
    (`MacroFocus` defines neither; they stay consumed-only). E6·P3 computes none of these
    — the per-day target is E7/E8's `MacroFocus`/TDEE, read by the caller from a prior
    `plans`/`suggestions` row and injected (DECISIONS Decision 1)."""

    kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g_low: float | None = None
    fat_g_high: float | None = None
    water_l_low: float | None = None
    water_l_high: float | None = None


@dataclass(frozen=True)
class NutritionAdherence:
    """A window's consumed totals + the consumed-vs-target view (per-day comparison).

    The adherence fields are the documented `WeeklyNutrition.lastWeek` / `vsTarget`
    ones, each `None` (unknown) when the target field is absent/zero or no day was
    logged (round-1 #1) — never a fabricated `0%`. Sodium & fiber are consumed-only.
    """

    consumed: NutritionConsumed
    target: NutritionTarget | None
    avg_kcal: float | None
    avg_protein_g: float | None
    kcal_pct: float | None
    protein_hit_days: int | None
    days_over_target: int | None
    days_under_target: int | None


def _safe_ratio(num: float | None, den: float | None) -> float | None:
    """`num / den`, or `None` when either is absent or the denominator is 0 (no
    divide-by-zero, no `inf`) — an undefined ratio is unknown, not a fabricated number."""
    if num is None or den is None or den == 0:
        return None
    return num / den


def nutrition_adherence(
    session: Session, anchor: date, days: int, *, target: NutritionTarget | None = None
) -> NutritionAdherence:
    """The consumed rollup plus, when a per-day `target` is supplied, the documented
    per-day-comparison adherence fields over the window's **logged** days.

    Each adherence field is `None` (unknown) when: the relevant target field is `None`,
    the target is `0` (divide-by-zero guard), or no day was logged for that nutrient
    (round-1 #1) — so a NULL-only window never reads as `0%`. Day-count fields count
    only logged days, so they are naturally coverage-aware. `target=None` → all `None`.
    """
    consumed = nutrition_consumed(session, anchor, days)
    avg_kcal: float | None = None
    avg_protein_g: float | None = None
    kcal_pct: float | None = None
    protein_hit_days: int | None = None
    days_over_target: int | None = None
    days_under_target: int | None = None

    if target is not None:
        start, end = window_bounds(anchor, days)
        rows = session.execute(
            select(DailyMetrics.kcal_in, DailyMetrics.protein_in_g).where(
                DailyMetrics.date.between(start, end)
            )
        ).all()
        logged_kcal = [k for (k, _p) in rows if k is not None]
        logged_protein = [p for (_k, p) in rows if p is not None]

        if logged_kcal:
            avg_kcal = sum(logged_kcal) / len(logged_kcal)
            kcal_pct = _safe_ratio(avg_kcal, target.kcal)
            if target.kcal not in (None, 0):
                days_over_target = sum(1 for k in logged_kcal if k > target.kcal)
                days_under_target = sum(1 for k in logged_kcal if k < target.kcal)
        if logged_protein:
            avg_protein_g = sum(logged_protein) / len(logged_protein)
            if target.protein_g not in (None, 0):
                protein_hit_days = sum(1 for p in logged_protein if p >= target.protein_g)

    return NutritionAdherence(
        consumed=consumed,
        target=target,
        avg_kcal=avg_kcal,
        avg_protein_g=avg_protein_g,
        kcal_pct=kcal_pct,
        protein_hit_days=protein_hit_days,
        days_over_target=days_over_target,
        days_under_target=days_under_target,
    )


# ---------------------------------------------------------------------------
# Public aggregate shape + accessor (TASK-003).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Aggregates:
    """The single context block E10's `LoadAggregatesNode` and the E11 daily context
    read — both training windows + both nutrition-adherence windows (ARCHITECTURE §5)."""

    anchor: date
    training_7d: TrainingRollup
    training_28d: TrainingRollup
    nutrition_7d: NutritionAdherence
    nutrition_28d: NutritionAdherence

    def to_dict(self) -> dict:
        """A plain JSON-serialisable dict (nested rollups flattened to primitives, anchor
        as ISO string) for `plans.inputs_snapshot` / the LLM context (DB.md §4). Each
        nutrition window's per-nutrient logged-day counts and `n_days` are **always**
        serialised alongside the adherence ratios/flags, so a (possibly low / `None`) ratio
        is never emitted without its coverage (round-2 #1)."""
        data = asdict(self)
        data["anchor"] = self.anchor.isoformat()
        return data


def load_aggregates(
    session: Session,
    anchor: date,
    *,
    nutrition_target_7d: NutritionTarget | None = None,
    nutrition_target_28d: NutritionTarget | None = None,
) -> Aggregates:
    """The one public accessor: build both training rollups (7/28) and both
    nutrition-adherence views (7/28, each against its **own** window's optional per-day
    target — never interchanged), and assemble the `Aggregates`. Takes a `Session` (the
    caller owns the txn — it runs inside a brief node's session); opens no `SessionLocal`,
    writes nothing.
    """
    return Aggregates(
        anchor=anchor,
        training_7d=training_rollup(session, anchor, 7),
        training_28d=training_rollup(session, anchor, 28),
        nutrition_7d=nutrition_adherence(session, anchor, 7, target=nutrition_target_7d),
        nutrition_28d=nutrition_adherence(session, anchor, 28, target=nutrition_target_28d),
    )
