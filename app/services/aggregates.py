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

One read here is **not** over `daily_metrics`: `prior_week_long_run_km` reads the prior
ISO week's longest running session straight off `workouts` (the §9 ramp cap's base). That
read reuses the recompute engine's read-time helpers (Sofia-day attribution + seed/sync
supersession) — the one place this module touches `daily_metrics_engine` — so it stays
byte-for-byte consistent with how the engine attributes a workout to its Sofia day.

The window is a lexical `date BETWEEN start AND end` over the `daily_metrics.date`
TEXT PK — already a `YYYY-MM-DD` Europe/Sofia string (E6·P1 fixed day attribution at
write time), so a contiguous PK range **is** the Sofia-day window with **no** read-time
tz parse (DECISIONS Decision 2). Sums are NULL-safe (`COALESCE(SUM, 0.0)`) — the
inverse of E6·P1's per-day null rule, because a rollup is an additive total
(DECISIONS Decision 3). Pure service — no FastAPI/HTTP, no profile/macro import, no DB
write; it imports only the `daily_metrics_engine` read-time helpers the prior-week
long-run derivation reuses (above).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.core.time import parse_ts, to_sofia
from app.database.models import DailyMetrics, Workouts

# The prior-week long-run derivation reuses the recompute engine's read-time helpers —
# the running-type canonicaliser and the seed/sync supersession pair — so workout
# attribution + seed-vs-sync precedence stay identical to `daily_metrics`' `hard_day`
# read (do NOT re-derive that logic here; weekly-budget-inputs-wiring TASK-001).
from app.services.daily_metrics_engine import (
    _canonical_activity_type,
    _day_is_sync_covered,
    _drop_superseded_seed,
)

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
    n_days: int  # MATERIALIZED rows (non-NULL computed_at) in the window — the coverage denominator


def training_rollup(session: Session, anchor: date, days: int) -> TrainingRollup:
    """The NULL-safe windowed-sum training rollup over `[anchor-(days-1), anchor]`.

    Sums `z1_min`…`z5_min`/`active_energy` (`COALESCE(SUM, 0.0)`), counts hard days
    (`COALESCE(SUM(hard_day), 0)` — `hard_day` is 0/1, so this is the count of hard
    days), and `COUNT(computed_at)` for `n_days` (materialized rows only). One aggregate query; no write.
    """
    stmt = _window_select(
        anchor,
        days,
        *[_sum0(col) for col in _ZONE_ENERGY_COLUMNS],
        func.coalesce(func.sum(DailyMetrics.hard_day), 0),
        # `n_days` counts only MATERIALIZED metric rows (non-NULL `computed_at`, stamped by the
        # metrics engine on every real upsert), not a readiness-only placeholder row that the
        # daily-brief persist can create for an unsynced day (Phase 19.5): counting the
        # placeholder would inflate the coverage denominator fed to the weekly planner.
        func.count(DailyMetrics.computed_at),
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

    `n_days` is the count of MATERIALIZED `daily_metrics` rows (non-NULL `computed_at`); the per-nutrient
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
    columns + each nutrient's logged-day count (`COUNT(col)`) + `n_days` (`COUNT(computed_at)`, materialized rows only)."""
    sums = [_sum0(col) for col in _DIETARY_COLUMNS]
    counts = [func.count(getattr(DailyMetrics, col)) for col in _DIETARY_COLUMNS]
    # `n_days` counts materialized rows only (non-NULL `computed_at`), excluding a readiness-only
    # placeholder (Phase 19.5) so coverage isn't inflated — see `training_rollup`.
    stmt = _window_select(anchor, days, *sums, *counts, func.count(DailyMetrics.computed_at))
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
    """The consumed rollup plus window-mean averages, plus — when a per-day `target` is
    supplied — the documented per-day-comparison adherence fields over the window's
    **logged** days.

    `avg_kcal`/`avg_protein_g` are window means of logged intake (`sum / count`) and are
    **target-independent** (round-1 #1; DECISIONS Decision 1): they populate whenever the
    nutrient is logged, or stay `None` when no day logged it. The comparison fields
    (`kcal_pct`/`protein_hit_days`/`days_over_target`/`days_under_target`) are `None`
    (unknown) when: the relevant target field is `None`, the target is `0`
    (divide-by-zero guard), or no day was logged for that nutrient — so a NULL-only window
    never reads as `0%`. `target=None` → averages from `consumed`, all comparison fields
    `None`.
    """
    consumed = nutrition_consumed(session, anchor, days)
    # Averages are window means of logged intake — NULL-skipping `sum / count` over the
    # `consumed` rollup, target-independent (round-1 #1; DECISIONS Decision 1). They
    # populate whenever the nutrient is logged, so a pre-E13·P2 `lastWeek` carries real
    # averages; a nutrient with no logged day stays `None` (unknown, never fabricated).
    avg_kcal: float | None = (
        consumed.kcal_in / consumed.kcal_in_n if consumed.kcal_in_n > 0 else None
    )
    avg_protein_g: float | None = (
        consumed.protein_in_g / consumed.protein_in_g_n if consumed.protein_in_g_n > 0 else None
    )
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
            kcal_pct = _safe_ratio(avg_kcal, target.kcal)
            if target.kcal not in (None, 0):
                days_over_target = sum(1 for k in logged_kcal if k > target.kcal)
                days_under_target = sum(1 for k in logged_kcal if k < target.kcal)
        if logged_protein:
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
# Prior-week long-run derivation (weekly-budget-inputs-wiring) — the §9 ramp base.
# ---------------------------------------------------------------------------
# `workouts.total_distance` is an unconstrained Float and `total_distance_unit` is
# nullable, so a materialised distance can be garbage — null / 0 / negative / non-finite
# (`inf`/`nan`) / unknown-unit — OR a finite-but-absurd outlier (e.g. a corrupt `1e308`).
# A finite-but-absurd value would overflow `long_run_cap_km`'s `raw * 10` ramp math to
# `inf` (a user-visible broken cap), so this sanity ceiling rejects it before it can reach
# the kernel. The bound is a deliberately wide guard — far above any real single session
# (the longest recorded ultramarathons are only a few hundred km) — so a real long run is
# never excluded.
MAX_PLAUSIBLE_LONG_RUN_KM = 500.0


def _long_run_km(w: Workouts) -> float | None:
    """One running workout's `total_distance` normalized to km, or `None` if non-qualifying.

    `total_distance_unit` `m` → `/1000`, `km` → pass-through; an unknown/empty unit is
    **non-qualifying**. A null / non-finite (`inf`/`nan`) / non-positive (`0`/negative) /
    above-the-sanity-ceiling (> `MAX_PLAUSIBLE_LONG_RUN_KM`) distance is also non-qualifying
    → `None`, so it is **excluded** from the MAX rather than coerced to a `0.0` cap
    (`long_run_cap_km(0.0)` would return a real `0.0`, only `None` is guarded).
    """
    dist = w.total_distance
    if dist is None or not math.isfinite(dist):
        return None
    unit = (w.total_distance_unit or "").strip().lower()
    if unit == "km":
        km = dist
    elif unit == "m":
        km = dist / 1000.0
    else:
        return None  # unknown / empty unit — non-qualifying
    if km <= 0.0 or km > MAX_PLAUSIBLE_LONG_RUN_KM:
        return None
    return km


def prior_week_long_run_km(session: Session, week_monday: date) -> float | None:
    """The longest qualifying running distance (km) over the **prior ISO week**.

    The §9 ≤10%/wk ramp cap's base (`compute_budgets`' `prior_week_long_run_km`). The window
    is the prior ISO week `[week_monday − 7d, week_monday)` in **Sofia days**. Because
    `workouts.start_date` is an offset-bearing ISO instant, candidate running rows are fetched
    over a **two-sided buffered** (±1-day) lexical `start_date` range — wide enough that an
    offset row near *either* Monday boundary is not dropped before attribution — then each row
    is attributed to its Sofia day via `to_sofia(parse_ts(...))` and kept iff that day is in
    `[week_monday − 7d, week_monday)` (mirrors the engine's `hard_day`, never a raw-string
    window).

    Source is **seed + sync** (no `origin` filter): per Sofia day the engine's
    `_drop_superseded_seed`/`_day_is_sync_covered` supersession runs, so a seed row counts on a
    day **not** sync-covered and is dropped on a sync-covered day — a freshly-bootstrapped,
    seed-only prior week still activates the cap. The result is the MAX of the **qualifying**
    km distances (`_long_run_km`); `None` when no running row qualifies (week-one unconstrained
    — MODELS `longRunKm` nullable). Pure read-only — the caller owns the txn; no write.
    """
    lo = week_monday - timedelta(days=7)
    hi = week_monday
    # Two-sided ±1-day buffer: start_date is an offset-bearing instant, so the precise cut is
    # the Sofia-date attribution below, NOT these string bounds (a near-boundary offset row
    # can sit a calendar day either side of the window before attribution).
    lo_fetch = (lo - timedelta(days=1)).isoformat()
    hi_fetch = (hi + timedelta(days=1)).isoformat()
    rows = (
        session.execute(
            select(Workouts)
            .where(Workouts.start_date >= lo_fetch)
            .where(Workouts.start_date < hi_fetch)
        )
        .scalars()
        .all()
    )

    # Attribute each running row to its Sofia day; keep only the in-window days.
    by_day: dict[date, list[Workouts]] = {}
    for w in rows:
        if _canonical_activity_type(w.activity_type) != "running":
            continue
        day = to_sofia(parse_ts(w.start_date)).date()
        if lo <= day < hi:
            by_day.setdefault(day, []).append(w)

    # Per Sofia day, drop seed rows superseded by live sync (Decision 4), then MAX over the
    # qualifying km distances of whatever rows survive.
    best: float | None = None
    for day, day_rows in by_day.items():
        kept = _drop_superseded_seed(day_rows, covered=_day_is_sync_covered(session, day))
        for w in kept:
            km = _long_run_km(w)
            if km is not None and (best is None or km > best):
                best = km
    return best


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
    # The prior ISO week's longest running session (km), the §9 ramp cap's base — injected by
    # the caller (E10's LoadAggregatesNode, via `prior_week_long_run_km`); `None` = no qualifying
    # prior-week running history (week-one unconstrained). Last field (it carries a default).
    prior_week_long_run_km: float | None = None

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
    prior_week_long_run_km: float | None = None,
) -> Aggregates:
    """The one public accessor: build both training rollups (7/28) and both
    nutrition-adherence views (7/28, each against its **own** window's optional per-day
    target — never interchanged), and assemble the `Aggregates`. Takes a `Session` (the
    caller owns the txn — it runs inside a brief node's session); opens no `SessionLocal`,
    writes nothing.

    `prior_week_long_run_km` is **injected** by the caller (E10's `LoadAggregatesNode`
    computes it via the module's `prior_week_long_run_km(session, week_monday)` query and
    passes it here) — it is not derived inside this assembler, mirroring the
    `nutrition_target_7d` injection seam; defaults to `None` (no prior-week running history).
    """
    return Aggregates(
        anchor=anchor,
        training_7d=training_rollup(session, anchor, 7),
        training_28d=training_rollup(session, anchor, 28),
        nutrition_7d=nutrition_adherence(session, anchor, 7, target=nutrition_target_7d),
        nutrition_28d=nutrition_adherence(session, anchor, 28, target=nutrition_target_28d),
        prior_week_long_run_km=prior_week_long_run_km,
    )
