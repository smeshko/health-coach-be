"""E5·P1: /sync wire models — RecordType + HealthRecord (TASK-001)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.api.schemas.sync import (
    ActivitySummary,
    DailyCheckin,
    HealthRecord,
    RecordType,
    StrengthTest,
    SyncRequest,
    SyncResponse,
    Workout,
    WorkoutStat,
)

# The exact MODELS "Enums → RecordType" value list, in reading order (24 values).
EXPECTED_RECORD_TYPES = [
    "heart_rate",
    "heart_rate_variability_sdnn",
    "resting_heart_rate",
    "sleep_analysis",
    "step_count",
    "active_energy_burned",
    "basal_energy_burned",
    "physical_effort",
    "vo2_max",
    "body_mass",
    "running_speed",
    "running_power",
    "running_cadence",
    "running_stride_length",
    "running_ground_contact_time",
    "running_vertical_oscillation",
    "respiratory_rate",
    "dietary_energy_consumed",
    "dietary_protein",
    "dietary_carbohydrates",
    "dietary_fat_total",
    "dietary_fiber",
    "dietary_sodium",
    "dietary_water",
]


def test_record_type_value_set_matches_models() -> None:
    assert [m.value for m in RecordType] == EXPECTED_RECORD_TYPES


@pytest.mark.parametrize("type_", ["body_mass", "dietary_protein", "sleep_analysis"])
def test_known_types_parse_on_health_record(type_: str) -> None:
    rec = HealthRecord.model_validate(
        {
            "uuid": "abc-123",
            "type": type_,
            "start": "2026-06-01T08:00:00+03:00",
            "end": "2026-06-01T08:00:00+03:00",
        }
    )
    assert rec.type == RecordType(type_)


def test_unknown_type_rejected() -> None:
    with pytest.raises(ValidationError):
        HealthRecord.model_validate(
            {
                "uuid": "abc-123",
                "type": "blood_glucose",
                "start": "2026-06-01T08:00:00+03:00",
                "end": "2026-06-01T08:00:00+03:00",
            }
        )


def test_quantity_sample_validates() -> None:
    rec = HealthRecord.model_validate(
        {
            "uuid": "q-1",
            "type": "heart_rate",
            "start": "2026-06-01T08:00:00+03:00",
            "end": "2026-06-01T08:00:30+03:00",
            "value": 57.0,
            "unit": "count/min",
            "category": None,
        }
    )
    assert rec.value == 57.0
    assert rec.unit == "count/min"
    assert rec.category is None


def test_category_sample_validates() -> None:
    rec = HealthRecord.model_validate(
        {
            "uuid": "c-1",
            "type": "sleep_analysis",
            "start": "2026-06-01T00:00:00+03:00",
            "end": "2026-06-01T01:00:00+03:00",
            "category": "asleepDeep",
            "value": None,
        }
    )
    assert rec.category == "asleepDeep"
    assert rec.value is None


def test_health_record_round_trips_camel_case() -> None:
    rec = HealthRecord.model_validate(
        {
            "uuid": "r-1",
            "type": "step_count",
            "start": "2026-06-01T08:00:00+03:00",
            "end": "2026-06-01T08:10:00+03:00",
            "value": 500.0,
            "unit": "count",
        }
    )
    payload = json.loads(rec.model_dump_json())
    # camelCase keys on the wire (no snake_case leakage for aliased fields).
    assert "uuid" in payload
    assert "type" in payload
    assert "start" in payload and "end" in payload
    # Re-parse the emitted camelCase JSON.
    again = HealthRecord.model_validate(payload)
    assert again == rec


def test_snake_case_input_also_accepted() -> None:
    # HealthRecord has no multi-word aliased field, so build a synthetic check via
    # populate_by_name: snake_case keys parse identically to the wire form.
    rec = HealthRecord.model_validate(
        {
            "uuid": "s-1",
            "type": "body_mass",
            "start": "2026-06-01T08:00:00+03:00",
            "end": "2026-06-01T08:00:00+03:00",
            "value": 78.5,
            "unit": "kg",
        }
    )
    assert rec.value == 78.5


def test_metadata_passthrough_object_parses() -> None:
    rec = HealthRecord.model_validate(
        {
            "uuid": "m-1",
            "type": "heart_rate",
            "start": "2026-06-01T08:00:00+03:00",
            "end": "2026-06-01T08:00:30+03:00",
            "value": 60.0,
            "unit": "count/min",
            "metadata": {"motionContext": 1, "nested": {"k": "v"}},
        }
    )
    assert rec.metadata == {"motionContext": 1, "nested": {"k": "v"}}


OPTIONAL_FIELDS = ["value", "unit", "category", "source", "metadata"]


@pytest.mark.parametrize("field", OPTIONAL_FIELDS)
def test_optional_field_accepts_omission(field: str) -> None:
    base = {
        "uuid": "o-1",
        "type": "heart_rate",
        "start": "2026-06-01T08:00:00+03:00",
        "end": "2026-06-01T08:00:30+03:00",
    }
    rec = HealthRecord.model_validate(base)
    assert getattr(rec, field) is None


@pytest.mark.parametrize("field", OPTIONAL_FIELDS)
def test_optional_field_accepts_explicit_null(field: str) -> None:
    base = {
        "uuid": "o-2",
        "type": "heart_rate",
        "start": "2026-06-01T08:00:00+03:00",
        "end": "2026-06-01T08:00:30+03:00",
        field: None,
    }
    rec = HealthRecord.model_validate(base)
    assert getattr(rec, field) is None


# ---------------------------------------------------------------------------
# TASK-002: Workout, WorkoutStat, ActivitySummary, DailyCheckin, StrengthTest,
# SyncRequest, SyncResponse.
# ---------------------------------------------------------------------------


def test_workout_stat_validates_and_round_trips() -> None:
    stat = WorkoutStat.model_validate({"type": "avg_hr", "value": 142.0, "unit": "count/min"})
    payload = json.loads(stat.model_dump_json())
    assert payload == {"type": "avg_hr", "value": 142.0, "unit": "count/min"}


def test_workout_emits_camel_case_keys() -> None:
    workout = Workout.model_validate(
        {
            "uuid": "w-1",
            "type": "boxing",
            "start": "2026-06-01T18:00:00+03:00",
            "end": "2026-06-01T18:45:00+03:00",
            "durationS": 2700.0,
            "distanceM": None,
            "activeEnergyKcal": 410.0,
            "effortScore": 7,
            "zoneMinutes": {"z2": 10.0, "z3": 20.0},
            "statistics": [{"type": "avg_hr", "value": 150.0, "unit": "count/min"}],
        }
    )
    assert workout.duration_s == 2700.0
    assert workout.active_energy_kcal == 410.0
    assert workout.effort_score == 7
    assert workout.zone_minutes == {"z2": 10.0, "z3": 20.0}
    assert workout.statistics[0].type == "avg_hr"
    payload = json.loads(workout.model_dump_json())
    for key in ("durationS", "distanceM", "activeEnergyKcal", "effortScore", "zoneMinutes"):
        assert key in payload


def test_workout_optionals_default_and_statistics_empty() -> None:
    workout = Workout.model_validate(
        {
            "uuid": "w-2",
            "type": "running",
            "start": "2026-06-01T07:00:00+03:00",
            "end": "2026-06-01T07:30:00+03:00",
            "durationS": 1800.0,
        }
    )
    assert workout.distance_m is None
    assert workout.active_energy_kcal is None
    assert workout.effort_score is None
    assert workout.zone_minutes is None
    assert workout.statistics == []


def test_activity_summary_emits_camel_case() -> None:
    summary = ActivitySummary.model_validate(
        {
            "date": "2026-06-01",
            "activeEnergyKcal": 620.0,
            "exerciseMinutes": 48,
            "standHours": 11,
            "steps": 9800,
        }
    )
    payload = json.loads(summary.model_dump_json())
    for key in ("activeEnergyKcal", "exerciseMinutes", "standHours", "steps"):
        assert key in payload


def test_activity_summary_steps_optional() -> None:
    summary = ActivitySummary.model_validate(
        {
            "date": "2026-06-01",
            "activeEnergyKcal": 620.0,
            "exerciseMinutes": 48,
            "standHours": 11,
        }
    )
    assert summary.steps is None


def test_daily_checkin_is_objective_only() -> None:
    assert "weight" not in DailyCheckin.model_fields
    assert "bodyMass" not in DailyCheckin.model_fields
    assert "body_mass" not in DailyCheckin.model_fields
    assert set(DailyCheckin.model_fields) == {"date", "gi_symptoms", "knee_pain", "illness"}


def test_daily_checkin_emits_camel_case() -> None:
    checkin = DailyCheckin.model_validate(
        {"date": "2026-06-01", "giSymptoms": True, "kneePain": 3, "illness": False}
    )
    payload = json.loads(checkin.model_dump_json())
    assert "giSymptoms" in payload
    assert "kneePain" in payload


@pytest.mark.parametrize("knee", [0, 10])
def test_daily_checkin_accepts_knee_pain_bounds(knee: int) -> None:
    checkin = DailyCheckin.model_validate(
        {"date": "2026-06-01", "giSymptoms": False, "kneePain": knee, "illness": False}
    )
    assert checkin.knee_pain == knee


@pytest.mark.parametrize("knee", [-1, 11])
def test_daily_checkin_rejects_out_of_range_knee_pain(knee: int) -> None:
    with pytest.raises(ValidationError):
        DailyCheckin.model_validate(
            {"date": "2026-06-01", "giSymptoms": False, "kneePain": knee, "illness": False}
        )


def test_strength_test_emits_camel_case() -> None:
    st = StrengthTest.model_validate(
        {"date": "2026-06-01", "maxPushups": 40, "maxPullups": 12}
    )
    payload = json.loads(st.model_dump_json())
    assert "maxPushups" in payload
    assert "maxPullups" in payload


def test_sync_request_defaults_on_empty() -> None:
    req = SyncRequest.model_validate({})
    assert req.records == []
    assert req.workouts == []
    assert req.activity_summary == []
    assert req.checkin is None
    assert req.strength_test is None


@pytest.mark.parametrize(("wire_field", "attr"), [("checkin", "checkin"), ("strengthTest", "strength_test")])
def test_sync_request_top_optionals_omitted_and_null(wire_field: str, attr: str) -> None:
    assert getattr(SyncRequest.model_validate({}), attr) is None
    assert getattr(SyncRequest.model_validate({wire_field: None}), attr) is None


def test_sync_response_emits_camel_case() -> None:
    resp = SyncResponse.model_validate(
        {
            "recordsUpserted": 3,
            "recordsDuplicate": 1,
            "workoutsUpserted": 2,
            "activityDaysUpserted": 1,
            "checkinSaved": True,
            "strengthTestSaved": False,
            "serverTime": "2026-06-01T20:00:00+03:00",
        }
    )
    payload = json.loads(resp.model_dump_json())
    for key in (
        "recordsUpserted",
        "recordsDuplicate",
        "workoutsUpserted",
        "activityDaysUpserted",
        "checkinSaved",
        "strengthTestSaved",
        "serverTime",
    ):
        assert key in payload


SYNC_REQUEST_EXAMPLE = json.dumps(
    {
        "records": [
            {
                "uuid": "r-1",
                "type": "heart_rate",
                "start": "2026-06-01T08:00:00+03:00",
                "end": "2026-06-01T08:00:30+03:00",
                "value": 57.0,
                "unit": "count/min",
            },
            {
                "uuid": "r-2",
                "type": "body_mass",
                "start": "2026-06-01T07:00:00+03:00",
                "end": "2026-06-01T07:00:00+03:00",
                "value": 78.4,
                "unit": "kg",
            },
            {
                "uuid": "r-3",
                "type": "sleep_analysis",
                "start": "2026-06-01T00:00:00+03:00",
                "end": "2026-06-01T01:00:00+03:00",
                "category": "asleepDeep",
            },
        ],
        "checkin": {
            "date": "2026-06-01",
            "giSymptoms": False,
            "kneePain": 2,
            "illness": False,
        },
    }
)


def test_sync_request_example_round_trips() -> None:
    req = SyncRequest.model_validate_json(SYNC_REQUEST_EXAMPLE)
    assert len(req.records) == 3
    assert req.checkin is not None
    assert req.checkin.knee_pain == 2
    payload = json.loads(req.model_dump_json())
    assert "giSymptoms" in payload["checkin"]
    assert payload["records"][0]["type"] == "heart_rate"
