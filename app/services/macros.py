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

# --- Pinned constants, transcribed verbatim from CONSTITUTION §7 (single source) ---

# §7.1 "never let the deficit exceed ~20%" — the hard calorie-deficit cap.
MAX_DEFICIT_PCT = 0.20
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
