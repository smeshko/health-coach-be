"""Deterministic, objective-only weekly budgets (E8·P4; CONSTITUTION §5.1/§9/§8.4).

A **pure** module: turn a week's resolved aggregate inputs (7-day sleep avg; the 7-day
HRV avg vs the rolling ``hrv_30d_mean``/``hrv_30d_sd`` baseline; the 7-day RHR avg vs the
rolling ``rhr_30d_mean``; a GI-symptoms-this-week flag; the prior week's long-run km; the
0-based ISO week-in-block index; and the §8.4 caller-supplied extra under-recovery signal
count) into the §5.1 weekly-budget skeleton — ``hardDays`` (2, or **3** only under the
sleep ≥6.5 h + HRV ≥ baseline + no-GI gate, **1** on a deload), ``strengthSessions``
(**constant 2**, the protected muscle goal — never reduced on any deload), ``longRunKm``
(the prior week's long run capped at **≤110 %**, the §9 ≤10%/wk ramp — down-ramped ~40 % on
a deload), and ``deload`` (true **every 4th week** or auto-triggered by the §8.4 "any two"
guardrail / a GI flare). There is **no** subjective check-in input, **no** LLM call, and
**no** DB read/write (the query that loads the rollups / the prior-week long-run km off
``daily_metrics``/``workouts`` and the merge into ``plans.payload`` are E10). It imports
only stdlib + the shared ``app.core.constraints.WeeklyBudgets`` value type the E7·P3
weekly validator reads — no FastAPI/HTTP/DB session/LLM.

Baselines are the **rolling** ``daily_metrics`` values (E6·P2), **never** the monthly
zone-derivation anchors — "one rolling baseline, not two competing ones" (DB.md §5 ¹). A
``None`` gate input **fails the 3-day upgrade closed** (the upgrade is opt-in evidence of
good recovery; absence ≠ permission); a ``None`` deload signal is **not counted** as fired;
``None`` prior long-run history → ``None`` (MODELS ``longRunKm`` nullable). The function is
**total** — no exception on incomplete inputs (epic R6).

Budget magnitudes are **named constants transcribed verbatim from §5.1/§9/§8.4** (single
source) so a mis-transcription is caught by a worked-point test.
"""

from __future__ import annotations

import math

from app.core.constraints import WeeklyBudgets

__all__ = [
    "BASE_HARD_DAYS",
    "MAX_HARD_DAYS",
    "DELOAD_HARD_DAYS",
    "STRENGTH_SESSIONS",
    "HARD3_SLEEP_MIN_H",
    "WeeklyBudgets",
    "hard_day_budget",
    "strength_sessions",
]

# --- Pinned hard-day budget magnitudes, transcribed verbatim from §5.1 ---
# §5.1 "2 hard/quality days to start"
BASE_HARD_DAYS = 2
# §5.1 "allow 3 only when 7-day avg sleep ≥6.5 h and HRV at/above baseline and no GI"
MAX_HARD_DAYS = 3
# §5.1 deload "drop to 1 hard day"
DELOAD_HARD_DAYS = 1
# §5.1 strength "2 sessions/week … protected as core"; MODELS strengthSessions "protected
# at 2" — a single constant, never reduced on any deload (review round-1 #1).
STRENGTH_SESSIONS = 2
# §5.1 the 3-hard-day gate sleep threshold — "7-day avg sleep ≥6.5 h" (inclusive).
HARD3_SLEEP_MIN_H = 6.5

# Rolling baselines are floats, so an exact §5.1 INCLUSIVE boundary (sleep == 6.5 h, the
# 7-day HRV avg == its rolling baseline) can land a hair off after binary float arithmetic.
# `_at_or_above` keeps an exact boundary on the qualifying side (the §5.1 "≥" / "at/above"
# is inclusive), matching the readiness.py / safety_gate.py tolerant-comparison pattern.
_BOUNDARY_REL_TOL = 1e-9
_BOUNDARY_ABS_TOL = 1e-12


def _at_boundary(value: float, boundary: float) -> bool:
    """``value`` equals ``boundary`` within float noise."""
    return math.isclose(value, boundary, rel_tol=_BOUNDARY_REL_TOL, abs_tol=_BOUNDARY_ABS_TOL)


def _at_or_above(value: float, boundary: float) -> bool:
    """``value >= boundary``, including an exact boundary masked by float noise."""
    return value >= boundary or _at_boundary(value, boundary)


def hard_day_budget(
    *,
    sleep_avg_7d_h: float | None,
    hrv_avg_7d: float | None,
    hrv_30d_mean: float | None,
    gi_symptoms_this_week: bool,
    deload: bool,
) -> int:
    """The §5.1 hard-day ceiling — 2 by default, 3 under the gate, 1 on a deload.

    **On a deload** → ``DELOAD_HARD_DAYS`` (1): a deload "drop[s] to 1 hard day" (§5.1) and
    **overrides** the 3-day upgrade (Decision 3), so it is checked first. Otherwise the
    **3-hard-day gate** returns ``MAX_HARD_DAYS`` (3) **iff ALL THREE** hold — 7-day avg
    sleep ≥ ``HARD3_SLEEP_MIN_H`` (6.5, inclusive) **AND** the 7-day HRV avg ≥ the rolling
    ``hrv_30d_mean`` baseline (at/above, inclusive) **AND** no GI symptoms — else
    ``BASE_HARD_DAYS`` (2). A **missing** gate input (any of sleep / HRV / baseline is
    ``None``) **fails the upgrade closed** (Decision 5): the upgrade is opt-in evidence of
    good recovery, absence ≠ permission, so the default 2 stands. The HRV comparison reads
    the **rolling** ``hrv_30d_mean`` input, never the monthly ``profile.yaml`` anchor
    (DB.md §5 ¹).
    """
    if deload:
        return DELOAD_HARD_DAYS
    sleep_ok = sleep_avg_7d_h is not None and _at_or_above(sleep_avg_7d_h, HARD3_SLEEP_MIN_H)
    hrv_ok = (
        hrv_avg_7d is not None
        and hrv_30d_mean is not None
        and _at_or_above(hrv_avg_7d, hrv_30d_mean)
    )
    if sleep_ok and hrv_ok and not gi_symptoms_this_week:
        return MAX_HARD_DAYS
    return BASE_HARD_DAYS


def strength_sessions() -> int:
    """Always ``STRENGTH_SESSIONS`` (2) — the protected muscle goal (§5.1).

    Parameterless: **no** deload (cadence, under-recovery, or GI flare) reduces it (review
    round-1 #1; Decision 4). MODELS ``strengthSessions`` is "protected at 2" with no sub-2
    variant; a deload cuts **hard days** (§5.1 "drop to 1 hard day") and **run volume**
    (~40 %), and the §5.3/§8.1 GI deload caps **hard days** at 1 — strength is **not** a
    hard day, so it stays 2. Kept as a tiny named function for a single source of the
    constant + call-site parity with the other helpers.
    """
    return STRENGTH_SESSIONS
