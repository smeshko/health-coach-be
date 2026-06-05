"""Pure model tests for the weekly LLM output contract (E10·P1 TASK-001).

No LLM, no network: these exercise the strict, slim `WeeklyPlanLLMOutput` /
`PlannedPick` / `NarrativeSection` shapes — the MODELS field tables, the
camelCase wire round-trip via `CamelModel`, nullable `suggestedDay`/dose, and the
absence of any card-derived/computed field (derive-don't-emit; MODELS rule 2).
"""

import json

from app.api.schemas.weekly import (
    NarrativeSection,
    PlannedPick,
    WeeklyPlanLLMOutput,
)
from app.core.enums import NarrativeType, Weekday, WorkoutCard

# The MODELS WeeklyPlanLLMOutput example (camelCase wire JSON), verbatim.
_MODELS_EXAMPLE = {
    "core": [
        {"card": "boxing", "suggestedDay": "tue", "durationMinLow": 60, "durationMinHigh": 90},
        {"card": "vo2", "suggestedDay": "fri", "durationMinLow": 30, "durationMinHigh": 40},
        {"card": "strength_pull", "suggestedDay": "mon", "durationMinLow": 30, "durationMinHigh": 45},
    ],
    "extras": [
        {"card": "easy_run", "suggestedDay": "wed", "durationMinLow": 30, "durationMinHigh": 40},
    ],
    "narrative": [
        {"type": "plan", "heading": "Two hard days around boxing", "body": "Boxing and VO2 are the quality days."},
        {"type": "session", "heading": "VO2 intervals", "body": "5 x 3 min at Z5."},
        {"type": "nutrition", "heading": "Fuel the hard days", "body": "Carb-load Tue and Fri."},
    ],
}


# --- field-set / shape invariants ---------------------------------------------


def test_weekly_output_model_fields_are_exactly_core_extras_narrative():
    assert set(WeeklyPlanLLMOutput.model_fields) == {"core", "extras", "narrative"}


def test_planned_pick_model_fields_are_the_four_slim_llm_fields():
    assert set(PlannedPick.model_fields) == {
        "card",
        "suggested_day",
        "duration_min_low",
        "duration_min_high",
    }


def test_planned_pick_has_no_card_derived_field():
    fields = set(PlannedPick.model_fields)
    for derived in ("tier", "intensity", "zone_target", "is_hard_day", "flags"):
        assert derived not in fields


def test_weekly_output_has_no_targets_nutrition_or_budgets_field():
    fields = set(WeeklyPlanLLMOutput.model_fields)
    for computed in ("targets", "nutrition", "budgets"):
        assert computed not in fields


def test_narrative_section_model_fields_are_type_heading_body():
    assert set(NarrativeSection.model_fields) == {"type", "heading", "body"}


def test_narrative_section_type_is_the_enum():
    section = NarrativeSection(type="plan", heading="h", body="b")
    assert section.type is NarrativeType.plan


# --- subclassing + enum reuse -------------------------------------------------


def test_models_subclass_camel_model():
    from app.api.schemas.base import CamelModel

    assert issubclass(WeeklyPlanLLMOutput, CamelModel)
    assert issubclass(PlannedPick, CamelModel)
    assert issubclass(NarrativeSection, CamelModel)


def test_planned_pick_uses_e7p1_enums():
    pick = PlannedPick(card="vo2", suggested_day="fri")
    assert pick.card is WorkoutCard.vo2
    assert pick.suggested_day is Weekday.fri


# --- nullable suggestedDay / dose ---------------------------------------------


def test_suggested_day_and_dose_are_nullable_and_omittable():
    # Omitted entirely.
    pick = PlannedPick(card="rest")
    assert pick.suggested_day is None
    assert pick.duration_min_low is None
    assert pick.duration_min_high is None
    # Explicit null on the wire.
    pick2 = PlannedPick.model_validate(
        {"card": "easy_run", "suggestedDay": None, "durationMinLow": None, "durationMinHigh": None}
    )
    assert pick2.suggested_day is None
    assert pick2.duration_min_low is None


# --- camelCase round-trip -----------------------------------------------------


def test_models_example_json_round_trips_with_camelcase():
    out = WeeklyPlanLLMOutput.model_validate(_MODELS_EXAMPLE)
    assert len(out.core) == 3
    assert len(out.extras) == 1
    assert out.core[0].card is WorkoutCard.boxing
    assert out.core[0].suggested_day is Weekday.tue
    assert out.core[0].duration_min_low == 60
    assert out.narrative[0].type is NarrativeType.plan

    # model_dump_json emits camelCase (CamelModel serialize_by_alias=True).
    dumped = json.loads(out.model_dump_json())
    assert dumped["core"][0]["suggestedDay"] == "tue"
    assert dumped["core"][0]["durationMinLow"] == 60
    assert dumped["core"][0]["durationMinHigh"] == 90
    assert dumped["narrative"][0]["type"] == "plan"
    # Re-validate the dumped camelCase JSON — a clean round-trip.
    again = WeeklyPlanLLMOutput.model_validate(dumped)
    assert again == out


def test_card_and_type_accept_enum_values():
    out = WeeklyPlanLLMOutput.model_validate(_MODELS_EXAMPLE)
    assert {p.card for p in out.core} == {
        WorkoutCard.boxing,
        WorkoutCard.vo2,
        WorkoutCard.strength_pull,
    }
