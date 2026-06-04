"""`derive_card_fields` — the shared card-field derivation core (E7·P2 TASK-001).

Pure unit tests over a real (or fixture) `Profile`: every `DerivedCardFields`
value must equal the corresponding `CARD_META[card]` attribute, the
`hr_cap`/`cadence` symbolic references must resolve against the **injected**
profile (never a hard-coded `146`/`160`), the ranged band / drift policy
(`zone_note`/`hr_cap_note`) must survive, `flags` must be the `.value` strings
(colon-preserved, sorted), and the two-axes rule (`is_hard` → `is_hard_day`;
`day_type` never read) must hold.
"""

import copy

import pytest

from app.core.cards import CARD_META, Flag
from app.core.enums import DayType, WorkoutCard, Zone
from app.core.profile import Profile, load_profile
from app.services.derive.card_fields import (
    DerivedCardFields,
    derive_card_fields,
    resolve_hr_cap,
)
from tests.core.test_profile import valid_profile_dict


@pytest.fixture
def profile() -> Profile:
    """The real repo `profile.yaml` (`easy_hr_cap=146`, `cadence_current_spm=160`)."""
    return load_profile()


@pytest.fixture
def non_default_profile() -> Profile:
    """A fixture profile with non-default `easy_hr_cap`/`cadence_current_spm` so a
    test proves the resolved values track the injected profile, not constants.
    `cadence_current_spm=165 <= cadence_target_spm=172` and `easy_hr_cap=150 <
    max_hr=192` keep the profile's own consistency validators happy."""
    d = valid_profile_dict()
    d["thresholds"]["easy_hr_cap"] = 150
    d["thresholds"]["cadence_current_spm"] = 165
    return Profile(**copy.deepcopy(d))


# A per-category card sample (running / cardio / strength / boxing / mobility /
# prehab / rest) — every category exercised at least once.
_CARD_SAMPLE = [
    WorkoutCard.easy_run,
    WorkoutCard.long_run,
    WorkoutCard.vo2,
    WorkoutCard.threshold,
    WorkoutCard.steady_cardio,
    WorkoutCard.strength_push,
    WorkoutCard.boxing,
    WorkoutCard.mobility,
    WorkoutCard.rest,
    WorkoutCard.foot_prehab,
]


@pytest.mark.parametrize("card", _CARD_SAMPLE)
def test_derived_fields_equal_card_meta(card, profile):
    """Every code-derived field equals the named `CARD_META[card]` attribute."""
    meta = CARD_META[card]
    d = derive_card_fields(card, profile)

    assert isinstance(d, DerivedCardFields)
    assert d.intensity == meta.intensity
    assert d.zone_target == meta.zone
    assert d.is_hard_day == meta.is_hard
    assert d.zone_note == meta.zone_note
    assert d.hr_cap_note == meta.hr_cap_note
    assert d.flags == sorted(f.value for f in meta.flags)


def test_hr_cap_resolves_for_capped_cards(profile):
    """`easy_run`/`long_run` resolve `hr_cap` to `profile.thresholds.easy_hr_cap`."""
    assert derive_card_fields(WorkoutCard.easy_run, profile).hr_cap_bpm == (
        profile.thresholds.easy_hr_cap
    )
    assert derive_card_fields(WorkoutCard.long_run, profile).hr_cap_bpm == (
        profile.thresholds.easy_hr_cap
    )


@pytest.mark.parametrize(
    "card",
    [WorkoutCard.vo2, WorkoutCard.threshold, WorkoutCard.strength_push, WorkoutCard.rest],
)
def test_hr_cap_none_for_uncapped_cards(card, profile):
    """A card with no `hr_cap` key → `hr_cap_bpm is None`."""
    assert derive_card_fields(card, profile).hr_cap_bpm is None


def test_hr_cap_tracks_injected_profile(non_default_profile):
    """The resolved bpm tracks the injected profile, not a hard-coded 146."""
    assert non_default_profile.thresholds.easy_hr_cap == 150
    assert derive_card_fields(WorkoutCard.easy_run, non_default_profile).hr_cap_bpm == 150


@pytest.mark.parametrize("card", [WorkoutCard.easy_run, WorkoutCard.vo2, WorkoutCard.long_run])
def test_cadence_set_for_cue_cards(card, profile):
    """A cue card carries `profile.thresholds.cadence_current_spm`."""
    assert CARD_META[card].cadence is True
    assert derive_card_fields(card, profile).cadence_spm == (
        profile.thresholds.cadence_current_spm
    )


@pytest.mark.parametrize(
    "card",
    [WorkoutCard.steady_cardio, WorkoutCard.strength_push, WorkoutCard.rest, WorkoutCard.mobility],
)
def test_cadence_none_for_non_cue_cards(card, profile):
    """A non-cue card → `cadence_spm is None`."""
    assert CARD_META[card].cadence is False
    assert derive_card_fields(card, profile).cadence_spm is None


def test_cadence_tracks_injected_profile(non_default_profile):
    """The cue tracks the injected profile, not a hard-coded 160."""
    assert non_default_profile.thresholds.cadence_current_spm == 165
    assert derive_card_fields(WorkoutCard.easy_run, non_default_profile).cadence_spm == 165


def test_zone_note_carried_through(profile):
    """`boxing`'s `z3–z5` band survives — not collapsed to the bare top zone."""
    d = derive_card_fields(WorkoutCard.boxing, profile)
    assert d.zone_target is Zone.z5
    assert d.zone_note == "z3–z5"


def test_hr_cap_note_carried_through(profile):
    """`long_run`'s drift policy survives."""
    assert derive_card_fields(WorkoutCard.long_run, profile).hr_cap_note == "start, drift OK"


def test_flags_are_value_strings_colon_preserved(profile):
    """`foot_prehab` → `["prehab:foot"]` (the `.value` string, colon preserved)."""
    assert derive_card_fields(WorkoutCard.foot_prehab, profile).flags == ["prehab:foot"]


def test_flags_are_sorted_and_value_strings(profile):
    """`vo2` flags are the sorted `.value` strings, not member names."""
    d = derive_card_fields(WorkoutCard.vo2, profile)
    assert d.flags == sorted(f.value for f in CARD_META[WorkoutCard.vo2].flags)
    assert d.flags == ["impact", "needs_green_knee", "quality_day"]
    # No member-name leakage and reproducible (sorted) order.
    assert d.flags == sorted(d.flags)
    assert all(isinstance(f, str) and f in {x.value for x in Flag} for f in d.flags)


def test_two_axes_survives_long_run(profile):
    """`long_run` is `is_hard_day False` even though `day_type is DayType.hard`."""
    assert CARD_META[WorkoutCard.long_run].day_type is DayType.hard
    assert CARD_META[WorkoutCard.long_run].is_hard is False
    assert derive_card_fields(WorkoutCard.long_run, profile).is_hard_day is False


def test_resolve_hr_cap_none_passthrough(profile):
    """`resolve_hr_cap(None, profile)` is `None` (a card with no cap)."""
    assert resolve_hr_cap(None, profile) is None


def test_resolve_hr_cap_unknown_key_raises(profile):
    """An unknown `hr_cap` key surfaces loudly as `AttributeError` (drift bug)."""
    with pytest.raises(AttributeError):
        resolve_hr_cap("nonexistent_key", profile)
