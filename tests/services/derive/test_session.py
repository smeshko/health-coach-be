"""`expand_session` — the daily `SessionPick`→`SessionBlock` expander (E7·P2 TASK-002).

Pure unit tests with an injected `Profile`: every code-derived `SessionBlock`
field equals `CARD_META[card]`'s (epic §4 bullet 2), the run/cue cards carry the
cadence cue (non-cue → null), the dose is copied **verbatim and unvalidated**
(an out-of-band dose passes through — derive ≠ validate), the block carries the
exact MODELS field set (no `isHardDay`/`tier`) and serializes camelCase, and the
`zone_note`/`hr_cap_note` stay reachable via `expand_session_with_notes`.
"""

import pytest

from app.core.cards import CARD_META
from app.core.enums import Intensity, WorkoutCard, Zone
from app.core.profile import Profile, load_profile
from app.services.derive.card_fields import DerivedCardFields
from app.services.derive.session import (
    SessionBlock,
    SessionPick,
    expand_session,
    expand_session_with_notes,
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
    """Every code-derived `SessionBlock` field equals `CARD_META[card]` / profile."""
    meta = CARD_META[card]
    pick = SessionPick(card=card, duration_min_low=30, duration_min_high=40)
    block = expand_session(pick, profile)

    assert isinstance(block, SessionBlock)
    assert block.card == card
    assert block.intensity == meta.intensity
    assert block.zone_target == meta.zone
    assert block.flags == sorted(f.value for f in meta.flags)
    # hr_cap/cadence are the profile-resolved values for this card.
    expected_hr = (
        getattr(profile.thresholds, meta.hr_cap) if meta.hr_cap is not None else None
    )
    assert block.hr_cap_bpm == expected_hr
    assert block.cadence_spm == (
        profile.thresholds.cadence_current_spm if meta.cadence else None
    )


def test_easy_run_block_equals_card_meta(profile):
    """The epic §4 bullet 2 worked example: `SessionPick{easy_run, 30, 40}`."""
    block = expand_session(
        SessionPick(card=WorkoutCard.easy_run, duration_min_low=30, duration_min_high=40),
        profile,
    )
    assert block.intensity is Intensity.easy
    assert block.zone_target is Zone.z2
    assert block.hr_cap_bpm == profile.thresholds.easy_hr_cap
    assert block.cadence_spm == profile.thresholds.cadence_current_spm
    assert block.flags == ["impact"]
    assert block.duration_min_low == 30
    assert block.duration_min_high == 40


@pytest.mark.parametrize("card", [WorkoutCard.easy_run, WorkoutCard.vo2])
def test_cue_cards_carry_cadence(card, profile):
    block = expand_session(
        SessionPick(card=card, duration_min_low=20, duration_min_high=30), profile
    )
    assert block.cadence_spm == profile.thresholds.cadence_current_spm


@pytest.mark.parametrize(
    "card", [WorkoutCard.steady_cardio, WorkoutCard.strength_push, WorkoutCard.rest]
)
def test_non_cue_cards_get_null_cadence(card, profile):
    block = expand_session(
        SessionPick(card=card, duration_min_low=20, duration_min_high=30), profile
    )
    assert block.cadence_spm is None


def test_dose_copied_verbatim_not_validated(profile):
    """An out-of-band dose (`easy_run` band 25–50) expands unchanged, no error."""
    block = expand_session(
        SessionPick(card=WorkoutCard.easy_run, duration_min_low=5, duration_min_high=200),
        profile,
    )
    assert block.duration_min_low == 5
    assert block.duration_min_high == 200


def test_card_passes_through_and_no_isharddday_or_tier(profile):
    """`card` is unchanged and the block has no `isHardDay`/`tier` field."""
    block = expand_session(
        SessionPick(card=WorkoutCard.vo2, duration_min_low=25, duration_min_high=45),
        profile,
    )
    assert block.card is WorkoutCard.vo2
    assert not hasattr(block, "is_hard_day")
    assert not hasattr(block, "tier")
    assert "isHardDay" not in block.model_dump(by_alias=True)
    assert "tier" not in block.model_dump(by_alias=True)


def test_notes_reachable_via_with_notes(profile):
    """`expand_session_with_notes` surfaces the band/drift policy."""
    block, d = expand_session_with_notes(
        SessionPick(card=WorkoutCard.long_run, duration_min_low=60, duration_min_high=90),
        profile,
    )
    assert isinstance(block, SessionBlock)
    assert isinstance(d, DerivedCardFields)
    assert d.hr_cap_note == "start, drift OK"
    # And the block matches the standalone expander.
    assert block == expand_session(
        SessionPick(card=WorkoutCard.long_run, duration_min_low=60, duration_min_high=90),
        profile,
    )


def test_boxing_zone_note_reachable(profile):
    _, d = expand_session_with_notes(
        SessionPick(card=WorkoutCard.boxing, duration_min_low=60, duration_min_high=90),
        profile,
    )
    assert d.zone_note == "z3–z5"


def test_wire_is_camel_case_and_matches_models(profile):
    """`SessionBlock.model_dump(by_alias=True)` is the exact MODELS camelCase set."""
    block = expand_session(
        SessionPick(card=WorkoutCard.easy_run, duration_min_low=30, duration_min_high=40),
        profile,
    )
    keys = set(block.model_dump(by_alias=True).keys())
    assert keys == {
        "card",
        "intensity",
        "zoneTarget",
        "durationMinLow",
        "durationMinHigh",
        "hrCapBpm",
        "cadenceSpm",
        "flags",
    }


def test_session_pick_accepts_camel_input():
    """`SessionPick` accepts the camelCase wire payload the LLM emits."""
    pick = SessionPick.model_validate(
        {"card": "easy_run", "durationMinLow": 30, "durationMinHigh": 40}
    )
    assert pick.card is WorkoutCard.easy_run
    assert pick.duration_min_low == 30
    assert pick.duration_min_high == 40
