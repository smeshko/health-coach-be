"""`expand_plan_pick`/`expand_plan` — the weekly expander (E7·P2 TASK-003).

Pure unit tests with an injected `Profile`: every code-derived `PlannedSession`
field equals `CARD_META[card]`'s, `isHardDay` is `is_hard` (NOT `day_type` — the
two-axes rule survives expansion), `tier` is implied by `core[]`-vs-`extras[]`
membership (stamped by `expand_plan`, never read off the pick or a card), the
block carries the exact MODELS field set (no `hrCapBpm`/`cadenceSpm`) and
serializes camelCase, and the dose / `suggested_day` are copied verbatim.
"""

import pytest

from app.core.cards import CARD_META
from app.core.enums import DayType, Intensity, Tier, Weekday, WorkoutCard, Zone
from app.core.profile import Profile, load_profile
from app.services.derive.plan import (
    PlannedPick,
    PlannedSession,
    expand_plan,
    expand_plan_pick,
)


@pytest.fixture
def profile() -> Profile:
    return load_profile()


_CARD_SAMPLE = [
    WorkoutCard.easy_run,
    WorkoutCard.long_run,
    WorkoutCard.vo2,
    WorkoutCard.threshold,
    WorkoutCard.steady_cardio,
    WorkoutCard.strength_push,
    WorkoutCard.boxing,
    WorkoutCard.rest,
]


@pytest.mark.parametrize("card", _CARD_SAMPLE)
def test_derived_fields_equal_card_meta(card, profile):
    """Every code-derived `PlannedSession` field equals `CARD_META[card]`."""
    meta = CARD_META[card]
    pick = PlannedPick(
        card=card, suggested_day=Weekday.fri, duration_min_low=30, duration_min_high=40
    )
    sess = expand_plan_pick(pick, Tier.core, profile)

    assert isinstance(sess, PlannedSession)
    assert sess.card == card
    assert sess.tier is Tier.core
    assert sess.intensity == meta.intensity
    assert sess.is_hard_day == meta.is_hard
    assert sess.zone_target == meta.zone
    assert sess.flags == sorted(f.value for f in meta.flags)
    assert sess.suggested_day is Weekday.fri
    assert sess.duration_min_low == 30
    assert sess.duration_min_high == 40


def test_vo2_planned_session_worked_example(profile):
    """`PlannedPick{vo2, fri, 30, 40}` with `tier=core`."""
    sess = expand_plan_pick(
        PlannedPick(
            card=WorkoutCard.vo2,
            suggested_day=Weekday.fri,
            duration_min_low=30,
            duration_min_high=40,
        ),
        Tier.core,
        profile,
    )
    assert sess.intensity is Intensity.quality
    assert sess.is_hard_day is True
    assert sess.zone_target is Zone.z5
    assert sess.flags == ["impact", "needs_green_knee", "quality_day"]
    assert sess.suggested_day is Weekday.fri


def test_two_axes_survives_long_run(profile):
    """`long_run` → `is_hard_day is False` despite `day_type is DayType.hard`."""
    assert CARD_META[WorkoutCard.long_run].day_type is DayType.hard
    sess = expand_plan_pick(
        PlannedPick(card=WorkoutCard.long_run), Tier.extra, profile
    )
    assert sess.is_hard_day is False


def test_tier_from_array_membership(profile):
    """`expand_plan` stamps tier from the array, preserving order/length."""
    core = [
        PlannedPick(card=WorkoutCard.vo2, suggested_day=Weekday.tue),
        PlannedPick(card=WorkoutCard.threshold, suggested_day=Weekday.thu),
    ]
    extras = [PlannedPick(card=WorkoutCard.easy_run, suggested_day=Weekday.sat)]

    core_sessions, extra_sessions = expand_plan(core, extras, profile)

    assert len(core_sessions) == 2
    assert len(extra_sessions) == 1
    assert [s.card for s in core_sessions] == [WorkoutCard.vo2, WorkoutCard.threshold]
    assert all(s.tier is Tier.core for s in core_sessions)
    assert extra_sessions[0].card is WorkoutCard.easy_run
    assert extra_sessions[0].tier is Tier.extra


def test_tier_not_read_from_pick(profile):
    """The same card expands to either tier depending only on the array."""
    pick = PlannedPick(card=WorkoutCard.easy_run, suggested_day=Weekday.mon)
    core_sessions, extra_sessions = expand_plan([pick], [pick], profile)
    assert core_sessions[0].tier is Tier.core
    assert extra_sessions[0].tier is Tier.extra


def test_no_hr_cap_or_cadence_field(profile):
    """`PlannedSession` carries no daily-only `hrCapBpm`/`cadenceSpm` field."""
    sess = expand_plan_pick(
        PlannedPick(card=WorkoutCard.easy_run), Tier.core, profile
    )
    assert not hasattr(sess, "hr_cap_bpm")
    assert not hasattr(sess, "cadence_spm")
    dumped = sess.model_dump(by_alias=True)
    assert "hrCapBpm" not in dumped
    assert "cadenceSpm" not in dumped


def test_dose_and_suggested_day_copied_verbatim(profile):
    """An out-of-band dose / any `suggested_day` passes through unchanged."""
    sess = expand_plan_pick(
        PlannedPick(
            card=WorkoutCard.easy_run,
            suggested_day=Weekday.sun,
            duration_min_low=5,
            duration_min_high=200,
        ),
        Tier.extra,
        profile,
    )
    assert sess.duration_min_low == 5
    assert sess.duration_min_high == 200
    assert sess.suggested_day is Weekday.sun


def test_optional_fields_default_none(profile):
    """A minimal `PlannedPick` (card only) expands with null dose/day."""
    sess = expand_plan_pick(PlannedPick(card=WorkoutCard.rest), Tier.extra, profile)
    assert sess.suggested_day is None
    assert sess.duration_min_low is None
    assert sess.duration_min_high is None


def test_wire_is_camel_case_and_matches_models(profile):
    """`PlannedSession.model_dump(by_alias=True)` is the exact MODELS camelCase set."""
    sess = expand_plan_pick(
        PlannedPick(
            card=WorkoutCard.vo2,
            suggested_day=Weekday.fri,
            duration_min_low=30,
            duration_min_high=40,
        ),
        Tier.core,
        profile,
    )
    keys = set(sess.model_dump(by_alias=True).keys())
    assert keys == {
        "card",
        "tier",
        "intensity",
        "isHardDay",
        "suggestedDay",
        "zoneTarget",
        "durationMinLow",
        "durationMinHigh",
        "flags",
    }


def test_planned_pick_accepts_camel_input():
    """`PlannedPick` accepts the camelCase wire payload the LLM emits."""
    pick = PlannedPick.model_validate(
        {"card": "vo2", "suggestedDay": "fri", "durationMinLow": 30, "durationMinHigh": 40}
    )
    assert pick.card is WorkoutCard.vo2
    assert pick.suggested_day is Weekday.fri
    assert pick.duration_min_low == 30
