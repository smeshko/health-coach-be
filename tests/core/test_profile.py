"""`profile.yaml` typed-loader tests (E3·P1).

`profile.yaml` is the single source of truth for every numeric constant (DB.md §5).
These tests pin the typed model 1:1 to the §5 block: the five sections load and
round-trip, every cap/monotonicity/contiguity rule fails loudly, and **no** live
or derived value (current weight, rolling HRV/RHR baselines, per-day metrics —
those live in `app.db`) is modelled here.
"""

import copy
from datetime import date

import pydantic
import pytest

from app.core.profile import (
    Athlete,
    CarbsPerKg,
    Meta,
    Nutrition,
    Profile,
    Thresholds,
    Zones,
)

# The DB.md §5 example block, as a plain dict — the known-valid baseline every
# negative case mutates from.
VALID_PROFILE: dict = {
    "athlete": {"age": 34, "sex": "male", "height_cm": 174, "goal_weight_kg": 75},
    "thresholds": {
        "max_hr": 192,
        "rhr_baseline": 58,
        "hrv_baseline_ms": 38,
        "easy_hr_cap": 146,
        "cadence_target_spm": 172,
        "cadence_current_spm": 160,
    },
    "zones": {
        "z1": [96, 125],
        "z2": [125, 150],
        "z3": [150, 167],
        "z4": [167, 177],
        "z5": [177, 192],
    },
    "nutrition": {
        "activity_factor": 1.65,
        "deficit_pct": 0.12,
        "protein_g_per_kg": 1.8,
        "fat_g_per_kg_low": 0.8,
        "fat_g_per_kg_high": 1.0,
        "carbs_g_per_kg": {
            "hard_low": 4,
            "hard_high": 5,
            "moderate": 3,
            "rest_low": 2,
            "rest_high": 2.5,
        },
        "hydration_l_low": 3.0,
        "hydration_l_high": 3.5,
        "fiber_g_low": 25,
        "fiber_g_high": 35,
    },
    "meta": {
        "derived_from": "baseline.db",
        "computed_at": date(2026, 6, 2),
        "constitution_version": "v1",
    },
}


def valid_profile_dict() -> dict:
    """A fresh deep copy of the valid §5 block, safe to mutate per test."""
    return copy.deepcopy(VALID_PROFILE)


# --- TASK-001: structure, round-trip, extra-forbid, static-vs-live ---


def test_valid_dict_constructs_and_round_trips():
    p = Profile(**valid_profile_dict())
    assert p.athlete.age == 34
    assert p.athlete.sex == "male"
    assert p.thresholds.max_hr == 192
    assert p.thresholds.cadence_current_spm == 160
    assert p.zones.z1 == (96, 125)
    assert p.zones.z5 == (177, 192)
    assert p.nutrition.activity_factor == 1.65
    assert p.nutrition.carbs_g_per_kg.hard_low == 4
    assert p.nutrition.carbs_g_per_kg.rest_high == 2.5
    assert p.meta.computed_at == date(2026, 6, 2)
    assert p.meta.constitution_version == "v1"


def test_missing_carb_multiplier_raises():
    d = valid_profile_dict()
    del d["nutrition"]["carbs_g_per_kg"]["rest_high"]
    with pytest.raises(pydantic.ValidationError) as exc:
        Profile(**d)
    assert "rest_high" in str(exc.value)


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("athlete", "weight_kg"),
        ("thresholds", "lthr"),
        ("zones", "z6"),
        ("nutrition", "sodium_g"),
        ("meta", "author"),
    ],
)
def test_unknown_key_in_any_section_rejected(section, key):
    d = valid_profile_dict()
    d[section][key] = 1
    with pytest.raises(pydantic.ValidationError):
        Profile(**d)


def test_stray_carb_key_rejected():
    d = valid_profile_dict()
    d["nutrition"]["carbs_g_per_kg"]["extra_day"] = 9
    with pytest.raises(pydantic.ValidationError):
        Profile(**d)


@pytest.mark.parametrize("section", ["athlete", "thresholds", "zones", "nutrition", "meta"])
def test_missing_section_raises(section):
    d = valid_profile_dict()
    del d[section]
    with pytest.raises(pydantic.ValidationError):
        Profile(**d)


# A defaulted field for a live/derived value would silently pass `extra="forbid"`
# (it never appears in input YAML), so guard the exact key set of every section.
EXPECTED_KEYS = {
    Athlete: {"age", "sex", "height_cm", "goal_weight_kg"},
    Thresholds: {
        "max_hr",
        "rhr_baseline",
        "hrv_baseline_ms",
        "easy_hr_cap",
        "cadence_target_spm",
        "cadence_current_spm",
    },
    Zones: {"z1", "z2", "z3", "z4", "z5"},
    Nutrition: {
        "activity_factor",
        "deficit_pct",
        "protein_g_per_kg",
        "fat_g_per_kg_low",
        "fat_g_per_kg_high",
        "carbs_g_per_kg",
        "hydration_l_low",
        "hydration_l_high",
        "fiber_g_low",
        "fiber_g_high",
    },
    CarbsPerKg: {"hard_low", "hard_high", "moderate", "rest_low", "rest_high"},
    Meta: {"derived_from", "computed_at", "constitution_version"},
}

# Names of live/derived values that must NEVER be modelled here — they live in
# app.db (daily_metrics), not profile.yaml (DB.md §5 table + footnote ¹).
LIVE_DERIVED_NAMES = frozenset(
    {
        "body_weight",
        "current_weight",
        "weight",
        "hrv_30d",
        "hrv_30d_mean",
        "hrv_30d_sd",
        "rhr_30d",
        "rhr_30d_mean",
        "readiness",
        "readiness_score",
        "sleep_h",
        "band",
    }
)


@pytest.mark.parametrize(("model", "expected"), list(EXPECTED_KEYS.items()))
def test_section_keyset_exactly_matches_db_md(model, expected):
    assert set(model.model_fields) == expected


def test_root_profile_keyset_is_the_five_sections():
    assert set(Profile.model_fields) == {"athlete", "thresholds", "zones", "nutrition", "meta"}


def test_no_live_or_derived_field_is_modelled():
    for model in (Profile, Athlete, Thresholds, Zones, Nutrition, CarbsPerKg, Meta):
        leaked = LIVE_DERIVED_NAMES & set(model.model_fields)
        assert not leaked, f"{model.__name__} leaks live/derived field(s): {leaked}"
