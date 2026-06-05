"""Deterministic weekly run/strength targets (E10·P2; MODELS ``WeeklyTargets``).

The one genuinely-new pure kernel this phase adds (DECISIONS D2): E8 ships budgets
(``compute_budgets``) and nutrition (``compute_weekly_nutrition``) but **no**
weekly-targets module, and ARCHITECTURE §5's ``ComputeTargetsNode`` "derive
totalRunKm/easyRatio/etc. from the picks (arithmetic)" has no prior kernel. So
``compute_targets(sessions, profile)`` is thin arithmetic over the **already-expanded**
``PlannedSession[]`` (E7·P2) — sums/ratios/counts + the cadence cue read straight off
``profile.thresholds.cadence_current_spm``.

It re-implements **no** card/zone/budget/macro formula: ``is_hard_day``/``intensity``/
``flags`` are already filled by ``expand_plan`` from ``CARD_META`` (E7·P1/P2); this
module only **reads** them. The only arithmetic it owns is:

- ``total_run_km`` — Σ run-card minutes (the dose-band midpoint) ÷ the easy pace model
  (min/km). A pure pace constant keyed off the profile's easy effort, never a number
  the LLM emits (MODELS ``totalRunKm`` "sum of run-card doses (× pace model)").
- ``easy_run_ratio`` — easy-run minutes ÷ total run minutes (the §3 ~0.8 polarization
  target the daily loop measures against).
- ``strength_sessions`` — count of strength cards (``Flag.strength``).
- ``hard_days`` — count of ``is_hard_day`` sessions.
- ``cadence_spm`` — ``profile.thresholds.cadence_current_spm`` (this month's cue — the
  E8·P5 ramp moves it, never this kernel).

Pure module: imports only ``app/core`` value types + the E7·P2 ``PlannedSession``; no
DB/HTTP/LLM import, no ``load_profile`` call, no card-field re-derivation.
"""

from __future__ import annotations

from app.api.schemas.base import CamelModel
from app.core.cards import Flag, get_card
from app.core.enums import Intensity, WorkoutCard
from app.core.profile import Profile
from app.services.derive.plan import PlannedSession

# The run cards whose dose (minutes) contributes to ``totalRunKm`` — the running pool
# (CARDS.md §1A). Read off ``CARD_META`` membership (``Flag.impact`` + a run zone) is
# noisy (jump_rope/strides carry impact but are not steady runs), so the run pool is a
# pinned, greppable set — the same cards the §1A "Running" block lists.
_RUN_CARDS: frozenset[WorkoutCard] = frozenset(
    {
        WorkoutCard.easy_run,
        WorkoutCard.long_run,
        WorkoutCard.progression_run,
        WorkoutCard.threshold,
        WorkoutCard.vo2,
    }
)

# The easy-pace model (minutes per km) — the single pace constant converting run-card
# minutes into distance for ``totalRunKm``. A run's distance ≈ its minutes ÷ this pace.
# Pinned here (one source) and reproduced by the MODELS ``WeeklyTargets`` worked-example
# test; a faster threshold/VO₂ pace is a future refinement, not invented now (RESEARCH
# Uncertainty — "no new constant invented here" beyond this single, documented model).
EASY_PACE_MIN_PER_KM: float = 6.0


class WeeklyTargets(CamelModel):
    """Week-level numeric targets, all code-derived (MODELS ``WeeklyTargets``).

    Snake_case fields serialise to the camelCase wire names
    (``totalRunKm``/``easyRunRatio``/``strengthSessions``/``hardDays``/``cadenceSpm``).
    Numbers only — no prose, no card-derived field (those live on ``PlannedSession``).
    ``total_run_km`` is ``float | None`` (MODELS nullable: ``None`` when no run card is
    planned — there is no run distance to sum).
    """

    total_run_km: float | None
    easy_run_ratio: float
    strength_sessions: int
    hard_days: int
    cadence_spm: int


def _dose_midpoint_min(session: PlannedSession) -> float | None:
    """The dose-band midpoint in minutes, or ``None`` when the dose is unset.

    A run pick may omit its dose (``suggested_day``-only sequencing); such a session
    contributes no minutes (it is left to the daily expansion — E11). With only a low
    bound set (open-ended bands like ``long_run``) the low bound is used as-is.
    """
    low = session.duration_min_low
    high = session.duration_min_high
    if low is None and high is None:
        return None
    if low is None:
        return float(high)  # type: ignore[arg-type]
    if high is None:
        return float(low)
    return (low + high) / 2


def compute_targets(sessions: list[PlannedSession], profile: Profile) -> WeeklyTargets:
    """Derive the weekly ``WeeklyTargets`` from the already-expanded sessions (§5).

    Pure arithmetic over the merged ``core + extras`` ``PlannedSession[]`` (the caller
    passes both lists concatenated): run minutes → km via the easy pace model, the
    easy-run share of run minutes, the strength-card count, the ``is_hard_day`` count,
    and the cadence cue read off ``profile.thresholds.cadence_current_spm``. Reads
    ``is_hard_day``/``intensity``/``flags`` already filled by ``expand_plan`` — it
    re-derives **no** card field. ``total_run_km`` is ``None`` when no run card carries
    a dose (no distance to sum); ``easy_run_ratio`` is ``0.0`` when no run minutes exist.
    """
    run_minutes_total = 0.0
    easy_run_minutes = 0.0
    has_run_dose = False
    for s in sessions:
        if s.card not in _RUN_CARDS:
            continue
        minutes = _dose_midpoint_min(s)
        if minutes is None:
            continue
        has_run_dose = True
        run_minutes_total += minutes
        if s.intensity is Intensity.easy:
            easy_run_minutes += minutes

    total_run_km = (
        round(run_minutes_total / EASY_PACE_MIN_PER_KM, 1) if has_run_dose else None
    )
    easy_run_ratio = (
        round(easy_run_minutes / run_minutes_total, 2) if run_minutes_total > 0 else 0.0
    )
    strength_sessions = sum(
        1 for s in sessions if Flag.strength in get_card(s.card).flags
    )

    return WeeklyTargets(
        total_run_km=total_run_km,
        easy_run_ratio=easy_run_ratio,
        strength_sessions=strength_sessions,
        hard_days=sum(1 for s in sessions if s.is_hard_day),
        cadence_spm=profile.thresholds.cadence_current_spm,
    )
