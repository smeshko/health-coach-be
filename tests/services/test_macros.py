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
from app.core.profile import CarbsPerKg
from app.services.macros import (
    BMR_SEX_CONSTANT,
    MAX_DEFICIT_PCT,
    MAX_PROTEIN_G_PER_KG,
    REST_DEFICIT_PCT,
    _round_half_up,
    bmr,
    calories_kcal,
    carbs_g,
    clamp_deficit,
    deficit_target,
    fat_g_range,
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
