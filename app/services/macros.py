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
from typing import TYPE_CHECKING

from pydantic import field_validator, model_validator

from app.api.schemas.base import CamelModel
from app.core.enums import DayType
from app.core.profile import Athlete, CarbsPerKg, Nutrition

if TYPE_CHECKING:  # type-only — no import-time coupling (no macros↔aggregates cycle)
    from app.services.aggregates import NutritionAdherence

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
    ~deepest-deficit) nets to the §7.1 average (§7.3). At the real profile (AF 1.50,
    deficit 0.12, W=81): hard 2599 (TDEE), moderate 2287 (target), rest 2079 (TDEE×0.80)
    — ``rest < moderate < hard``. (When a profile's ``deficit_pct`` itself sits at the
    0.20 cap, moderate's target equals rest's ``TDEE×0.80``, so the ordering relaxes to
    ``rest == moderate < hard`` — both legitimately at the cap; the production 0.12 keeps
    it strict.)
    """
    if day_type == DayType.hard:
        return _round_half_up(tdee_kcal)
    if day_type == DayType.rest:
        return _round_half_up(tdee_kcal * (1 - clamp_deficit(REST_DEFICIT_PCT)))
    return _round_half_up(target_avg_kcal)  # DayType.moderate → the §7.1 avg target


def hydration_l_range(low_l: float, high_l: float, *, sweat_l: float = 0.0) -> tuple[float, float]:
    """Daily hydration target range in litres (CONSTITUTION §7.4; DECISIONS 7).

    The baseline range **plus** an additive sweat-replacement term: ``(low_l +
    sweat_l, high_l + sweat_l)``. ``sweat_l`` defaults to ``0.0`` → the plain baseline
    (MODELS ``hydrationLLow: 3.0``/``hydrationLHigh: 3.5``); a caller that knows the
    session (E11) may pass estimated sweat litres to add on top. Returns **floats** (no
    rounding — Decision 4; ``3.0`` stays ``3.0``, MODELS types these as ``number``).
    """
    return (low_l + sweat_l, high_l + sweat_l)


# --- Result models — exactly the MODELS field set, camelCase on the wire (DECISIONS 1/8/10) ---


class MacroFocus(CamelModel):
    """The day's nutrition target (MODELS ``MacroFocus``) — all numbers code-computed.

    Snake_case fields serialize to the MODELS camelCase wire names
    (``dayType``/``caloriesKcal``/``proteinG``/``carbsG``/``fatGLow``/``fatGHigh``/
    ``hydrationLLow``/``hydrationLHigh``). Carries exactly the MODELS fields — **no**
    fiber/sodium target (those are §7.4 narrative/medical filters, not code targets —
    Decision 10).
    """

    day_type: DayType
    calories_kcal: int
    protein_g: int
    carbs_g: int
    fat_g_low: int
    fat_g_high: int
    hydration_l_low: float
    hydration_l_high: float


class DayTypePatternEntry(CamelModel):
    """One planned-session entry of ``WeeklyNutrition.dayTypePattern`` (MODELS).

    ``{suggestedDay, dayType, caloriesKcal, carbsG}`` — the per-session calorie/carb
    numbers, derived from the same selectors as the daily focus (single source).
    """

    suggested_day: str
    day_type: DayType
    calories_kcal: int
    carbs_g: int


class LastWeekNutrition(CamelModel):
    """The 7-day intake scorecard MODELS' ``WeeklyNutrition.lastWeek`` carries (E13·P1).

    Exactly the five documented camelCase fields → wire keys ``avgCaloriesKcal``,
    ``avgProteinG``, ``proteinHitDays``, ``daysOverTarget``, ``daysUnderTarget``. The two
    averages are window means of logged intake (``None`` for a nutrient with no logged
    day — never fabricated); the three counts are target-gated and stay ``None`` until
    E13·P2 wires ``nutrition_target_7d``. Every field is ``int | None = None`` so the
    object honestly represents partial coverage (calorie-only / protein-only weeks) and a
    legacy cached payload with missing keys still validates (DECISIONS Decisions 2 & 5).

    The ``mode="before"`` validator is the **single rounding site**: it rounds an incoming
    ``float`` average to ``int`` via ``_round_half_up``, serving both the float means
    ``from_adherence`` passes in **and** a legacy cached payload's raw fractional
    ``avg_protein_g`` (which Pydantic v2 lax mode would otherwise reject for an ``int``
    field — round-2 #1; DECISIONS Decision 4).
    """

    avg_calories_kcal: int | None = None
    avg_protein_g: int | None = None
    protein_hit_days: int | None = None
    days_over_target: int | None = None
    days_under_target: int | None = None

    @field_validator("avg_calories_kcal", "avg_protein_g", mode="before")
    @classmethod
    def _round_float_average(cls, value: object) -> object:
        """Round a ``float`` average half-up to ``int``; pass ``int``/``None`` through."""
        return _round_half_up(value) if isinstance(value, float) else value

    @classmethod
    def from_adherence(cls, adherence: NutritionAdherence | None) -> LastWeekNutrition | None:
        """Map an E6·P3 ``NutritionAdherence`` → the ``lastWeek`` scorecard.

        Returns ``None`` (→ ``lastWeek: null``, the empty state) when ``adherence`` is
        ``None`` **or** the window logged neither calories nor protein
        (``kcal_in_n == 0 and protein_in_g_n == 0``; DECISIONS Decision 3) — so a non-null
        object always carries ≥1 non-null average. The float averages are passed straight
        in (the validator rounds them); the three target-gated counts pass through (``None``
        until E13·P2).
        """
        if adherence is None:
            return None
        consumed = adherence.consumed
        if consumed.kcal_in_n == 0 and consumed.protein_in_g_n == 0:
            return None
        # `model_validate` runs the `mode="before"` float→int rounding validator; the
        # float averages are passed straight in (DECISIONS Decision 4).
        return cls.model_validate(
            {
                "avg_calories_kcal": adherence.avg_kcal,
                "avg_protein_g": adherence.avg_protein_g,
                "protein_hit_days": adherence.protein_hit_days,
                "days_over_target": adherence.days_over_target,
                "days_under_target": adherence.days_under_target,
            }
        )


class WeeklyNutrition(CamelModel):
    """The weekly brief's nutrition half (MODELS ``WeeklyNutrition``) — all code-derived.

    The constant targets (``proteinG``/``fatGLow/High``/``hydrationLLow/High``) + the
    week-average target (``avgCaloriesKcal`` = the §7.1 ``Target_avg``, the figure the
    per-day-type calories net to — Decision 5) + the ``dayTypePattern`` from the planned
    picks. ``lastWeek`` (7-day intake adherence) is a typed ``LastWeekNutrition`` (E13·P1)
    or ``None`` (no logged dietary coverage); ``ComputeNutritionNode`` builds it via
    ``LastWeekNutrition.from_adherence``.
    """

    protein_g: int
    fat_g_low: int
    fat_g_high: int
    hydration_l_low: float
    hydration_l_high: float
    avg_calories_kcal: int
    day_type_pattern: list[DayTypePatternEntry]
    last_week: LastWeekNutrition | None = None

    @field_validator("last_week", mode="before")
    @classmethod
    def _map_legacy_last_week(cls, value: object) -> object:
        """Translate a **legacy** cached ``lastWeek`` dump to the five-key shape (E13·P1
        review #1). Key mapping only — the empty-state collapse is ``_empty_last_week_is_null``.

        Current rows store ``lastWeek`` as ``LastWeekNutrition.from_adherence``'s output (the
        five camelCase keys, or ``null``). A pre-E13·P1 ``plans.payload`` instead stored
        ``dataclasses.asdict(NutritionAdherence)`` — a snake_case dict carrying
        ``consumed``/``target``/``avg_kcal``/``kcal_pct``. The cache-hit re-validation path
        (``weekly.py``) runs on **every** cache read, so that legacy dict (identified by its
        ``consumed`` key) is projected onto the five contract fields, mapping the legacy
        ``avg_kcal`` to ``avg_calories_kcal`` (else the stored calorie average would silently
        drop to ``null``). Non-legacy values (a ``LastWeekNutrition``, ``None``, or a current
        camelCase dict — none of which carry a ``consumed`` key) pass through untouched. This
        is read-side tolerance, not a row migration (DECISIONS Decision 5): rows aren't rewritten.
        """
        if isinstance(value, dict) and "consumed" in value:
            return {
                "avg_calories_kcal": value.get("avg_kcal"),
                "avg_protein_g": value.get("avg_protein_g"),
                "protein_hit_days": value.get("protein_hit_days"),
                "days_over_target": value.get("days_over_target"),
                "days_under_target": value.get("days_under_target"),
            }
        return value

    @model_validator(mode="after")
    def _empty_last_week_is_null(self) -> WeeklyNutrition:
        """Collapse an all-null ``lastWeek`` to ``None`` regardless of provenance — the P1
        empty-state contract ("never a populated all-null object on the wire") enforced at
        the validation boundary, not just at the ``from_adherence`` producer (review #2/#3).

        A non-null ``LastWeekNutrition`` whose five contract fields are *all* ``None`` carries
        no information, so it is the empty state. This catches every way one can arise on the
        cache-hit re-validation path: a legacy no-coverage asdict dump, a legacy
        covered-but-no-target row (old target-gating left ``avg_kcal``/``avg_protein_g``
        ``None`` despite logged days), and a current-format five-key payload that is all-null
        (intermediate-build / future cache drift). The live producer never emits such an
        object (``from_adherence`` returns ``None`` for no coverage and otherwise carries ≥1
        non-null average), so this is purely a read-side safety net — no production change.
        """
        lw = self.last_week
        if lw is not None and all(
            field is None
            for field in (
                lw.avg_calories_kcal,
                lw.avg_protein_g,
                lw.protein_hit_days,
                lw.days_over_target,
                lw.days_under_target,
            )
        ):
            self.last_week = None
        return self


def _require_positive_weight(weight_kg: float) -> None:
    """A macro brief is meaningless for a non-positive body weight (missing/garbage
    scale data) — fail fast rather than silently emit negative grams/calories (review).
    """
    if not weight_kg > 0:
        raise ValueError(f"weight_kg must be > 0 to compute macros, got {weight_kg!r}")


def compute_macro_focus(
    *,
    day_type: DayType,
    weight_kg: float,
    nutrition: Nutrition,
    athlete: Athlete,
    sweat_l: float = 0.0,
) -> MacroFocus:
    """Build the daily ``MacroFocus`` (the entry E11 calls; CONSTITUTION §7).

    Keyword-only so a call site can never pair the wrong constant with a number. Reads
    already-loaded ``Nutrition``/``Athlete`` sub-models (E11's loader builds them once
    per brief) + a live ``weight_kg`` — it opens no session and reads no file.
    ``day_type`` is the **already-chosen, already-floored** input (the LLM picks it,
    E7's validator floors it); this function classifies nothing.
    """
    _require_positive_weight(weight_kg)
    b = bmr(weight_kg=weight_kg, height_cm=athlete.height_cm, age=athlete.age, sex=athlete.sex)
    t = tdee(b, nutrition.activity_factor)
    target = deficit_target(t, nutrition.deficit_pct)
    fat_low, fat_high = fat_g_range(weight_kg, nutrition.fat_g_per_kg_low, nutrition.fat_g_per_kg_high)
    hyd_low, hyd_high = hydration_l_range(
        nutrition.hydration_l_low, nutrition.hydration_l_high, sweat_l=sweat_l
    )
    return MacroFocus(
        day_type=day_type,
        calories_kcal=calories_kcal(day_type, tdee_kcal=t, target_avg_kcal=target),
        protein_g=protein_g(weight_kg, nutrition.protein_g_per_kg),
        carbs_g=carbs_g(weight_kg, day_type, nutrition.carbs_g_per_kg),
        fat_g_low=fat_low,
        fat_g_high=fat_high,
        hydration_l_low=hyd_low,
        hydration_l_high=hyd_high,
    )


def day_type_pattern(
    picks: list[tuple[str, DayType]],
    *,
    weight_kg: float,
    nutrition: Nutrition,
    athlete: Athlete,
) -> list[DayTypePatternEntry]:
    """One ``DayTypePatternEntry`` per planned session (MODELS ``dayTypePattern``).

    Reuses the **same** ``carbs_g``/``calories_kcal`` selectors as the daily focus
    (single source — Decision 5), so a ``hard`` weekly entry and a ``hard``
    ``MacroFocus`` carry identical ``carbsG``/``caloriesKcal``. The session→``dayType``
    mapping is the caller's (E10 reads each pick's ``CARD_META.day_type``); this helper
    takes the resolved ``dayType`` per pick.
    """
    _require_positive_weight(weight_kg)
    b = bmr(weight_kg=weight_kg, height_cm=athlete.height_cm, age=athlete.age, sex=athlete.sex)
    t = tdee(b, nutrition.activity_factor)
    target = deficit_target(t, nutrition.deficit_pct)
    return [
        DayTypePatternEntry(
            suggested_day=suggested_day,
            day_type=dt,
            calories_kcal=calories_kcal(dt, tdee_kcal=t, target_avg_kcal=target),
            carbs_g=carbs_g(weight_kg, dt, nutrition.carbs_g_per_kg),
        )
        for suggested_day, dt in picks
    ]


def compute_weekly_nutrition(
    *,
    picks: list[tuple[str, DayType]],
    weight_kg: float,
    nutrition: Nutrition,
    athlete: Athlete,
    last_week: LastWeekNutrition | None = None,
    sweat_l: float = 0.0,
) -> WeeklyNutrition:
    """Build the weekly ``WeeklyNutrition`` (the entry E10 calls; CONSTITUTION §7).

    The constant ``proteinG``/``fatG*``/``hydration*`` targets, ``avgCaloriesKcal`` =
    the §7.1 ``Target_avg`` (the week-average target the per-day-type calories net to —
    Decision 5), and the ``dayTypePattern`` from the picks. ``last_week`` is passed
    **through** unchanged (or left ``None``) — its derivation from logged intake is
    E6·P3/E10 (Decision 9). Keyword-only.
    """
    _require_positive_weight(weight_kg)
    b = bmr(weight_kg=weight_kg, height_cm=athlete.height_cm, age=athlete.age, sex=athlete.sex)
    t = tdee(b, nutrition.activity_factor)
    target = deficit_target(t, nutrition.deficit_pct)
    fat_low, fat_high = fat_g_range(weight_kg, nutrition.fat_g_per_kg_low, nutrition.fat_g_per_kg_high)
    hyd_low, hyd_high = hydration_l_range(
        nutrition.hydration_l_low, nutrition.hydration_l_high, sweat_l=sweat_l
    )
    return WeeklyNutrition(
        protein_g=protein_g(weight_kg, nutrition.protein_g_per_kg),
        fat_g_low=fat_low,
        fat_g_high=fat_high,
        hydration_l_low=hyd_low,
        hydration_l_high=hyd_high,
        avg_calories_kcal=_round_half_up(target),
        day_type_pattern=day_type_pattern(
            picks, weight_kg=weight_kg, nutrition=nutrition, athlete=athlete
        ),
        last_week=last_week,
    )
