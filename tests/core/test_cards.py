"""Unit tests for CARD_META, the Flag/Impact enums, the downgrade map, and the
lookup API (E7·P1 TASK-002 + TASK-003).

The 20-row ``EXPECTED`` table is a hand transcription of CARDS.md §1A–§1E — it
asserts **every** ``CardMeta`` field for **every** card (no "at minimum"
subset), so a wrong attribute (a flipped ``is_hard``, a dropped ``serves`` or
``zone_note``, a mistyped flag) fails the test rather than slipping through.
"""

import dataclasses

import pytest

from app.core.cards import (
    CARD_META,
    DOWNGRADE_MAP,
    CardMeta,
    Downgrade,
    Flag,
    Impact,
    all_cards,
    downgrade_for,
    floors_day_type_hard,
    get_card,
    is_hard_card,
)
from app.core.enums import DayType, Intensity, WorkoutCard, Zone

C = WorkoutCard

# --- Full per-card expected table, transcribed column-for-column from CARDS.md
# §1A–§1E. Tuple order:
# (intensity, is_hard, day_type, zone, zone_note, hr_cap, hr_cap_note,
#  cadence, impact, dose_low, dose_high, flags, serves)
EXPECTED: dict[WorkoutCard, tuple] = {
    # --- 1A. Running -----------------------------------------------------
    C.easy_run: (
        Intensity.easy, False, DayType.moderate, Zone.z2, None,
        "easy_hr_cap", None, True, Impact.yes, 25, 50,
        frozenset({Flag.impact}),
        "aerobic base, fat ox., recovery",
    ),
    C.long_run: (
        Intensity.easy, False, DayType.hard, Zone.z2, "z2 (by effort)",
        "easy_hr_cap", "start, drift OK", True, Impact.yes, 60, None,
        frozenset({Flag.impact, Flag.long, Flag.effort_based}),
        "endurance, durability, HM progression",
    ),
    C.progression_run: (
        Intensity.quality, True, DayType.hard, Zone.z4, "z2→z4",
        None, None, True, Impact.yes, 50, 80,
        frozenset({Flag.quality_day, Flag.impact, Flag.needs_green_knee}),
        "running on tired legs; HM stamina (periodized upgrade)",
    ),
    C.threshold: (
        Intensity.quality, True, DayType.hard, Zone.z4, None,
        None, None, True, Impact.yes, 30, 50,
        frozenset({Flag.quality_day, Flag.impact}),
        'lactate threshold, "comfortably hard"',
    ),
    C.vo2: (
        Intensity.quality, True, DayType.hard, Zone.z5, None,
        None, None, True, Impact.high, 25, 45,
        frozenset({Flag.quality_day, Flag.impact, Flag.needs_green_knee}),
        "top-end aerobic power, VO₂max",
    ),
    C.strides: (
        Intensity.easy, False, DayType.moderate, Zone.z5, "z5 (brief)",
        None, None, True, Impact.yes, 5, 12,
        frozenset({Flag.impact, Flag.append_to_easy}),
        "running economy, neuromuscular, cadence",
    ),
    C.active_recovery: (
        Intensity.recovery, False, DayType.rest, Zone.z1, None,
        None, None, False, Impact.no, 20, 40,
        frozenset({Flag.low_impact}),
        "blood flow, gentle recovery (walk/spin/row/mobility)",
    ),
    # --- 1B. Cardio ------------------------------------------------------
    C.hiit: (
        Intensity.quality, True, DayType.hard, Zone.z5, "z4–z5",
        None, None, False, Impact.conditional, 15, 25,
        frozenset({Flag.quality_day, Flag.prefer_low_impact}),
        "conditioning, fat loss, time-efficient",
    ),
    C.jump_rope: (
        Intensity.quality, False, DayType.moderate, Zone.z4, "z3–z4",
        None, None, True, Impact.yes, 8, 20,
        frozenset({Flag.impact, Flag.knee_amber_cap}),
        "conditioning, calf/foot stiffness, cadence",
    ),
    C.steady_cardio: (
        Intensity.easy, False, DayType.moderate, Zone.z2, None,
        None, None, False, Impact.no, 30, 50,
        frozenset({Flag.low_impact}),
        "low-impact aerobic base (bike/row/elliptical/incline walk)",
    ),
    # --- 1C. Strength ----------------------------------------------------
    C.strength_push: (
        Intensity.quality, False, DayType.moderate, None, None,
        None, None, False, Impact.no, 30, 45,
        frozenset({Flag.strength, Flag.upper}),
        "upper-body muscle (chest/shoulder/triceps)",
    ),
    C.strength_pull: (
        Intensity.quality, False, DayType.moderate, None, None,
        None, None, False, Impact.no, 30, 45,
        frozenset({Flag.strength, Flag.upper}),
        "upper-body muscle (back/biceps) + posture",
    ),
    C.strength_lower: (
        Intensity.quality, False, DayType.moderate, None, None,
        None, None, False, Impact.low, 25, 35,
        frozenset({Flag.strength, Flag.lower}),
        "running support, knee stability",
    ),
    C.strength_full: (
        Intensity.quality, False, DayType.moderate, None, None,
        None, None, False, Impact.low, 20, 35,
        frozenset({Flag.strength}),
        "GPP, carryover, time-crunch option",
    ),
    # --- 1D. Boxing ------------------------------------------------------
    C.boxing: (
        Intensity.quality, True, DayType.hard, Zone.z5, "z3–z5",
        None, None, False, Impact.low, 60, 90,
        frozenset({Flag.quality_day, Flag.big_recovery_cost}),
        "conditioning, fat loss, adherence, upper-body endurance",
    ),
    C.boxing_technique: (
        Intensity.easy, False, DayType.moderate, Zone.z3, "z2–z3",
        None, None, False, Impact.low, 45, 60,
        frozenset({Flag.auto_reg_downgrade}),
        "skill on a tired/amber day (footwork/pads light)",
    ),
    # --- 1E. Mobility / prehab -------------------------------------------
    C.foot_prehab: (
        Intensity.recovery, False, DayType.rest, None, None,
        None, None, False, Impact.no, 5, 10,
        frozenset({Flag.prehab_foot}),
        "arch/intrinsic strength (flat feet), ↓ injury",
    ),
    C.glute_prehab: (
        Intensity.recovery, False, DayType.rest, None, None,
        None, None, False, Impact.no, 5, 10,
        frozenset({Flag.prehab_glute}),
        "knee tracking, ↓ knee pain",
    ),
    C.mobility: (
        Intensity.recovery, False, DayType.rest, None, None,
        None, None, False, Impact.no, 10, 30,
        frozenset({Flag.red_day_default}),
        "recovery, range, stress/sleep (pre-bed OK)",
    ),
    C.rest: (
        Intensity.recovery, False, DayType.rest, None, None,
        None, None, False, Impact.no, 0, 0,
        frozenset(),
        "full rest (the gate/RED default)",
    ),
}

# The exact, closed Flag vocabulary = CARDS.md §2 vocabulary ∪ the §1-only
# `red_day_default` (round-3 #2).
EXPECTED_FLAG_VALUES = {
    "impact",
    "needs_green_knee",
    "quality_day",
    "low_impact",
    "prefer_low_impact",
    "knee_amber_cap",
    "append_to_easy",
    "effort_based",
    "auto_reg_downgrade",
    "big_recovery_cost",
    "long",
    "strength",
    "upper",
    "lower",
    "prehab:foot",
    "prehab:glute",
    "red_day_default",
}


# --------------------------------------------------------------------------
# Flag / Impact enum coverage
# --------------------------------------------------------------------------
def test_impact_value_set_is_exact():
    assert {i.value for i in Impact} == {"yes", "no", "low", "high", "conditional"}


def test_flag_value_set_is_exact_closed_literal():
    # The exact closed set — not merely a subset; an undocumented extra member
    # or a missing §1 flag must both fail.
    assert {f.value for f in Flag} == EXPECTED_FLAG_VALUES


def test_every_flag_used_in_table_is_a_flag_member():
    flags_used = {f.value for meta in CARD_META.values() for f in meta.flags}
    assert flags_used <= {f.value for f in Flag}


def test_prehab_flags_preserve_colon():
    assert Flag.prehab_foot.value == "prehab:foot"
    assert Flag.prehab_glute.value == "prehab:glute"


# --------------------------------------------------------------------------
# Completeness
# --------------------------------------------------------------------------
def test_card_meta_is_complete_over_workout_card():
    assert set(CARD_META) == set(WorkoutCard)
    assert len(CARD_META) == 20


def test_expected_table_covers_all_cards():
    # Guards the test itself: the hand-transcribed table covers every card.
    assert set(EXPECTED) == set(WorkoutCard)


# --------------------------------------------------------------------------
# Full per-card attribute transcription (no "at minimum" subset)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("card", list(WorkoutCard))
def test_full_per_card_attributes_match_cards_md(card):
    (
        intensity,
        is_hard,
        day_type,
        zone,
        zone_note,
        hr_cap,
        hr_cap_note,
        cadence,
        impact,
        dose_low,
        dose_high,
        flags,
        serves,
    ) = EXPECTED[card]
    meta = CARD_META[card]
    assert meta.card is card
    assert meta.intensity is intensity
    assert meta.is_hard is is_hard
    assert meta.day_type is day_type
    assert meta.zone is zone
    assert meta.zone_note == zone_note
    assert meta.hr_cap == hr_cap
    assert meta.hr_cap_note == hr_cap_note
    assert meta.cadence is cadence
    assert meta.impact is impact
    assert meta.dose_min_low == dose_low
    assert meta.dose_min_high == dose_high
    assert meta.flags == flags
    assert meta.serves == serves


# --------------------------------------------------------------------------
# Ranged-zone band preserved in zone_note (round-3 #1)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "card,band",
    [
        (C.long_run, "z2 (by effort)"),
        (C.progression_run, "z2→z4"),
        (C.strides, "z5 (brief)"),
        (C.hiit, "z4–z5"),
        (C.jump_rope, "z3–z4"),
        (C.boxing, "z3–z5"),
        (C.boxing_technique, "z2–z3"),
    ],
)
def test_ranged_cards_carry_band_in_zone_note(card, band):
    assert CARD_META[card].zone_note == band


# --------------------------------------------------------------------------
# Epic spot-checks
# --------------------------------------------------------------------------
def test_spot_check_long_run_two_axes():
    meta = CARD_META[C.long_run]
    assert meta.is_hard is False
    assert meta.day_type is DayType.hard


def test_spot_check_vo2_impact_high():
    assert CARD_META[C.vo2].impact is Impact.high


# --------------------------------------------------------------------------
# Two-axes independence
# --------------------------------------------------------------------------
def test_is_hard_and_day_type_are_independent_axes():
    # There is at least one card where the two axes diverge — pinned by long_run.
    divergent = {
        c for c, m in CARD_META.items() if m.is_hard != (m.day_type is DayType.hard)
    }
    assert C.long_run in divergent
    assert divergent  # the axes are modelled independently, not aliased


# --------------------------------------------------------------------------
# Representative cards per category
# --------------------------------------------------------------------------
def test_representative_easy_run():
    m = CARD_META[C.easy_run]
    assert m.zone is Zone.z2
    assert m.hr_cap == "easy_hr_cap"
    assert m.hr_cap_note is None
    assert (m.dose_min_low, m.dose_min_high) == (25, 50)
    assert m.flags == frozenset({Flag.impact})


def test_representative_long_run():
    m = CARD_META[C.long_run]
    assert m.zone is Zone.z2
    assert m.zone_note == "z2 (by effort)"
    assert m.hr_cap == "easy_hr_cap"
    assert m.hr_cap_note == "start, drift OK"


def test_representative_boxing_low_impact_not_gated():
    m = CARD_META[C.boxing]
    assert m.is_hard is True
    assert m.zone is Zone.z5
    assert m.zone_note == "z3–z5"
    assert m.impact is Impact.low
    assert (m.dose_min_low, m.dose_min_high) == (60, 90)
    # A low-impact card is NOT knee-gated — the gate keys on Flag.impact, not
    # the Impact column (round-1 #1).
    assert Flag.impact not in m.flags


def test_representative_strength_push():
    m = CARD_META[C.strength_push]
    assert m.zone is None
    assert m.impact is Impact.no
    assert m.flags == frozenset({Flag.strength, Flag.upper})


def test_representative_rest():
    m = CARD_META[C.rest]
    assert m.day_type is DayType.rest
    assert (m.dose_min_low, m.dose_min_high) == (0, 0)
    assert m.flags == frozenset()


def test_impact_flag_and_impact_column_do_not_alias():
    # A card can carry Flag.impact at any Impact level; the two are separate.
    # easy_run: Impact.yes AND Flag.impact; boxing: Impact.low WITHOUT Flag.impact.
    assert CARD_META[C.easy_run].impact is Impact.yes
    assert Flag.impact in CARD_META[C.easy_run].flags
    assert CARD_META[C.boxing].impact is Impact.low
    assert Flag.impact not in CARD_META[C.boxing].flags


# --------------------------------------------------------------------------
# Dose-band sanity
# --------------------------------------------------------------------------
def test_dose_band_low_le_high_where_both_set():
    for card, meta in CARD_META.items():
        if meta.dose_min_high is not None:
            assert meta.dose_min_low <= meta.dose_min_high, card


def test_long_run_dose_high_is_open_ended():
    assert CARD_META[C.long_run].dose_min_high is None


def test_rest_dose_is_zero_zero():
    m = CARD_META[C.rest]
    assert (m.dose_min_low, m.dose_min_high) == (0, 0)


# --------------------------------------------------------------------------
# Immutability
# --------------------------------------------------------------------------
def test_card_meta_is_frozen():
    m = CARD_META[C.rest]
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.is_hard = True  # type: ignore[misc]


def test_card_meta_replace_works():
    m = CARD_META[C.rest]
    replaced = dataclasses.replace(m, dose_min_high=5)
    assert replaced.dose_min_high == 5
    assert m.dose_min_high == 0  # original untouched


def test_flags_is_a_frozenset():
    assert isinstance(CARD_META[C.easy_run].flags, frozenset)


def test_card_meta_mapping_is_read_only():
    with pytest.raises(TypeError):
        CARD_META[C.rest] = CARD_META[C.easy_run]  # type: ignore[index]


def test_card_meta_is_a_card_meta_instance():
    assert isinstance(CARD_META[C.vo2], CardMeta)


# ==========================================================================
# TASK-003: DOWNGRADE_MAP, the knee-gate set, the fuel-floor predicate, and
# the lookup API.
# ==========================================================================

# The CARDS.md §3 rows, pinned per DECISIONS.md Decision 3:
# (planned_card, expected_amber_tuple, expected_red_tuple)
EXPECTED_DOWNGRADES = [
    (C.vo2, (C.easy_run, C.steady_cardio), (C.active_recovery, C.mobility, C.rest)),
    (C.threshold, (C.easy_run, C.steady_cardio), (C.active_recovery, C.mobility, C.rest)),
    (C.progression_run, (C.easy_run, C.steady_cardio), (C.active_recovery, C.mobility, C.rest)),
    (C.hiit, (C.steady_cardio,), (C.active_recovery, C.mobility)),
    (C.boxing, (C.boxing_technique,), (C.rest, C.mobility)),
    (C.long_run, (C.easy_run,), (C.active_recovery, C.rest)),
    (C.easy_run, (C.steady_cardio,), (C.active_recovery, C.mobility)),
    (C.jump_rope, (C.steady_cardio,), (C.rest,)),
    (C.strength_push, (), (C.mobility, C.rest)),
    (C.strength_pull, (), (C.mobility, C.rest)),
    (C.strength_lower, (), (C.mobility, C.rest)),
    (C.strength_full, (), (C.mobility, C.rest)),
]

# The knee-gate set — pinned independently from CARDS.md §1 (NOT derived from
# CARD_META, which would be circular: a wrong Flag.impact would define and pass
# its own expectation — round-2 #1).
EXPECTED_IMPACT_FLAG_CARDS = {
    C.easy_run,
    C.long_run,
    C.progression_run,
    C.threshold,
    C.vo2,
    C.strides,
    C.jump_rope,
}


@pytest.mark.parametrize("card,amber,red", EXPECTED_DOWNGRADES)
def test_downgrade_map_rows_match_cards_md(card, amber, red):
    dg = DOWNGRADE_MAP[card]
    assert dg.amber == amber
    assert dg.red == red


def test_downgrade_map_has_exactly_the_expected_keys():
    assert set(DOWNGRADE_MAP) == {card for card, _, _ in EXPECTED_DOWNGRADES}


def test_strength_amber_is_empty_tuple():
    # "light" version = a dose reduction, not a card swap.
    for card in (C.strength_push, C.strength_pull, C.strength_lower, C.strength_full):
        assert DOWNGRADE_MAP[card].amber == ()


def test_downgrade_substitutes_are_valid_workout_cards():
    for dg in DOWNGRADE_MAP.values():
        for sub in (*dg.amber, *dg.red):
            assert isinstance(sub, WorkoutCard)
            assert sub in CARD_META


def test_knee_pain_safety_gate_row_is_not_in_the_map():
    # The "any impact card with knee_pain > 3" row is a runtime predicate keyed
    # on Flag.impact (E7·P3), deliberately not a static map entry.
    assert C.foot_prehab not in DOWNGRADE_MAP  # sanity: not every card is a key
    # No key represents the gate; the map only holds per-planned-card swaps.
    assert set(DOWNGRADE_MAP) == {card for card, _, _ in EXPECTED_DOWNGRADES}


def test_knee_gate_set_keys_on_flag_impact_against_pinned_literal():
    # Compute the actual gated set from the table; assert it equals the
    # independently-pinned CARDS.md literal (not the other way round).
    actual = {c for c in WorkoutCard if Flag.impact in CARD_META[c].flags}
    assert actual == EXPECTED_IMPACT_FLAG_CARDS


@pytest.mark.parametrize("card", [C.boxing, C.strength_lower, C.hiit])
def test_low_or_conditional_impact_card_without_flag_is_not_gated(card):
    # These carry no Flag.impact even though some are Impact.low/conditional.
    assert Flag.impact not in CARD_META[card].flags
    assert card not in EXPECTED_IMPACT_FLAG_CARDS


# --------------------------------------------------------------------------
# Fuel-floor predicate
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "card", [C.vo2, C.long_run, C.boxing, C.threshold, C.progression_run, C.hiit]
)
def test_floors_day_type_hard_true(card):
    assert floors_day_type_hard(card) is True


@pytest.mark.parametrize("card", [C.easy_run, C.rest, C.strength_push, C.active_recovery])
def test_floors_day_type_hard_false(card):
    assert floors_day_type_hard(card) is False


def test_floors_day_type_hard_long_run_is_floored_despite_not_is_hard():
    # long_run is is_hard=False but floors dayType at hard via the `long` flag.
    assert is_hard_card(C.long_run) is False
    assert floors_day_type_hard(C.long_run) is True


# --------------------------------------------------------------------------
# Lookup API
# --------------------------------------------------------------------------
def test_get_card_returns_the_card_meta():
    assert get_card(C.vo2) is CARD_META[C.vo2]
    assert isinstance(get_card(C.vo2), CardMeta)


def test_is_hard_card():
    assert is_hard_card(C.vo2) is True
    assert is_hard_card(C.easy_run) is False


def test_downgrade_for():
    assert downgrade_for(C.boxing).amber == (C.boxing_technique,)
    assert isinstance(downgrade_for(C.boxing), Downgrade)
    assert downgrade_for(C.mobility) is None


def test_all_cards_returns_20_in_stable_order():
    cards1 = all_cards()
    cards2 = all_cards()
    assert len(cards1) == 20
    assert all(isinstance(m, CardMeta) for m in cards1)
    # Stable order across calls.
    assert [m.card for m in cards1] == [m.card for m in cards2]


def test_downgrade_is_frozen():
    dg = DOWNGRADE_MAP[C.boxing]
    with pytest.raises(dataclasses.FrozenInstanceError):
        dg.amber = ()  # type: ignore[misc]
