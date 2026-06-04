"""Unit tests for the card-system enums (E7·P1 TASK-001).

Each enum's `.value` set is asserted **equal** to the MODELS § Enums value set
verbatim; `WorkoutCard` must have exactly the 20 documented cards; members are
`str`-subclassed and round-trip. `RecordType` is owned by E5 and must NOT ship
from `app.core.enums` (a forward dependency, not merged in this checkout).
"""

import app.core.enums as enums_module
from app.core.enums import (
    DayType,
    Intensity,
    NarrativeType,
    Tier,
    Weekday,
    WorkoutCard,
    Zone,
)

# The 20 documented WorkoutCard keys, verbatim from MODELS § Enums.
WORKOUT_CARD_VALUES = {
    "easy_run",
    "long_run",
    "progression_run",
    "active_recovery",
    "threshold",
    "vo2",
    "strides",
    "hiit",
    "jump_rope",
    "steady_cardio",
    "strength_push",
    "strength_pull",
    "strength_lower",
    "strength_full",
    "boxing",
    "boxing_technique",
    "foot_prehab",
    "glute_prehab",
    "mobility",
    "rest",
}


def test_zone_value_set_matches_models():
    assert {z.value for z in Zone} == {"z1", "z2", "z3", "z4", "z5"}


def test_intensity_value_set_matches_models():
    assert {i.value for i in Intensity} == {"easy", "quality", "recovery"}


def test_day_type_value_set_matches_models():
    assert {d.value for d in DayType} == {"hard", "moderate", "rest"}


def test_tier_value_set_matches_models():
    # MODELS uses singular `extra`, not `extras`.
    assert {t.value for t in Tier} == {"core", "extra"}


def test_weekday_value_set_matches_models():
    assert {w.value for w in Weekday} == {
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
    }


def test_narrative_type_value_set_matches_models():
    assert {n.value for n in NarrativeType} == {
        "summary",
        "session",
        "nutrition",
        "caution",
        "plan",
    }


def test_workout_card_value_set_matches_models():
    assert {c.value for c in WorkoutCard} == WORKOUT_CARD_VALUES


def test_workout_card_has_exactly_twenty_members():
    assert len(WorkoutCard) == 20


def test_workout_card_round_trips():
    assert WorkoutCard("vo2") is WorkoutCard.vo2
    assert WorkoutCard("easy_run") is WorkoutCard.easy_run


def test_zone_round_trips():
    assert Zone("z4") is Zone.z4


def test_enums_are_str_subclassed():
    assert WorkoutCard.easy_run == "easy_run"
    assert isinstance(WorkoutCard.easy_run, str)
    assert Zone.z2 == "z2"
    assert isinstance(Zone.z2, str)
    assert Tier.extra == "extra"
    assert isinstance(Intensity.quality, str)


def test_record_type_is_not_defined_here():
    # RecordType is owned by E5 (a forward dependency, not merged in this
    # checkout). This module must ship none — we do NOT assert E5 has one.
    assert not hasattr(enums_module, "RecordType")
