"""Pure model tests for the daily LLM output contract (E11·P1 TASK-001).

No LLM, no network — just the slim `DailyBriefLLMOutput` / `SessionPick` wire
shapes (MODELS `DailyBriefLLMOutput`/`SessionPick`; LLM §1) and the **one shared**
`NarrativeSection`. The `alternatives` ≤ 2 cap, the `dayType` fuel-floor, and the
daily narrative subset are validator rules (TASK-003), **not** Pydantic
constraints — so the types here stay permissive.
"""

import json

from app.api.schemas import daily, weekly
from app.api.schemas.daily import DailyBriefLLMOutput, NarrativeSection, SessionPick
from app.core.enums import DayType, NarrativeType, WorkoutCard


def _example() -> dict:
    """A MODELS-shaped daily output in camelCase (the wire form)."""
    return {
        "session": {"card": "vo2", "durationMinLow": 30, "durationMinHigh": 40},
        "alternatives": [
            {"card": "easy_run", "durationMinLow": 30, "durationMinHigh": 45},
        ],
        "skipOk": False,
        "dayType": "hard",
        "narrative": [
            {"type": "session", "heading": "Today", "body": "VO2 intervals."},
        ],
    }


def test_daily_brief_llm_output_model_fields_are_exactly_the_slim_set():
    assert set(DailyBriefLLMOutput.model_fields) == {
        "session",
        "alternatives",
        "skip_ok",
        "day_type",
        "narrative",
    }


def test_session_pick_model_fields_are_exactly_the_three_llm_fields():
    # Slim by design — no card-derived field, no `suggestedDay` (a weekly field).
    assert set(SessionPick.model_fields) == {
        "card",
        "duration_min_low",
        "duration_min_high",
    }


def test_session_pick_has_no_derived_or_suggested_day_field():
    for stray in (
        "intensity",
        "zone_target",
        "hr_cap_bpm",
        "cadence_spm",
        "flags",
        "suggested_day",
    ):
        assert stray not in SessionPick.model_fields


def test_daily_brief_has_no_readiness_or_merged_field():
    for stray in ("readiness", "safety_gate", "macro_focus", "intake_yesterday"):
        assert stray not in DailyBriefLLMOutput.model_fields


def test_day_type_is_an_emitted_daytype_not_predefaulted():
    field = DailyBriefLLMOutput.model_fields["day_type"]
    assert field.annotation is DayType
    # Not pre-defaulted to a card value — the model must pick (the floor is a
    # validator rule, TASK-003).
    assert field.is_required()


def test_skip_ok_is_a_bool():
    assert DailyBriefLLMOutput.model_fields["skip_ok"].annotation is bool


def test_narrative_section_is_the_one_shared_class():
    # The SAME class object as the weekly output's — re-homed, not duplicated.
    assert daily.NarrativeSection is weekly.NarrativeSection
    assert set(NarrativeSection.model_fields) == {"type", "heading", "body"}
    assert NarrativeSection.model_fields["type"].annotation is NarrativeType


def test_models_example_round_trips_with_camelcase():
    data = _example()
    out = DailyBriefLLMOutput.model_validate(data)
    assert out.session.card is WorkoutCard.vo2
    assert out.day_type is DayType.hard
    assert out.skip_ok is False
    # `serialize_by_alias` → raw dump is camelCase and round-trips byte-for-byte.
    assert json.loads(out.model_dump_json()) == data


def test_dose_is_nullable_and_omittable():
    pick = SessionPick.model_validate({"card": "rest"})
    assert pick.duration_min_low is None
    assert pick.duration_min_high is None
    pick2 = SessionPick.model_validate(
        {"card": "rest", "durationMinLow": None, "durationMinHigh": None}
    )
    assert pick2.duration_min_high is None


def test_alternatives_list_is_permissive_three_is_allowed_by_the_type():
    # The ≤ 2 cap is a validator rule (TASK-003), NOT a Pydantic max_length — three
    # alternatives parse fine here and are gated downstream with a ModelRetry.
    data = _example()
    data["alternatives"] = [
        {"card": "easy_run", "durationMinLow": 30, "durationMinHigh": 45},
        {"card": "mobility", "durationMinLow": 15, "durationMinHigh": 30},
        {"card": "rest"},
    ]
    out = DailyBriefLLMOutput.model_validate(data)
    assert len(out.alternatives) == 3


def test_plan_narrative_section_parses_subset_enforced_by_validator():
    # `plan` is a valid NarrativeType, so it parses — the daily-subset exclusion is
    # a validator rule (TASK-003), not a type Literal.
    data = _example()
    data["narrative"] = [{"type": "plan", "heading": "W", "body": "weekly-only kind"}]
    out = DailyBriefLLMOutput.model_validate(data)
    assert out.narrative[0].type is NarrativeType.plan
