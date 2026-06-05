"""E8·P2 safety-gate tests — pure table-driven unit tests (no session/TestClient/LLM).

Mirrors CONSTITUTION §6.2's authoritative gate table — the six reasons + their strict
thresholds (GI symptoms; Sleep <4 h; Illness/fever; Knee pain >3/10; RHR >+12 bpm over
baseline; HRV crash >40 %) — plus the epic §4 / MODELS worked examples (the six machine
reason keys, the `overrideTo` universe `rest`/`active_recovery`/`mobility`, the triggered
example `["knee_pain_high"] → "active_recovery"`, the empty example), the strict-boundary
edges, the null/skip cases (a sparse/day-one E6·P2 baseline), and the most-restrictive
`overrideTo` precedence. Every input is a plain number/flag — no DB row, no HTTP, no LLM
(epic R6).
"""

from __future__ import annotations

import dataclasses

import pytest

from app.core.enums import WorkoutCard
from app.services.safety_gate import (
    GI_FLARE,
    HRV_CRASH,
    HRV_CRASH_FRACTION,
    ILLNESS,
    KNEE_PAIN_HIGH,
    RHR_SPIKE,
    RHR_SPIKE_BPM,
    SLEEP_BELOW_4H,
    SafetyGate,
    collect_reasons,
    evaluate_safety_gate,
    gi_flare_reason,
    hrv_crash_reason,
    illness_reason,
    knee_pain_high_reason,
    override_for,
    rhr_spike_reason,
    sleep_below_4h_reason,
)

# All-clear objective inputs (no reason fires) — the baseline for single-reason cases.
_ALL_CLEAR = dict(
    gi_symptoms=0,
    illness=0,
    knee_pain=0,
    sleep_h=8.0,
    rhr=55.0,
    rhr_30d_mean=55.0,
    hrv_sdnn=60.0,
    hrv_30d_mean=60.0,
)

# The six MODELS machine reason keys, in the fixed §6.2 / MODELS listing order.
_SIX_REASONS = [GI_FLARE, SLEEP_BELOW_4H, ILLNESS, KNEE_PAIN_HIGH, RHR_SPIKE, HRV_CRASH]

# The three forced-card tokens (the MODELS `overrideTo` universe).
_FORCED_CARDS = {WorkoutCard.rest, WorkoutCard.active_recovery, WorkoutCard.mobility}


# --- gi_flare_reason (§6.2 "GI symptoms → no hard training; easy/mobility only") ---


def test_gi_flare_fires_on_flag():
    assert gi_flare_reason(1) == GI_FLARE
    assert gi_flare_reason(1) == "gi_flare"


def test_gi_flare_clear_or_null_does_not_fire():
    assert gi_flare_reason(0) is None
    assert gi_flare_reason(None) is None  # absence ≠ flare (DECISIONS 4)


# --- sleep_below_4h_reason (§6.2 "Sleep <4 h → rest or Z1 active recovery only") ---


def test_sleep_below_4h_fires_below_floor():
    # strict `< 4` — 3.9 h trips
    assert sleep_below_4h_reason(3.9) == SLEEP_BELOW_4H
    assert sleep_below_4h_reason(3.9) == "sleep_below_4h"


def test_sleep_below_4h_strict_floor_does_not_fire_at_or_above_4():
    assert sleep_below_4h_reason(4.0) is None  # exactly 4 h does NOT trip (strict <4)
    assert sleep_below_4h_reason(4.5) is None
    assert sleep_below_4h_reason(None) is None  # no reading ≠ 0 h (DECISIONS 4)


# --- illness_reason (§6.2 "Illness / fever → rest") ---


def test_illness_fires_on_flag():
    assert illness_reason(1) == ILLNESS
    assert illness_reason(1) == "illness"


def test_illness_clear_or_null_does_not_fire():
    assert illness_reason(0) is None
    assert illness_reason(None) is None


# --- knee_pain_high_reason (§6.2 "Knee pain >3/10 → no running/jumping/plyo") ---


def test_knee_pain_high_fires_above_floor():
    # strict `> 3` — 4 trips
    assert knee_pain_high_reason(4) == KNEE_PAIN_HIGH
    assert knee_pain_high_reason(4) == "knee_pain_high"


def test_knee_pain_high_strict_floor_does_not_fire_at_or_below_3():
    assert knee_pain_high_reason(3) is None  # exactly 3 does NOT trip (strict >3)
    assert knee_pain_high_reason(0) is None  # 0 = none (DB.md §3)
    assert knee_pain_high_reason(None) is None


# --- rhr_spike_reason (§6.2 "Resting HR >+12 bpm over baseline → treat as red") ---


def test_rhr_spike_fires_above_strict_band():
    # build the edge off the constant: mean + 12 = no trip, mean + 13 = trip
    mean = 55.0
    # delta 13 (strictly > 12) trips
    assert rhr_spike_reason(mean + RHR_SPIKE_BPM + 1, mean) == RHR_SPIKE
    assert rhr_spike_reason(mean + RHR_SPIKE_BPM + 1, mean) == "rhr_spike"


def test_rhr_spike_strict_band_does_not_fire_at_or_below_12():
    mean = 55.0
    # delta == 12 exactly does NOT trip (strict >)
    assert rhr_spike_reason(mean + RHR_SPIKE_BPM, mean) is None
    # delta 11 does not trip
    assert rhr_spike_reason(mean + RHR_SPIKE_BPM - 1, mean) is None


def test_rhr_spike_null_baseline_or_reading_skips():
    assert rhr_spike_reason(None, 50.0) is None
    assert rhr_spike_reason(63.0, None) is None  # day-one sparse baseline (DECISIONS 5)


def test_rhr_spike_uses_rolling_baseline_argument():
    # the comparison is against the rolling rhr_30d_mean argument, never an anchor:
    # a reading 15 over the rolling mean trips regardless of any profile value
    assert rhr_spike_reason(70.0, 55.0) == RHR_SPIKE
    # the same reading vs a higher rolling mean (within band) does not
    assert rhr_spike_reason(70.0, 60.0) is None


# --- hrv_crash_reason (§6.2 "HRV crash >40 % → treat as red", mean-only percent-drop) ---


def test_hrv_crash_fires_more_than_40pct_below_mean():
    mean = 60.0
    # exactly 40 % below is the strict edge: build it off the constant so the
    # "no trip" boundary is deterministic, then go strictly below it to trip.
    edge = mean * (1 - HRV_CRASH_FRACTION)  # 36.0 = exactly 40 % below
    assert hrv_crash_reason(edge - 1, mean) == HRV_CRASH  # 35.0 ≈ 41.7 % below → trips
    assert hrv_crash_reason(edge - 1, mean) == "hrv_crash"


def test_hrv_crash_strict_does_not_fire_at_or_above_40pct():
    mean = 60.0
    edge = mean * (1 - HRV_CRASH_FRACTION)  # exactly 40 % below
    assert hrv_crash_reason(edge, mean) is None  # exactly 40 % below does NOT trip
    # 30 % below (a milder dip) does not trip
    assert hrv_crash_reason(mean * 0.70, mean) is None


def test_hrv_crash_null_or_nonpositive_baseline_skips():
    assert hrv_crash_reason(None, 60.0) is None
    assert hrv_crash_reason(20.0, None) is None  # day-one sparse baseline (DECISIONS 5)
    assert hrv_crash_reason(20.0, 0.0) is None  # no divide-by-zero (DECISIONS 5)
    assert hrv_crash_reason(20.0, -5.0) is None  # degenerate baseline


def test_hrv_crash_uses_rolling_mean_not_sd_zscore():
    # A "1 SD low but <40 % below" reading must NOT trip the crash (that's the §6.1
    # readiness term, E8·P1). With mean 60 and a reading 50 (≈16.7 % below), no trip.
    assert hrv_crash_reason(50.0, 60.0) is None


# --- collect_reasons (epic §3 — firing keys in the fixed MODELS order) ---


def test_collect_reasons_all_firing_in_fixed_order():
    # every reason fires: gi=1; sleep 3 h; illness=1; knee 5; rhr delta 15; hrv 50 % below
    reasons = collect_reasons(
        gi_symptoms=1,
        illness=1,
        knee_pain=5,
        sleep_h=3.0,
        rhr=70.0,
        rhr_30d_mean=55.0,
        hrv_sdnn=30.0,
        hrv_30d_mean=60.0,
    )
    assert reasons == _SIX_REASONS
    assert reasons == [
        "gi_flare",
        "sleep_below_4h",
        "illness",
        "knee_pain_high",
        "rhr_spike",
        "hrv_crash",
    ]


def test_collect_reasons_subset_preserves_relative_order():
    # only sleep + knee fire — they keep their relative MODELS order
    reasons = collect_reasons(
        gi_symptoms=0,
        illness=0,
        knee_pain=5,
        sleep_h=3.0,
        rhr=None,
        rhr_30d_mean=None,
        hrv_sdnn=None,
        hrv_30d_mean=None,
    )
    assert reasons == [SLEEP_BELOW_4H, KNEE_PAIN_HIGH]


def test_collect_reasons_none_firing_is_empty():
    reasons = collect_reasons(
        gi_symptoms=0,
        illness=0,
        knee_pain=0,
        sleep_h=8.0,
        rhr=55.0,
        rhr_30d_mean=55.0,
        hrv_sdnn=60.0,
        hrv_30d_mean=60.0,
    )
    assert reasons == []


# --- override_for (§6.2 per-reason cards + most-restrictive precedence) ---


def test_override_for_empty_is_none():
    assert override_for([]) is None


def test_override_for_single_reason_cards_match_constitution():
    # §6.2: illness / no-sleep → rest
    assert override_for([ILLNESS]) == WorkoutCard.rest
    assert override_for([SLEEP_BELOW_4H]) == WorkoutCard.rest
    # §6.2: red / no-impact → active_recovery (MODELS knee example)
    assert override_for([KNEE_PAIN_HIGH]) == WorkoutCard.active_recovery
    assert override_for([RHR_SPIKE]) == WorkoutCard.active_recovery
    assert override_for([HRV_CRASH]) == WorkoutCard.active_recovery
    # §6.2: lone GI flare → easy/mobility only
    assert override_for([GI_FLARE]) == WorkoutCard.mobility


def test_override_for_single_reason_cards_round_trip_to_wire_string():
    # WorkoutCard is a str-Enum: members equal their MODELS wire token
    assert override_for([ILLNESS]) == "rest"
    assert override_for([KNEE_PAIN_HIGH]) == "active_recovery"
    assert override_for([GI_FLARE]) == "mobility"


def test_override_for_multi_reason_most_restrictive_wins():
    # rest > active_recovery > mobility (DECISIONS 7)
    assert override_for([GI_FLARE, ILLNESS]) == WorkoutCard.rest
    assert override_for([GI_FLARE, KNEE_PAIN_HIGH]) == WorkoutCard.active_recovery
    assert override_for([KNEE_PAIN_HIGH, ILLNESS]) == WorkoutCard.rest


def test_override_for_returns_only_the_three_forced_cards_or_none():
    # every non-empty firing subset maps into the three-card universe (or None when empty)
    assert override_for([]) is None
    for reason in _SIX_REASONS:
        assert override_for([reason]) in _FORCED_CARDS
    assert override_for(_SIX_REASONS) in _FORCED_CARDS


# --- evaluate_safety_gate (epic §4 — each reason triggers with the correct overrideTo) ---


def test_evaluate_each_reason_triggers_with_correct_card():
    # gi_symptoms=1 → gi_flare / mobility
    g = evaluate_safety_gate(**{**_ALL_CLEAR, "gi_symptoms": 1})
    assert g.triggered is True
    assert g.reasons == (GI_FLARE,)
    assert g.overrideTo == WorkoutCard.mobility

    # sleep <4 h → sleep_below_4h / rest
    s = evaluate_safety_gate(**{**_ALL_CLEAR, "sleep_h": 3.0})
    assert s.triggered is True
    assert s.reasons == (SLEEP_BELOW_4H,)
    assert s.overrideTo == WorkoutCard.rest

    # illness=1 → illness / rest
    i = evaluate_safety_gate(**{**_ALL_CLEAR, "illness": 1})
    assert i.triggered is True
    assert i.reasons == (ILLNESS,)
    assert i.overrideTo == WorkoutCard.rest

    # knee 5 → knee_pain_high / active_recovery (MODELS triggered example)
    k = evaluate_safety_gate(**{**_ALL_CLEAR, "knee_pain": 5})
    assert k.triggered is True
    assert k.reasons == (KNEE_PAIN_HIGH,)
    assert k.overrideTo == WorkoutCard.active_recovery
    assert k.overrideTo == "active_recovery"  # MODELS wire token

    # rhr delta 15 → rhr_spike / active_recovery
    r = evaluate_safety_gate(**{**_ALL_CLEAR, "rhr": 70.0, "rhr_30d_mean": 55.0})
    assert r.triggered is True
    assert r.reasons == (RHR_SPIKE,)
    assert r.overrideTo == WorkoutCard.active_recovery

    # hrv 50 % below → hrv_crash / active_recovery
    h = evaluate_safety_gate(**{**_ALL_CLEAR, "hrv_sdnn": 30.0, "hrv_30d_mean": 60.0})
    assert h.triggered is True
    assert h.reasons == (HRV_CRASH,)
    assert h.overrideTo == WorkoutCard.active_recovery


def test_evaluate_no_reason_is_not_triggered():
    result = evaluate_safety_gate(**_ALL_CLEAR)
    assert result == SafetyGate(triggered=False, reasons=(), overrideTo=None)
    assert result.triggered is False
    assert result.reasons == ()
    assert result.overrideTo is None


def test_evaluate_triggered_equals_reasons_nonempty():
    # no reason
    assert _triggered_matches(evaluate_safety_gate(**_ALL_CLEAR))
    # single reason
    assert _triggered_matches(evaluate_safety_gate(**{**_ALL_CLEAR, "illness": 1}))
    # multi reason
    assert _triggered_matches(
        evaluate_safety_gate(**{**_ALL_CLEAR, "gi_symptoms": 1, "illness": 1})
    )


def _triggered_matches(result: SafetyGate) -> bool:
    return result.triggered == bool(result.reasons)


def test_evaluate_multi_reason_fixed_order_and_most_restrictive_card():
    result = evaluate_safety_gate(**{**_ALL_CLEAR, "gi_symptoms": 1, "illness": 1})
    assert result.triggered is True
    assert result.reasons == (GI_FLARE, ILLNESS)  # fixed MODELS order
    assert result.overrideTo == WorkoutCard.rest  # most restrictive (DECISIONS 7)


def test_evaluate_day_one_null_baselines_trips_on_flags_and_sleep_floor():
    # day-one athlete: null rolling baselines, but gi flare + <4 h sleep present
    result = evaluate_safety_gate(
        gi_symptoms=1,
        illness=0,
        knee_pain=0,
        sleep_h=3.0,
        rhr=80.0,
        rhr_30d_mean=None,  # sparse / day-one window (E6·P2)
        hrv_sdnn=10.0,
        hrv_30d_mean=None,  # sparse / day-one window
    )
    # trips on the check-in flag + the <4 h floor only — no spike/crash, no exception
    assert result.reasons == (GI_FLARE, SLEEP_BELOW_4H)
    assert RHR_SPIKE not in result.reasons
    assert HRV_CRASH not in result.reasons
    assert result.triggered is True
    assert result.overrideTo == WorkoutCard.rest  # sleep_below_4h forces rest


def test_evaluate_objective_only_signature_has_no_subjective_parameter():
    import inspect

    params = set(inspect.signature(evaluate_safety_gate).parameters)
    # exactly the three check-in flags + the five physiological values — nothing subjective
    assert params == {
        "gi_symptoms",
        "illness",
        "knee_pain",
        "sleep_h",
        "rhr",
        "rhr_30d_mean",
        "hrv_sdnn",
        "hrv_30d_mean",
    }
    assert not (params & {"energy", "soreness", "motivation", "mood"})


def test_safety_gate_result_has_exactly_the_three_models_fields():
    field_names = {f.name for f in dataclasses.fields(SafetyGate)}
    assert field_names == {"triggered", "reasons", "overrideTo"}
    # not the readiness shape — no score/band/penalties or any medical-diagnosis field
    assert not (field_names & {"score", "band", "penalties", "diagnosis", "medical"})


def test_evaluate_overrideto_always_in_the_card_universe_or_none():
    # all-clear → None; every single reason → one of the three forced cards
    assert evaluate_safety_gate(**_ALL_CLEAR).overrideTo is None
    for override in ("gi_symptoms", "illness"):
        card = evaluate_safety_gate(**{**_ALL_CLEAR, override: 1}).overrideTo
        assert card in _FORCED_CARDS


# --- Review round 1: override fails closed; SafetyGate enforces its invariants ---


def test_override_for_unknown_reason_fails_closed_to_rest():
    # A non-empty reasons list with an unrecognized key (schema drift / typo / future
    # reason) must fall to the MOST-restrictive card, never mobility (review #1/#3) —
    # including when MIXED with a known key that would otherwise map to a milder card.
    assert override_for(["some_future_reason"]) == WorkoutCard.rest
    assert override_for(["some_future_reason", GI_FLARE]) == WorkoutCard.rest
    assert override_for(["some_future_reason", KNEE_PAIN_HIGH]) == WorkoutCard.rest


def test_override_for_gi_flare_alone_is_mobility_explicit():
    # The gi_flare → mobility branch is explicit (not a catch-all): a known single reason.
    assert override_for([GI_FLARE]) == WorkoutCard.mobility
    assert override_for(()) is None


def test_safety_gate_coerces_reasons_to_immutable_tuple():
    g = evaluate_safety_gate(**{**_ALL_CLEAR, "gi_symptoms": 1})
    assert isinstance(g.reasons, tuple)
    # frozen + tuple → no in-place mutation of the snapshot
    with pytest.raises(AttributeError):
        g.reasons.append(ILLNESS)  # type: ignore[attr-defined]
    # constructing from a list still yields a tuple (coerced in __post_init__)
    built = SafetyGate(triggered=True, reasons=[GI_FLARE], overrideTo=WorkoutCard.mobility)
    assert built.reasons == (GI_FLARE,)
    assert isinstance(built.reasons, tuple)


def test_safety_gate_rejects_triggered_disagreeing_with_reasons():
    # triggered must equal bool(reasons) — desynced construction fails closed (review #2)
    with pytest.raises(ValueError, match="triggered"):
        SafetyGate(triggered=True, reasons=(), overrideTo=None)
    with pytest.raises(ValueError, match="triggered"):
        SafetyGate(triggered=False, reasons=(ILLNESS,), overrideTo=WorkoutCard.rest)


def test_safety_gate_rejects_stale_override():
    # overrideTo must be the mapped card for the reasons — a stale override fails (review #2)
    with pytest.raises(ValueError, match="overrideTo"):
        SafetyGate(triggered=True, reasons=(ILLNESS,), overrideTo=WorkoutCard.mobility)


def test_safety_gate_rejects_unknown_reason_key():
    # __post_init__ enforces the closed REASON_KEYS set — an undocumented machine key
    # cannot escape in reasons[] even though override_for fails closed to rest (review #3).
    with pytest.raises(ValueError, match="unknown"):
        SafetyGate(
            triggered=True,
            reasons=("some_future_reason",),
            overrideTo=WorkoutCard.rest,
        )
    # a valid known key still constructs fine
    ok = SafetyGate(triggered=True, reasons=(ILLNESS,), overrideTo=WorkoutCard.rest)
    assert ok.reasons == (ILLNESS,)


# --- Review round 4: tolerant strict float boundaries for RHR/HRV gates ---


def test_rhr_spike_exact_plus12_with_decimal_baseline_does_not_trip():
    # 67.4 - 55.4 = 12.000000000000007 in binary float, but mathematically exactly +12,
    # which is the strict no-trip boundary (review #4).
    assert rhr_spike_reason(67.4, 55.4) is None


def test_hrv_crash_exact_40pct_with_decimal_baseline_does_not_trip():
    # 33.7 * 0.6 = 20.220000000000002 in binary float; an HRV reading of exactly 20.22 is
    # exactly 40 % below (the strict no-trip boundary), so it must NOT trip (review #4).
    assert hrv_crash_reason(20.22, 33.7) is None
