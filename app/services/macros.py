"""Deterministic nutrition / macro engine (E8·P3; CONSTITUTION §7).

A **pure** module on the code side of the code/LLM boundary (LLM.md §1.1): the LLM
picks **one** nutrition input — ``dayType`` — and this code computes **every** gram
from it. There is **no** LLM call, **no** HTTP/FastAPI import, and **no** DB
session/read/write: the functions take an already-loaded ``Nutrition``/``Athlete``
(E3·P1's typed sub-models) + a live weight ``W`` (kg, the materialized
``body_weight`` from E6·P1; passed in as a ``float``, never read off a row here) +
a chosen ``DayType``, and return value objects. The query that loads the weight and
the brief assembly/persistence are E10/E11.

Every formula is transcribed verbatim from CONSTITUTION §7 with a citation comment:
§7.1 Mifflin-St Jeor BMR (``10·W + 6.25·height_cm − 5·age + 5``, male) → ``TDEE =
BMR × activity_factor`` → ``Target_avg = TDEE × (1 − deficit_pct)`` with the deficit
**re-clamped to ≤0.20**; §7.2 constant protein (``protein_g_per_kg`` g/kg, re-capped
at ≤2.0) + fat range; §7.3 day-type carb cycling + the TDEE × day-type calories; §7.4
hydration baseline + additive sweat.

The deficit ≤0.20 and protein ≤2.0 g/kg caps are **re-asserted here** even though
``app/core/profile.py`` already enforces them at load (``deficit_pct: Field(le=0.20)``,
``protein_g_per_kg: Field(le=2.0)``) — defence in depth, because the epic §4 states the
cap as the **engine's** contract (twice) and a raw caller (e.g. the §7.3 rest-day
deficit lever) could otherwise blow it (DECISIONS Decision 3).

``DayType`` is the canonical ``app.core.enums.DayType`` (E7) — ``hard·moderate·rest`` —
reused, not redefined; it is an **input**, never chosen or floored here (the LLM picks
it, E7's validator floors it).
"""

from __future__ import annotations

import math

from app.core.enums import DayType
from app.core.profile import CarbsPerKg

# --- Pinned constants, transcribed verbatim from CONSTITUTION §7 (single source) ---

# §7.1 "never let the deficit exceed ~20%" — the hard calorie-deficit cap.
MAX_DEFICIT_PCT = 0.20
# §7.2 "kidney-stone cap ~2.0" — the constant-protein ceiling (g/kg/day).
MAX_PROTEIN_G_PER_KG = 2.0
# §7.3 rest-day "larger deficit" lever — the deepest cap-legal rest cut, routed through
# ``clamp_deficit`` so it stays ≤0.20 (DECISIONS Decision 5; the rest total is a §7.3
# day-type lever, distinct from the §7.1 week-average ``deficit_pct`` but bounded by the
# same ≤0.20 cap). At the worked athlete TDEE × 0.80 → 2287 (§7.3's "~2,200" is the doc's
# illustration; landing exactly ~2,200 would need a ~0.23 deficit, which the cap forbids).
REST_DEFICIT_PCT = 0.20
# The standard Mifflin-St Jeor sex constant pair (male +5, female −161); §7.1 renders
# the male form for this athlete, but ``bmr`` is total for either sex (DECISIONS 2).
BMR_SEX_CONSTANT = {"male": 5, "female": -161}


def _round_half_up(x: float) -> int:
    """Round a non-negative value half-**up** to an ``int`` (DECISIONS Decision 4).

    The pinned rounding for **every** gram/calorie emit. Python's built-in ``round``
    is banker's (round-half-to-even), so ``round(364.5) == 364``, but MODELS' hard
    ``dayTypePattern`` carb is **365** — half-up (``floor(x + 0.5)``) reproduces it.
    Grams/calories are non-negative here, so half-up is unambiguous.
    """
    return math.floor(x + 0.5)


def bmr(*, weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    """Basal metabolic rate via Mifflin-St Jeor (CONSTITUTION §7.1).

    ``BMR = 10·W + 6.25·height_cm − 5·age + S`` where ``S`` is the sex constant
    (male ``+5`` / female ``−161``). Returns the **raw float** — rounding happens only
    at the final macro/calorie emit (DECISIONS Decision 4). An unrecognised ``sex``
    defaults to the male ``+5`` (the profile is male and §7.1 renders the male form).
    At W=81, h=174, age=34, male → **1732.5** (§7.1 "BMR ≈ 1,733").
    """
    sex_constant = BMR_SEX_CONSTANT.get(sex.lower(), BMR_SEX_CONSTANT["male"])
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + sex_constant


def tdee(bmr_kcal: float, activity_factor: float) -> float:
    """Total daily energy expenditure (CONSTITUTION §7.1) — ``BMR × activity_factor``.

    Returns the **raw float**. At BMR 1732.5 × the profile's 1.50 → 2598.75 (§7.1
    "TDEE ~2,600"); at × 1.65 → 2858.625.
    """
    return bmr_kcal * activity_factor


def clamp_deficit(deficit_pct: float) -> float:
    """Re-assert the §7.1 ≤0.20 deficit cap — ``min(deficit_pct, MAX_DEFICIT_PCT)``.

    Only ever **reduces** an over-cap value (DECISIONS Decision 3 — defence in depth
    over the profile schema's ``Field(le=0.20)``); a valid profile deficit is a no-op.
    """
    return min(deficit_pct, MAX_DEFICIT_PCT)


def deficit_target(tdee_kcal: float, deficit_pct: float) -> float:
    """Average daily calorie target (CONSTITUTION §7.1) — ``TDEE × (1 − deficit)``.

    The deficit is routed through ``clamp_deficit`` so the target can never fall below
    ``0.80 × TDEE`` (the ≤0.20 cap; epic §4). Returns the **raw float**. At TDEE
    2858.625 × (1 − 0.12) → 2515.59; at the profile's TDEE 2598.75 × (1 − 0.12) → 2286.9
    (§7.1 "avg target ~2,290").
    """
    return tdee_kcal * (1 - clamp_deficit(deficit_pct))


def protein_g(weight_kg: float, protein_g_per_kg: float) -> int:
    """Daily protein target in grams (CONSTITUTION §7.2) — constant across day types.

    ``round_half_up(W × min(protein_g_per_kg, MAX_PROTEIN_G_PER_KG))`` — the g/kg is
    re-capped at 2.0 (the §7.2 kidney-stone cap; DECISIONS Decision 3) so the gram count
    can never exceed ``round(2.0 × W)``. Takes **no** ``DayType`` — protein is constant
    every day (§7.2). At 81 × 1.8 = 145.8 → **146** (MODELS ``proteinG: 146``).
    """
    return _round_half_up(weight_kg * min(protein_g_per_kg, MAX_PROTEIN_G_PER_KG))


def fat_g_range(weight_kg: float, low_g_per_kg: float, high_g_per_kg: float) -> tuple[int, int]:
    """Daily fat target range in grams (CONSTITUTION §7.2) — constant across day types.

    ``(round_half_up(W × low), round_half_up(W × high))``. Takes **no** ``DayType`` —
    fat is constant every day (§7.2). At 81 × (0.8, 1.0) → **(65, 81)** (64.8→65,
    81.0→81 — the engine's honest round; MODELS shows ``fatGHigh: 80``, the doc's
    down-round of ``1.0 × 81``, in-band per §7.2's "≈ 65–80 g" — a noted divergence).
    """
    return (_round_half_up(weight_kg * low_g_per_kg), _round_half_up(weight_kg * high_g_per_kg))


def carbs_g(weight_kg: float, day_type: DayType, carbs: CarbsPerKg) -> int:
    """Daily carb target in grams **by day type** (CONSTITUTION §7.3; DECISIONS 5).

    Carbs are the §7.3 carb-cycling lever — the one macro that moves with ``dayType``.
    The §7.3 table gives a g/kg **band** for hard/rest and a single multiplier for
    moderate; the engine emits the **band midpoint** × W as the single int MODELS'
    ``carbsG`` requires (the band itself is surfaced in the LLM nutrition narrative):
    ``hard`` → mid(``hard_low``, ``hard_high``); ``moderate`` → ``moderate``; ``rest``
    → mid(``rest_low``, ``rest_high``). At W=81: hard mid 4.5 → **365**, moderate 3 →
    **243**, rest mid 2.25 → **182**.
    """
    if day_type == DayType.hard:
        g_per_kg = (carbs.hard_low + carbs.hard_high) / 2
    elif day_type == DayType.rest:
        g_per_kg = (carbs.rest_low + carbs.rest_high) / 2
    else:  # DayType.moderate — the single §7.3 multiplier
        g_per_kg = carbs.moderate
    return _round_half_up(weight_kg * g_per_kg)


def calories_kcal(day_type: DayType, *, tdee_kcal: float, target_avg_kcal: float) -> int:
    """Daily calorie total **by day type** (MODELS "TDEE × day type"; §7.3; DECISIONS 5).

    The calorie total is computed independently of the carb grams (MODELS types
    ``caloriesKcal`` and ``carbsG`` as two code outputs, not one derived from the
    other): ``hard`` → TDEE (~maintenance); ``moderate`` → the §7.1 ``Target_avg``;
    ``rest`` → ``TDEE × (1 − clamp_deficit(REST_DEFICIT_PCT))`` (the deeper rest-day
    cut, **cap-safe** ≤0.20). The week of (hard ~maintenance, moderate ~avg, rest
    ~deepest-deficit) nets to the §7.1 average (§7.3). At the worked athlete: hard 2859
    (TDEE), moderate 2516 (target), rest 2287 (TDEE×0.80) — ``rest < moderate < hard``.
    """
    if day_type == DayType.hard:
        return _round_half_up(tdee_kcal)
    if day_type == DayType.rest:
        return _round_half_up(tdee_kcal * (1 - clamp_deficit(REST_DEFICIT_PCT)))
    return _round_half_up(target_avg_kcal)  # DayType.moderate → the §7.1 avg target
