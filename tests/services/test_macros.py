"""E8·P3 nutrition / macro-engine tests — pure table-driven unit tests.

No DB session, no ``TestClient``, no LLM (epic R6) — every input is a plain number
or a hand-built ``Nutrition``/``Athlete``. The cases mirror CONSTITUTION §7's worked
chain: §7.1 BMR (Mifflin-St Jeor, male ``10·W + 6.25·h − 5·age + 5``) → TDEE → target
with the ≤0.20 deficit cap; §7.2 constant protein (cap ≤2.0) + fat range; §7.3
day-type carb cycling + the TDEE × day-type calories; §7.4 hydration baseline + sweat;
and the MODELS ``MacroFocus``/``WeeklyNutrition`` shapes.

Note on ``activity_factor``: the pure-function tests below pin ``tdee``/``deficit_target``
against **explicit** inputs (e.g. ``tdee(1732.5, 1.65)``), which is correct arithmetic for
any caller. The ``compute_macro_focus``/``compute_weekly_nutrition`` end-to-end tests read
the **real** ``profile.yaml`` constant (``activity_factor = 1.50``) via a hand-built
``Nutrition`` matching the §5 block, so they reproduce the CONSTITUTION §7.1 worked chain
at AF=1.50 (BMR 1732.5 → TDEE 2598.75 → target 2286.9). (See the report for the AF
divergence between the plan's pinned 1.65 examples and profile.yaml/§7.1's 1.50.)
"""

from __future__ import annotations

import math

import pytest

from app.core.enums import DayType
from app.core.profile import Athlete, CarbsPerKg, Nutrition
from app.services.aggregates import NutritionAdherence, NutritionConsumed
from app.services.macros import (
    BMR_SEX_CONSTANT,
    MAX_DEFICIT_PCT,
    MAX_PROTEIN_G_PER_KG,
    REST_DEFICIT_PCT,
    DayTypePatternEntry,
    LastWeekNutrition,
    RestDayNutrition,
    WeeklyNutrition,
    _round_half_up,
    bmr,
    calories_kcal,
    carbs_g,
    clamp_deficit,
    compute_macro_focus,
    compute_weekly_nutrition,
    day_type_pattern,
    deficit_target,
    fat_g_range,
    hydration_l_range,
    per_day_nutrition_target,
    protein_g,
    tdee,
)

# The §7.1 worked athlete (profile.yaml: W is live, the rest are the static athlete block).
_W = 81.0
_HEIGHT_CM = 174
_AGE = 34

# The §7.1 worked chain *at the plan's pinned activity_factor 1.65* (pure-arithmetic pins).
_BMR_81 = 1732.5
_TDEE_AF165 = 2858.625  # 1732.5 × 1.65

# The §5 carb-multiplier block (profile.yaml `nutrition.carbs_g_per_kg`).
_CARBS = CarbsPerKg(hard_low=4, hard_high=5, moderate=3, rest_low=2, rest_high=2.5)

# The §5 nutrition + athlete blocks, mirroring profile.yaml 1:1 — so the end-to-end
# compute_* tests reproduce the *real* CONSTITUTION §7.1 chain at activity_factor 1.50
# (BMR 1732.5 → TDEE 2598.75 → target 2286.9), not the plan's pinned-1.65 figures.
_NUTRITION = Nutrition(
    activity_factor=1.50,
    deficit_pct=0.12,
    protein_g_per_kg=1.8,
    fat_g_per_kg_low=0.8,
    fat_g_per_kg_high=1.0,
    carbs_g_per_kg=_CARBS,
    hydration_l_low=3.0,
    hydration_l_high=3.5,
    fiber_g_low=25,
    fiber_g_high=35,
)
_ATHLETE = Athlete(age=34, sex="male", height_cm=174, goal_weight_kg=75)

# The §7.1 worked chain at the *profile* activity_factor 1.50.
_TDEE_AF150 = 2598.75  # 1732.5 × 1.50
_TARGET_AF150 = _round_half_up(_TDEE_AF150 * (1 - 0.12))  # 2286.9 → 2287


# --- bmr (§7.1 Mifflin-St Jeor; DECISIONS 1/2) ---


def test_bmr_male_matches_section_7_1_worked_point():
    # §7.1 "BMR ≈ 1,733" — exactly 1732.5 at W=81, h=174, age=34, male (+5).
    assert bmr(weight_kg=_W, height_cm=_HEIGHT_CM, age=_AGE, sex="male") == _BMR_81


def test_bmr_female_uses_minus_161_constant():
    male = bmr(weight_kg=_W, height_cm=_HEIGHT_CM, age=_AGE, sex="male")
    female = bmr(weight_kg=_W, height_cm=_HEIGHT_CM, age=_AGE, sex="female")
    # The standard Mifflin-St Jeor pair differs by +5 − (−161) = 166 kcal.
    assert male - female == 166
    assert female == _BMR_81 - 166


def test_bmr_sex_constant_pair_is_the_standard_msj():
    assert BMR_SEX_CONSTANT["male"] == 5
    assert BMR_SEX_CONSTANT["female"] == -161


def test_bmr_unrecognised_sex_defaults_to_male():
    # The profile is male and §7.1 renders the male form — the chosen default.
    assert bmr(weight_kg=_W, height_cm=_HEIGHT_CM, age=_AGE, sex="other") == _BMR_81


# --- tdee (§7.1 TDEE = BMR × activity_factor) ---


def test_tdee_is_bmr_times_activity_factor():
    assert tdee(_BMR_81, 1.65) == _TDEE_AF165


def test_tdee_at_profile_activity_factor_1_50_matches_section_7_1():
    # profile.yaml / §7.1 worked example uses activity_factor 1.50 → TDEE ~2,600.
    assert tdee(_BMR_81, 1.50) == 2598.75


# --- clamp_deficit + deficit_target (§7.1 "never let the deficit exceed ~20%"; DECISIONS 3) ---


def test_clamp_deficit_caps_at_max():
    assert MAX_DEFICIT_PCT == 0.20
    assert clamp_deficit(0.30) == 0.20  # over-cap → clamped
    assert clamp_deficit(0.20) == 0.20  # exact cap → unchanged
    assert clamp_deficit(0.05) == 0.05  # below cap → unchanged


def test_deficit_target_at_section_7_1_worked_point():
    # §7.1 "avg target ~2,520" at AF=1.65, deficit 0.12 → 2515.59.
    assert deficit_target(_TDEE_AF165, 0.12) == pytest.approx(2515.59)


def test_deficit_target_re_asserts_the_cap():
    t = _TDEE_AF165
    assert deficit_target(t, 0.20) == pytest.approx(t * 0.80)  # exact cap
    assert deficit_target(t, 0.30) == pytest.approx(t * 0.80)  # clamped to 0.20
    assert deficit_target(t, 0.05) == pytest.approx(t * 0.95)  # unclamped below cap
    # The clamp never lets the target fall below 0.80·T no matter how large the pct.
    assert deficit_target(t, 0.99) == pytest.approx(t * 0.80)


# --- _round_half_up (DECISIONS 4 — the pinned half-up rule) ---


def test_round_half_up_pins_the_point_five_edge():
    # MODELS' hard carb 364.5 → 365 (Python's banker's round() would give 364).
    assert _round_half_up(364.5) == 365
    assert math.isclose(round(364.5), 364)  # documents the banker's-round divergence
    assert _round_half_up(145.8) == 146
    assert _round_half_up(81.0) == 81
    assert _round_half_up(64.8) == 65


# --- protein_g (§7.2 constant protein, kidney-stone cap ≤2.0; DECISIONS 3) ---


def test_protein_g_at_worked_point():
    # §7.2 "≈ 146 g" — 81 × 1.8 = 145.8 → 146 (MODELS proteinG: 146).
    assert protein_g(_W, 1.8) == 146


def test_protein_g_re_asserts_the_2_0_cap():
    assert MAX_PROTEIN_G_PER_KG == 2.0
    # 81 × 2.0 = 162; an over-cap g/kg is clamped to 2.0, never 2.5.
    assert protein_g(_W, 2.5) == _round_half_up(_W * 2.0) == 162
    assert protein_g(_W, 2.0) == 162  # exact cap → 162
    assert protein_g(_W, 2.5) != _round_half_up(_W * 2.5)  # never the un-capped value


def test_protein_g_returns_int():
    assert isinstance(protein_g(_W, 1.8), int)


# --- fat_g_range (§7.2 fat 0.8–1.0 g/kg) ---


def test_fat_g_range_at_worked_point():
    # §7.2 "≈ 65–80 g": 81 × 0.8 = 64.8 → 65; 81 × 1.0 = 81.0 → 81 (engine's honest
    # round; MODELS shows fatGHigh: 80, the doc's down-round — a noted divergence).
    assert fat_g_range(_W, 0.8, 1.0) == (65, 81)
    low, high = fat_g_range(_W, 0.8, 1.0)
    assert isinstance(low, int) and isinstance(high, int)


# --- carbs_g (§7.3 day-type carb cycling; band midpoint × W; DECISIONS 5) ---


def test_carbs_g_by_day_type_worked_points():
    # hard mid(4,5)=4.5 → 81 × 4.5 = 364.5 → 365 (MODELS hard carbsG: 365).
    assert carbs_g(_W, DayType.hard, _CARBS) == 365
    # moderate 3 → 243 (§7.3 "~245 g" is the doc's round figure).
    assert carbs_g(_W, DayType.moderate, _CARBS) == 243
    # rest mid(2,2.5)=2.25 → 81 × 2.25 = 182.25 → 182 (inside §7.3 "~165–200 g").
    assert carbs_g(_W, DayType.rest, _CARBS) == 182


def test_carbs_g_strictly_increasing_rest_moderate_hard():
    rest = carbs_g(_W, DayType.rest, _CARBS)
    moderate = carbs_g(_W, DayType.moderate, _CARBS)
    hard = carbs_g(_W, DayType.hard, _CARBS)
    assert rest < moderate < hard


def test_carbs_g_accepts_the_wire_string_values():
    # DayType is a str-Enum, so the MODELS wire strings work directly.
    assert carbs_g(_W, "hard", _CARBS) == carbs_g(_W, DayType.hard, _CARBS)
    assert carbs_g(_W, "moderate", _CARBS) == carbs_g(_W, DayType.moderate, _CARBS)
    assert carbs_g(_W, "rest", _CARBS) == carbs_g(_W, DayType.rest, _CARBS)


# --- calories_kcal (§7.3 TDEE × day-type; rest cap-routed ≤0.20; DECISIONS 5) ---


def test_calories_kcal_by_day_type_worked_points():
    # At the plan's AF=1.65 worked chain (TDEE 2858.625, target 2515.59):
    t, target = _TDEE_AF165, 2515.59
    assert calories_kcal(DayType.hard, tdee_kcal=t, target_avg_kcal=target) == 2859  # ~TDEE
    assert calories_kcal(DayType.moderate, tdee_kcal=t, target_avg_kcal=target) == 2516
    # rest = TDEE × (1 − 0.20) = 2286.9 → 2287 (cap-safe; §7.3's "~2,200" is illustrative).
    assert calories_kcal(DayType.rest, tdee_kcal=t, target_avg_kcal=target) == 2287


def test_calories_kcal_rest_routes_through_the_deficit_cap():
    assert REST_DEFICIT_PCT == 0.20
    t = _TDEE_AF165
    # The rest deficit is cap-routed, so the rest total can never dip below 0.80·TDEE.
    assert calories_kcal(DayType.rest, tdee_kcal=t, target_avg_kcal=2515.59) == _round_half_up(
        t * (1 - clamp_deficit(REST_DEFICIT_PCT))
    )


def test_calories_kcal_strictly_increasing_rest_moderate_hard():
    t, target = _TDEE_AF165, 2515.59
    rest = calories_kcal(DayType.rest, tdee_kcal=t, target_avg_kcal=target)
    moderate = calories_kcal(DayType.moderate, tdee_kcal=t, target_avg_kcal=target)
    hard = calories_kcal(DayType.hard, tdee_kcal=t, target_avg_kcal=target)
    assert rest < moderate < hard


# --- the carb-cycling contract: only carbs + calories move with dayType ---


def test_protein_and_fat_are_constant_across_day_types():
    # protein_g / fat_g_range take no dayType — they are identical for every day type,
    # while carbs_g / calories_kcal differ (§7.2 "Protein stays ~constant every day").
    proteins = {protein_g(_W, 1.8) for _ in DayType}
    fats = {fat_g_range(_W, 0.8, 1.0) for _ in DayType}
    assert len(proteins) == 1
    assert len(fats) == 1
    t, target = _TDEE_AF165, 2515.59
    carbs = {carbs_g(_W, dt, _CARBS) for dt in DayType}
    cals = {calories_kcal(dt, tdee_kcal=t, target_avg_kcal=target) for dt in DayType}
    assert len(carbs) == 3  # all three differ
    assert len(cals) == 3


# --- hydration_l_range (§7.4 baseline + additive sweat; DECISIONS 7) ---


def test_hydration_l_range_baseline():
    assert hydration_l_range(3.0, 3.5) == (3.0, 3.5)
    low, high = hydration_l_range(3.0, 3.5)
    assert isinstance(low, float) and isinstance(high, float)  # not rounded to int


def test_hydration_l_range_adds_sweat():
    assert hydration_l_range(3.0, 3.5, sweat_l=1.0) == (4.0, 4.5)


# --- MacroFocus assembly (MODELS; reproduces the §7.1 chain at the *profile* AF=1.50) ---

# The exact MODELS MacroFocus field set (camelCase wire names).
_MACRO_FOCUS_FIELDS = {
    "dayType",
    "caloriesKcal",
    "proteinG",
    "carbsG",
    "fatGLow",
    "fatGHigh",
    "hydrationLLow",
    "hydrationLHigh",
}


def test_compute_macro_focus_moderate_reproduces_profile_chain():
    focus = compute_macro_focus(
        day_type=DayType.moderate, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    )
    # AF-independent macros match MODELS / the plan exactly.
    assert focus.protein_g == 146
    assert focus.carbs_g == 243  # moderate 3 g/kg × 81 (§7.3; the doc's "~245")
    assert focus.fat_g_low == 65
    assert focus.fat_g_high == 81  # engine's honest round(81.0); MODELS shows 80 (doc round)
    assert focus.hydration_l_low == 3.0
    assert focus.hydration_l_high == 3.5
    # Calories follow the *real* profile AF=1.50 chain → 2287 (the plan's 2516/2520
    # assumed AF=1.65; profile.yaml & §7.1 use 1.50, so the engine emits 2287).
    assert focus.calories_kcal == _TARGET_AF150 == 2287
    assert focus.day_type == DayType.moderate


def test_macro_focus_wire_field_set_matches_models():
    focus = compute_macro_focus(
        day_type=DayType.moderate, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    )
    # camelCase serialization == the MODELS MacroFocus field set (no fiber/sodium).
    assert set(focus.model_dump(by_alias=True)) == _MACRO_FOCUS_FIELDS


def test_macro_focus_carb_cycling_across_day_types():
    hard = compute_macro_focus(
        day_type=DayType.hard, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    )
    moderate = compute_macro_focus(
        day_type=DayType.moderate, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    )
    rest = compute_macro_focus(
        day_type=DayType.rest, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    )
    # carbs + calories carb-load up for hard, pull down for rest.
    assert rest.carbs_g < moderate.carbs_g < hard.carbs_g
    assert rest.calories_kcal < moderate.calories_kcal < hard.calories_kcal
    # protein / fat / hydration held constant across the three.
    for held in ("protein_g", "fat_g_low", "fat_g_high", "hydration_l_low", "hydration_l_high"):
        assert getattr(hard, held) == getattr(moderate, held) == getattr(rest, held)


def test_compute_macro_focus_passes_sweat_to_hydration():
    focus = compute_macro_focus(
        day_type=DayType.moderate,
        weight_kg=_W,
        nutrition=_NUTRITION,
        athlete=_ATHLETE,
        sweat_l=1.0,
    )
    assert focus.hydration_l_low == 4.0
    assert focus.hydration_l_high == 4.5


# --- WeeklyNutrition + dayTypePattern (MODELS; DECISIONS 5/9) ---

_PICKS = [("mon", DayType.moderate), ("tue", DayType.hard), ("fri", DayType.hard)]


def test_compute_weekly_nutrition_constant_targets_and_avg():
    weekly = compute_weekly_nutrition(
        picks=_PICKS, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    )
    # Constant targets (AF-independent).
    assert weekly.protein_g == 146
    assert weekly.fat_g_low == 65
    assert weekly.fat_g_high == 81
    assert weekly.hydration_l_low == 3.0
    assert weekly.hydration_l_high == 3.5
    # avgCaloriesKcal == the §7.1 Target_avg (the week nets to it) — AF=1.50 → 2287.
    expected_avg = _round_half_up(
        deficit_target(
            tdee(
                bmr(weight_kg=_W, height_cm=_ATHLETE.height_cm, age=_ATHLETE.age, sex=_ATHLETE.sex),
                _NUTRITION.activity_factor,
            ),
            _NUTRITION.deficit_pct,
        )
    )
    assert weekly.avg_calories_kcal == expected_avg == 2287


def test_day_type_pattern_agrees_with_daily_focus():
    weekly = compute_weekly_nutrition(
        picks=_PICKS, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    )
    assert len(weekly.day_type_pattern) == 3
    for (suggested_day, dt), entry in zip(_PICKS, weekly.day_type_pattern, strict=True):
        assert isinstance(entry, DayTypePatternEntry)
        assert entry.suggested_day == suggested_day
        assert entry.day_type == dt
        # Each pattern entry's {caloriesKcal, carbsG} equals the matching daily focus.
        focus = compute_macro_focus(
            day_type=dt, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
        )
        assert entry.calories_kcal == focus.calories_kcal
        assert entry.carbs_g == focus.carbs_g


def test_day_type_pattern_helper_matches_selectors():
    pattern = day_type_pattern(_PICKS, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE)
    t = tdee(
        bmr(weight_kg=_W, height_cm=_ATHLETE.height_cm, age=_ATHLETE.age, sex=_ATHLETE.sex),
        _NUTRITION.activity_factor,
    )
    target = deficit_target(t, _NUTRITION.deficit_pct)
    for (suggested_day, dt), entry in zip(_PICKS, pattern, strict=True):
        assert entry.carbs_g == carbs_g(_W, dt, _CARBS)
        assert entry.calories_kcal == calories_kcal(dt, tdee_kcal=t, target_avg_kcal=target)


# --- E13·P1: LastWeekNutrition model + from_adherence mapper + typed last_week ---


def _adherence(
    *,
    kcal_in_n: int,
    protein_in_g_n: int,
    avg_kcal: float | None,
    avg_protein_g: float | None,
    protein_hit_days: int | None = None,
    days_over_target: int | None = None,
    days_under_target: int | None = None,
) -> NutritionAdherence:
    """Build a `NutritionAdherence` for the mapper tests (no DB) — only the fields the
    `from_adherence` null predicate + pass-through read are varied."""
    consumed = NutritionConsumed(
        days=7, kcal_in=0.0, protein_in_g=0.0, carbs_in_g=0.0, fat_in_g=0.0,
        fiber_in_g=0.0, sodium_in_mg=0.0, water_in_l=0.0, n_days=7,
        kcal_in_n=kcal_in_n, protein_in_g_n=protein_in_g_n, carbs_in_g_n=0,
        fat_in_g_n=0, fiber_in_g_n=0, sodium_in_mg_n=0, water_in_l_n=0,
    )
    return NutritionAdherence(
        consumed=consumed, target=None, avg_kcal=avg_kcal, avg_protein_g=avg_protein_g,
        kcal_pct=None, protein_hit_days=protein_hit_days,
        days_over_target=days_over_target, days_under_target=days_under_target,
    )


_LAST_WEEK_KEYS = {
    "avgCaloriesKcal", "avgProteinG", "proteinHitDays", "daysOverTarget", "daysUnderTarget",
}


def test_last_week_nutrition_serialises_camel_keys():
    lw = LastWeekNutrition(
        avg_calories_kcal=2600, avg_protein_g=150,
        protein_hit_days=4, days_over_target=3, days_under_target=1,
    )
    dumped = lw.model_dump(mode="json")
    assert set(dumped) == _LAST_WEEK_KEYS  # exactly the five camelCase keys, no extras
    assert dumped == {
        "avgCaloriesKcal": 2600, "avgProteinG": 150,
        "proteinHitDays": 4, "daysOverTarget": 3, "daysUnderTarget": 1,
    }


def test_last_week_nutrition_rounds_float_averages():
    # Fractional floats round half-up to int (camelCase input) — no ValidationError.
    camel = LastWeekNutrition.model_validate({"avgProteinG": 138.5, "avgCaloriesKcal": 2610.4})
    assert camel.avg_protein_g == 139  # floor(138.5 + 0.5)
    assert camel.avg_calories_kcal == 2610  # floor(2610.4 + 0.5)
    # snake_case input is equally accepted (populate_by_name) and rounded the same.
    snake = LastWeekNutrition.model_validate({"avg_protein_g": 138.5, "avg_calories_kcal": 2610.4})
    assert snake.avg_protein_g == 139
    assert snake.avg_calories_kcal == 2610
    # int / None pass through unchanged.
    passthrough = LastWeekNutrition(avg_protein_g=150, avg_calories_kcal=None)
    assert passthrough.avg_protein_g == 150
    assert passthrough.avg_calories_kcal is None


def test_from_adherence_none_on_no_coverage():
    no_coverage = _adherence(
        kcal_in_n=0, protein_in_g_n=0, avg_kcal=None, avg_protein_g=None
    )
    assert LastWeekNutrition.from_adherence(no_coverage) is None
    assert LastWeekNutrition.from_adherence(None) is None


def test_from_adherence_rounds_and_passes_counts():
    adherence = _adherence(
        kcal_in_n=5, protein_in_g_n=5, avg_kcal=2610.4, avg_protein_g=138.5,
        protein_hit_days=4, days_over_target=3, days_under_target=1,
    )
    lw = LastWeekNutrition.from_adherence(adherence)
    assert lw is not None
    assert lw.avg_calories_kcal == 2610  # float mean rounded
    assert lw.avg_protein_g == 139
    assert lw.protein_hit_days == 4  # counts pass through unchanged
    assert lw.days_over_target == 3
    assert lw.days_under_target == 1


def test_from_adherence_partial_coverage_nulls_missing_average():
    # Protein-only week: calories never logged → avg_calories_kcal stays None (not fabricated).
    protein_only = _adherence(
        kcal_in_n=0, protein_in_g_n=5, avg_kcal=None, avg_protein_g=150.0
    )
    lw = LastWeekNutrition.from_adherence(protein_only)
    assert lw is not None
    assert lw.avg_calories_kcal is None
    assert lw.avg_protein_g == 150  # the logged nutrient is an int


def test_weekly_nutrition_last_week_null_and_object_shapes():
    none_dump = compute_weekly_nutrition(
        picks=_PICKS, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    ).model_dump(mode="json")
    assert none_dump["lastWeek"] is None  # default → lastWeek: null

    lw = LastWeekNutrition(avg_calories_kcal=2600, avg_protein_g=150)
    obj_dump = compute_weekly_nutrition(
        picks=_PICKS, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE, last_week=lw
    ).model_dump(mode="json")
    assert set(obj_dump["lastWeek"]) == _LAST_WEEK_KEYS  # camelCase only, no snake/extra
    assert obj_dump["lastWeek"] == {
        "avgCaloriesKcal": 2600, "avgProteinG": 150,
        "proteinHitDays": None, "daysOverTarget": None, "daysUnderTarget": None,
    }


def _weekly_nutrition_kwargs(**overrides):
    base = dict(
        protein_g=150, fat_g_low=60, fat_g_high=80,
        hydration_l_low=2.5, hydration_l_high=3.5,
        avg_calories_kcal=2600, day_type_pattern=[],
    )
    base.update(overrides)
    return base


def test_weekly_nutrition_adapts_legacy_cached_last_week():
    """Review #1/#2: the read-side adapter on `WeeklyNutrition.last_week` keeps a legacy
    `dataclasses.asdict(NutritionAdherence)` payload contract-correct on the cache-hit path —
    no all-null object, no dropped calorie average."""
    # (a) Legacy no-intake dump → lastWeek collapses to null (never an all-null object).
    no_intake = WeeklyNutrition.model_validate(
        _weekly_nutrition_kwargs(
            last_week={
                "consumed": {"kcal_in_n": 0, "protein_in_g_n": 0},
                "avg_kcal": None, "avg_protein_g": None, "kcal_pct": None,
            }
        )
    )
    assert no_intake.last_week is None
    assert no_intake.model_dump(mode="json")["lastWeek"] is None

    # (b) Legacy calorie-only dump → avg_kcal mapped to avgCaloriesKcal; avgProteinG stays null.
    cal_only = WeeklyNutrition.model_validate(
        _weekly_nutrition_kwargs(
            last_week={
                "consumed": {"kcal_in_n": 5, "protein_in_g_n": 0},
                "avg_kcal": 2610.0, "avg_protein_g": None,
            }
        )
    )
    assert cal_only.model_dump(mode="json")["lastWeek"] == {
        "avgCaloriesKcal": 2610, "avgProteinG": None,
        "proteinHitDays": None, "daysOverTarget": None, "daysUnderTarget": None,
    }

    # (c) Legacy full dump → avg_kcal mapped + both averages rounded; counts pass through.
    full = WeeklyNutrition.model_validate(
        _weekly_nutrition_kwargs(
            last_week={
                "consumed": {"kcal_in_n": 7, "protein_in_g_n": 7},
                "avg_kcal": 2610.0, "avg_protein_g": 138.5,
                "kcal_pct": None, "protein_hit_days": 4,
                "days_over_target": 3, "days_under_target": 1,
            }
        )
    )
    assert full.model_dump(mode="json")["lastWeek"] == {
        "avgCaloriesKcal": 2610, "avgProteinG": 139,
        "proteinHitDays": 4, "daysOverTarget": 3, "daysUnderTarget": 1,
    }

    # (d) A current camelCase dict (no `consumed` key) passes through untranslated.
    current = WeeklyNutrition.model_validate(
        _weekly_nutrition_kwargs(last_week={"avgCaloriesKcal": 2605, "avgProteinG": 144})
    )
    assert current.last_week is not None
    assert current.last_week.avg_calories_kcal == 2605
    assert current.last_week.avg_protein_g == 144


def test_weekly_nutrition_collapses_all_null_last_week():
    """Review #3: an all-null `lastWeek` collapses to None at the validation boundary
    regardless of provenance — the empty-state contract never emits an all-null object."""
    # (a) Current five-key shape, every value null (intermediate-build / cache drift).
    current_all_null = WeeklyNutrition.model_validate(
        _weekly_nutrition_kwargs(
            last_week={
                "avgCaloriesKcal": None, "avgProteinG": None,
                "proteinHitDays": None, "daysOverTarget": None, "daysUnderTarget": None,
            }
        )
    )
    assert current_all_null.last_week is None
    assert current_all_null.model_dump(mode="json")["lastWeek"] is None

    # (b) Legacy row that logged days but had no target (old target-gating left both
    #     averages null despite `kcal_in_n > 0`) → still collapses to the empty state.
    legacy_covered_no_target = WeeklyNutrition.model_validate(
        _weekly_nutrition_kwargs(
            last_week={
                "consumed": {"kcal_in_n": 7, "protein_in_g_n": 7},
                "avg_kcal": None, "avg_protein_g": None, "protein_hit_days": None,
            }
        )
    )
    assert legacy_covered_no_target.last_week is None

    # A LastWeekNutrition instance with one non-null field is NOT collapsed.
    populated = WeeklyNutrition.model_validate(
        _weekly_nutrition_kwargs(last_week=LastWeekNutrition(avg_protein_g=150))
    )
    assert populated.last_week is not None
    assert populated.last_week.avg_protein_g == 150


def test_weekly_nutrition_last_week_passes_through():
    # The field is typed now: a LastWeekNutrition round-trips unchanged (no object() identity).
    lw = LastWeekNutrition(avg_calories_kcal=2600, avg_protein_g=150, protein_hit_days=4)
    weekly = compute_weekly_nutrition(
        picks=_PICKS, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE, last_week=lw
    )
    assert weekly.last_week == lw  # passed through unchanged, not recomputed
    weekly_none = compute_weekly_nutrition(
        picks=_PICKS, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    )
    assert weekly_none.last_week is None  # default → None


# --- E13·P2: per_day_nutrition_target reuses the displayed §7.1 chain ---


def test_per_day_nutrition_target_matches_displayed_targets():
    """The adherence denominator equals the *displayed* targets: kcal is the unrounded
    week-average target `compute_weekly_nutrition` rounds into avgCaloriesKcal, and protein_g
    is the displayed proteinG floor — same weight basis."""
    target = per_day_nutrition_target(weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE)
    raw_kcal = deficit_target(
        tdee(
            bmr(weight_kg=_W, height_cm=_ATHLETE.height_cm, age=_ATHLETE.age, sex=_ATHLETE.sex),
            _NUTRITION.activity_factor,
        ),
        _NUTRITION.deficit_pct,
    )
    assert target.kcal == _round_half_up(raw_kcal)  # rounded to the displayed integer (review #2)
    assert target.protein_g == protein_g(_W, _NUTRITION.protein_g_per_kg)
    # The adherence target is exactly the displayed avgCaloriesKcal/proteinG the user sees —
    # so strict >/< comparisons measure against the shown number, not a sub-kcal remainder.
    displayed = compute_weekly_nutrition(
        picks=_PICKS, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    )
    assert target.kcal == displayed.avg_calories_kcal
    assert target.protein_g == displayed.protein_g


def test_per_day_nutrition_target_leaves_other_fields_none():
    target = per_day_nutrition_target(weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE)
    assert target.carbs_g is None
    assert target.fat_g_low is None
    assert target.fat_g_high is None
    assert target.water_l_low is None
    assert target.water_l_high is None


def test_per_day_nutrition_target_rejects_non_positive_weight():
    with pytest.raises(ValueError, match="weight_kg"):
        per_day_nutrition_target(weight_kg=0.0, nutrition=_NUTRITION, athlete=_ATHLETE)


# --- E13·P4: WeeklyNutrition.restDay (the rest-day cut of the carb cycle) ---


def _t_and_target() -> tuple[float, float]:
    """The in-scope `t`/`target` `compute_weekly_nutrition` derives for the fixture athlete."""
    t = tdee(
        bmr(weight_kg=_W, height_cm=_ATHLETE.height_cm, age=_ATHLETE.age, sex=_ATHLETE.sex),
        _NUTRITION.activity_factor,
    )
    return t, deficit_target(t, _NUTRITION.deficit_pct)


def test_rest_day_matches_rest_selectors():
    weekly = compute_weekly_nutrition(
        picks=_PICKS, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    )
    t, target = _t_and_target()
    assert weekly.rest_day is not None
    # Single-sourced with the per-session selectors: a `rest` dayTypePattern entry would match.
    assert weekly.rest_day.calories_kcal == calories_kcal(
        DayType.rest, tdee_kcal=t, target_avg_kcal=target
    )
    assert weekly.rest_day.carbs_g == carbs_g(_W, DayType.rest, _CARBS)


def test_rest_day_is_below_moderate():
    """The rest-day cut is the deepest level — `rest < moderate` (the carb-cycle visual). Pinned
    at the production sub-cap deficit (0.12) where the ordering is strict (at the 0.20 cap
    calories_kcal makes rest == moderate, the documented relaxed ordering)."""
    weekly = compute_weekly_nutrition(
        picks=_PICKS, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    )
    t, target = _t_and_target()
    moderate_cal = calories_kcal(DayType.moderate, tdee_kcal=t, target_avg_kcal=target)
    moderate_carbs = carbs_g(_W, DayType.moderate, _CARBS)
    assert weekly.rest_day is not None
    assert weekly.rest_day.calories_kcal < moderate_cal
    assert weekly.rest_day.carbs_g < moderate_carbs


def test_weekly_nutrition_restday_serialises_camel_and_optional():
    # Populated → restDay { caloriesKcal, carbsG } in camelCase.
    weekly = compute_weekly_nutrition(
        picks=_PICKS, weight_kg=_W, nutrition=_NUTRITION, athlete=_ATHLETE
    )
    dumped = weekly.model_dump(mode="json")["restDay"]
    assert set(dumped) == {"caloriesKcal", "carbsG"}
    assert isinstance(dumped["caloriesKcal"], int) and isinstance(dumped["carbsG"], int)

    # A direct RestDayNutrition round-trips camelCase.
    assert RestDayNutrition(calories_kcal=2240, carbs_g=180).model_dump(mode="json") == {
        "caloriesKcal": 2240, "carbsG": 180,
    }

    # A legacy cached payload WITHOUT restDay validates (→ rest_day is None), so the cache-hit
    # re-validation path won't 500.
    legacy = {
        "proteinG": 146, "fatGLow": 65, "fatGHigh": 80,
        "hydrationLLow": 3.0, "hydrationLHigh": 3.5,
        "avgCaloriesKcal": 2520, "dayTypePattern": [], "lastWeek": None,
    }
    revalidated = WeeklyNutrition.model_validate(legacy)
    assert revalidated.rest_day is None
    assert revalidated.model_dump(mode="json")["restDay"] is None


# --- DayType is an input, never chosen/floored; the accepted value set is the three ---


def test_day_type_value_set_is_exactly_three():
    assert {d.value for d in DayType} == {"hard", "moderate", "rest"}


# --- Review: non-positive weight fails fast (no silent negative macros) ---


def test_compute_macro_focus_rejects_non_positive_weight():
    # A missing/garbage scale reading must fail fast, not emit negative grams (review).
    for bad in (0.0, -5.0):
        with pytest.raises(ValueError, match="weight_kg must be > 0"):
            compute_macro_focus(
                day_type=DayType.moderate, weight_kg=bad, nutrition=_NUTRITION, athlete=_ATHLETE
            )


def test_compute_weekly_nutrition_rejects_non_positive_weight():
    with pytest.raises(ValueError, match="weight_kg must be > 0"):
        compute_weekly_nutrition(
            picks=_PICKS, weight_kg=0.0, nutrition=_NUTRITION, athlete=_ATHLETE
        )


def test_day_type_pattern_rejects_non_positive_weight():
    with pytest.raises(ValueError, match="weight_kg must be > 0"):
        day_type_pattern(_PICKS, weight_kg=-1.0, nutrition=_NUTRITION, athlete=_ATHLETE)
