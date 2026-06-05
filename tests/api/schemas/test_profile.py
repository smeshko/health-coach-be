"""E14·P1 TASK-001: ProfileResponse wire-schema tests — pure model serialisation, no app/DB.

Pins the camelCase contract (the core Athlete/Thresholds/Meta are snake_case BaseModels, so the
CamelModel sub-models are what produce the wire shape) and the zone `{low, high}` ranges.
"""

from __future__ import annotations

import json

from app.api.schemas.profile import (
    AthleteOut,
    MetaOut,
    ProfileResponse,
    ThresholdsOut,
    ZoneRange,
    ZonesOut,
)
from app.core.profile import load_profile


def _zone(lo: int, hi: int) -> ZoneRange:
    return ZoneRange(low=lo, high=hi)


def _profile_response() -> ProfileResponse:
    return ProfileResponse(
        athlete=AthleteOut(age=34, sex="male", height_cm=174, goal_weight_kg=75.0),
        zones=ZonesOut(
            z1=_zone(96, 133), z2=_zone(134, 152), z3=_zone(153, 171),
            z4=_zone(172, 190), z5=_zone(191, 202),
        ),
        thresholds=ThresholdsOut(
            max_hr=202, rhr_baseline=48, hrv_baseline_ms=65, easy_hr_cap=152,
            cadence_current_spm=170, cadence_target_spm=180,
        ),
        meta=MetaOut(constitution_version="2026.1", constants_recomputed_week="2026-W23"),
    )


def test_profile_response_camel_keys():
    dumped = _profile_response().model_dump(mode="json")
    assert set(dumped) == {"athlete", "zones", "thresholds", "meta"}
    assert set(dumped["athlete"]) == {"age", "sex", "heightCm", "goalWeightKg"}
    assert set(dumped["thresholds"]) == {
        "maxHr", "rhrBaseline", "hrvBaselineMs", "easyHrCap",
        "cadenceCurrentSpm", "cadenceTargetSpm",
    }
    assert set(dumped["meta"]) == {"constitutionVersion", "constantsRecomputedWeek"}
    assert set(dumped["zones"]) == {"z1", "z2", "z3", "z4", "z5"}


def test_zone_range_serialises_low_high():
    dumped = _profile_response().model_dump(mode="json")
    assert dumped["zones"]["z4"] == {"low": 172, "high": 190}
    assert dumped["zones"]["z5"] == {"low": 191, "high": 202}


def test_out_models_validate_from_core_models():
    """The Out sub-models read the snake_case core models by attribute (from_attributes)."""
    profile = load_profile()
    athlete = AthleteOut.model_validate(profile.athlete)
    assert athlete.age == profile.athlete.age
    assert athlete.height_cm == profile.athlete.height_cm
    assert athlete.goal_weight_kg == profile.athlete.goal_weight_kg
    thresholds = ThresholdsOut.model_validate(profile.thresholds)
    assert thresholds.max_hr == profile.thresholds.max_hr
    assert thresholds.cadence_current_spm == profile.thresholds.cadence_current_spm
    meta = MetaOut.model_validate(profile.meta)
    assert meta.constitution_version == profile.meta.constitution_version


def test_meta_out_omits_internal_fields():
    """The internal provenance (`derived_from`/`computed_at`) is not on the wire."""
    dumped = MetaOut.model_validate(load_profile().meta).model_dump(mode="json")
    assert set(dumped) == {"constitutionVersion", "constantsRecomputedWeek"}
    for internal in ("derivedFrom", "computedAt", "derived_from", "computed_at"):
        assert internal not in dumped


def test_profile_response_has_no_nutrition_or_weight_fields():
    blob = json.dumps(_profile_response().model_dump(mode="json"))
    for forbidden in (
        "activityFactor", "deficitPct", "proteinGPerKg",
        "bodyWeight", "currentWeight", "restDay", "lastWeek",
    ):
        assert forbidden not in blob
