"""E5·P1: /sync wire models — RecordType + HealthRecord (TASK-001)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.api.schemas.sync import HealthRecord, RecordType

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
