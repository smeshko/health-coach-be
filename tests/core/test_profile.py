"""`profile.yaml` typed-loader tests (E3·P1).

`profile.yaml` is the single source of truth for every numeric constant (DB.md §5).
These tests pin the typed model 1:1 to the §5 block: the five sections load and
round-trip, every cap/monotonicity/contiguity rule fails loudly, and **no** live
or derived value (current weight, rolling HRV/RHR baselines, per-day metrics —
those live in `app.db`) is modelled here.
"""

import copy
from datetime import date
from pathlib import Path

import pydantic
import pytest
import yaml

from app.core.profile import (
    PROFILE_PATH,
    Athlete,
    CarbsPerKg,
    Meta,
    Nutrition,
    Profile,
    Thresholds,
    Zones,
    load_profile,
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


# --- TASK-002: loader + cap/monotonicity/contiguity validators ---


def write_yaml(tmp_path: Path, overrides: dict | None = None, *, name: str = "profile.yaml") -> Path:
    """Dump the valid §5 dict (with optional per-section overrides) to a temp file."""
    d = valid_profile_dict()
    for section, patch in (overrides or {}).items():
        if patch is None:
            del d[section]
        else:
            d[section].update(patch)
    path = tmp_path / name
    path.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    return path


def test_load_profile_reads_valid_file(tmp_path):
    p = load_profile(write_yaml(tmp_path))
    assert isinstance(p, Profile)
    assert p.thresholds.max_hr == 192
    assert p.zones.z1 == (96, 125)
    assert p.nutrition.carbs_g_per_kg.hard_low == 4
    assert p.meta.computed_at == date(2026, 6, 2)


def test_load_profile_missing_path_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_profile(tmp_path / "does-not-exist.yaml")


def test_deficit_cap_boundary_inclusive_and_rejects_above(tmp_path):
    # 0.20 accepted (inclusive), 0.25 rejected naming the field.
    load_profile(write_yaml(tmp_path, {"nutrition": {"deficit_pct": 0.20}}))
    with pytest.raises(pydantic.ValidationError) as exc:
        load_profile(write_yaml(tmp_path, {"nutrition": {"deficit_pct": 0.25}}))
    assert "deficit_pct" in str(exc.value)


def test_protein_cap_boundary_inclusive_and_rejects_above(tmp_path):
    load_profile(write_yaml(tmp_path, {"nutrition": {"protein_g_per_kg": 2.0}}))
    with pytest.raises(pydantic.ValidationError) as exc:
        load_profile(write_yaml(tmp_path, {"nutrition": {"protein_g_per_kg": 2.5}}))
    assert "protein_g_per_kg" in str(exc.value)


@pytest.mark.parametrize(
    "bad_zones",
    [
        # z3 low >= high (degenerate zone).
        {"z3": [167, 167]},
        # lows not strictly increasing (z2.low == z1.low).
        {"z1": [96, 125], "z2": [96, 150]},
    ],
)
def test_non_monotonic_zones_rejected(tmp_path, bad_zones):
    with pytest.raises(pydantic.ValidationError):
        load_profile(write_yaml(tmp_path, {"zones": bad_zones}))


def test_non_contiguous_zones_rejected(tmp_path):
    # Monotonic but gapped: z1.high (124) != z2.low (125).
    with pytest.raises(pydantic.ValidationError):
        load_profile(write_yaml(tmp_path, {"zones": {"z1": [96, 124], "z2": [125, 150]}}))


def test_contiguous_zones_accepted(tmp_path):
    # The §5 set is exactly contiguous — it must pass.
    p = load_profile(write_yaml(tmp_path))
    assert p.zones.z1[1] == p.zones.z2[0]


def test_fat_low_greater_than_high_rejected(tmp_path):
    with pytest.raises(pydantic.ValidationError):
        load_profile(
            write_yaml(tmp_path, {"nutrition": {"fat_g_per_kg_low": 1.2, "fat_g_per_kg_high": 1.0}})
        )


def test_max_hr_not_above_rhr_rejected(tmp_path):
    with pytest.raises(pydantic.ValidationError):
        load_profile(write_yaml(tmp_path, {"thresholds": {"max_hr": 50, "rhr_baseline": 58}}))


# A hand-edited single-source-of-truth file must fail loudly on impossible
# values, not just on the upper caps — a negative protein/hydration/fiber/carb
# would otherwise reach the macro engine (PLAN R2). (review round-1 #2)
@pytest.mark.parametrize(
    "patch",
    [
        {"activity_factor": -1.65},
        {"activity_factor": 0},
        {"protein_g_per_kg": -1.8},
        {"protein_g_per_kg": 0},
        {"fat_g_per_kg_low": -0.8},
        {"fat_g_per_kg_high": 0},
        {"hydration_l_low": -3.0},
        {"hydration_l_high": 0},
        {"fiber_g_low": -25},
        {"fiber_g_high": 0},
        {"deficit_pct": -0.05},
    ],
)
def test_negative_or_zero_nutrition_constant_rejected(tmp_path, patch):
    with pytest.raises(pydantic.ValidationError):
        load_profile(write_yaml(tmp_path, {"nutrition": patch}))


@pytest.mark.parametrize(
    "carb_patch",
    [
        {"hard_low": -4},
        {"moderate": 0},
        {"rest_high": -2.5},
    ],
)
def test_negative_or_zero_carb_multiplier_rejected(tmp_path, carb_patch):
    d = valid_profile_dict()
    d["nutrition"]["carbs_g_per_kg"].update(carb_patch)
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    with pytest.raises(pydantic.ValidationError):
        load_profile(path)


def test_hydration_low_above_high_rejected(tmp_path):
    with pytest.raises(pydantic.ValidationError):
        load_profile(write_yaml(tmp_path, {"nutrition": {"hydration_l_low": 3.5, "hydration_l_high": 3.0}}))


def test_fiber_low_above_high_rejected(tmp_path):
    with pytest.raises(pydantic.ValidationError):
        load_profile(write_yaml(tmp_path, {"nutrition": {"fiber_g_low": 35, "fiber_g_high": 25}}))


def test_deficit_pct_zero_accepted(tmp_path):
    # 0% deficit == maintenance, a legitimate floor (the cap is the upper bound).
    p = load_profile(write_yaml(tmp_path, {"nutrition": {"deficit_pct": 0}}))
    assert p.nutrition.deficit_pct == 0


# --- TASK-003: shipped example file + constant accessors ---


def test_shipped_profile_yaml_loads_via_default_path():
    # load_profile() with no arg resolves PROFILE_PATH (the committed §5 example).
    p = load_profile()
    assert isinstance(p, Profile)
    assert p.meta.constitution_version == "v1"


def test_zone_bounds_accessor_returns_db_md_bounds():
    p = load_profile()
    assert p.zone_bounds() == {
        "z1": (96, 125),
        "z2": (125, 150),
        "z3": (150, 167),
        "z4": (167, 177),
        "z5": (177, 192),
    }


def test_nutrition_constants_reachable_for_macro_engine():
    p = load_profile()
    assert p.nutrition.deficit_pct == 0.12
    assert p.nutrition.activity_factor == 1.65
    assert p.nutrition.protein_g_per_kg == 1.8
    assert p.nutrition.carbs_g_per_kg.hard_high == 5


def test_constitution_version_convenience_property():
    p = load_profile()
    assert p.constitution_version == "v1"
    assert p.constitution_version == p.meta.constitution_version


def test_shipped_profile_top_level_keys_equal_the_five_sections():
    # A defaulted top-level field would pass extra="forbid"; assert the shipped
    # file's own top-level keys are exactly the five §5 sections.
    raw = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))
    assert set(raw) == {"athlete", "thresholds", "zones", "nutrition", "meta"}


def test_loaded_profile_exposes_no_live_or_derived_field():
    # Re-assert the static-vs-live guard against the real loaded model.
    p = load_profile()
    for model in (type(p), type(p.athlete), type(p.thresholds), type(p.zones), type(p.nutrition), type(p.meta)):
        assert not (LIVE_DERIVED_NAMES & set(model.model_fields))
