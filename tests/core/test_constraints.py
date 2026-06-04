"""Unit tests for ``app/core/constraints.py`` — the pure E7·P3 validators.

Pure tests: no DB/HTTP/LLM fixture. ``ValidationContext`` is hand-built and the
``out`` arguments are lightweight ``SimpleNamespace``-shaped picks (the
validators read them structurally, so the real MODELS ``*LLMOutput`` models work
once E9 passes them).

TASK-001 covers the value-type foundations (``Violation``/``Severity``/the
``WEEKLY_RULES``/``DAILY_RULES`` key sets/``ValidationContext``/``WeeklyBudgets``/
``ReadinessBand``). TASK-002/TASK-003 add the ``validate_daily``/``validate_weekly``
cases.
"""

import dataclasses
from types import SimpleNamespace

import pytest

from app.core.constraints import (
    DAILY_RULES,
    WEEKLY_RULES,
    Severity,
    ValidationContext,
    Violation,
    WeeklyBudgets,
    validate_daily,
    validate_weekly,
)
from app.core.enums import DayType, ReadinessBand, Weekday, WorkoutCard

C = WorkoutCard
D = Weekday

# --- Documented per-family rule-key sets (the closed contract, PLAN.md/TASK-001).
EXPECTED_WEEKLY_RULES = {
    "hard_day_count",
    "hard_day_spacing",
    "hard_run_after_boxing",
    "strength_count",
    "core_size",
    "extras_size",
    "long_run_count",
    "quality_run_mismatch",
    "deload_hard_cap",
    "dose_out_of_band",
}
EXPECTED_DAILY_RULES = {
    "card_not_in_plan",
    "red_requires_rest_card",
    "amber_full_intensity",
    "knee_impact_blocked",
    "dose_out_of_band",
    "day_type_below_floor",
    "too_many_alternatives",
}


# --------------------------------------------------------------------------
# TASK-001 — Severity / Violation / rule-key sets / ValidationContext.
# --------------------------------------------------------------------------
def test_severity_value_set_and_round_trip():
    assert {s.value for s in Severity} == {"hard", "soft"}
    assert Severity("hard") is Severity.hard
    assert Severity("soft") is Severity.soft
    assert isinstance(Severity.hard, str)
    assert Severity.hard == "hard"


def test_violation_is_frozen_with_default_hard_severity():
    v = Violation(rule="hard_day_count", message="too many hard days")
    assert v.rule == "hard_day_count"
    assert v.message == "too many hard days"
    assert v.severity is Severity.hard
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.rule = "other"  # type: ignore[misc]


def test_violation_equality():
    a = Violation(rule="core_size", message="core has 1 pick", severity=Severity.hard)
    b = Violation(rule="core_size", message="core has 1 pick", severity=Severity.hard)
    c = Violation(rule="core_size", message="different", severity=Severity.hard)
    assert a == b
    assert a != c


def test_weekly_and_daily_rule_key_sets_are_exact():
    assert WEEKLY_RULES == EXPECTED_WEEKLY_RULES
    assert DAILY_RULES == EXPECTED_DAILY_RULES


def test_rule_keys_are_unique_within_each_set():
    # frozensets dedupe; assert the documented lists had no dupes by size match.
    assert len(WEEKLY_RULES) == len(EXPECTED_WEEKLY_RULES)
    assert len(DAILY_RULES) == len(EXPECTED_DAILY_RULES)


def test_weekly_and_daily_share_only_dose_out_of_band():
    assert WEEKLY_RULES & DAILY_RULES == {"dose_out_of_band"}


def test_readiness_band_value_set():
    assert {b.value for b in ReadinessBand} == {"green", "amber", "red"}
    assert ReadinessBand("amber") is ReadinessBand.amber
    assert isinstance(ReadinessBand.green, str)


def test_weekly_budgets_is_frozen_and_round_trips():
    b = WeeklyBudgets(
        hard_days=2, strength_sessions=2, long_run_km=18.0, deload=False
    )
    assert b.hard_days == 2
    assert b.strength_sessions == 2
    assert b.long_run_km == 18.0
    assert b.deload is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        b.hard_days = 3  # type: ignore[misc]


def test_validation_context_is_frozen_and_round_trips():
    budgets = WeeklyBudgets(
        hard_days=2, strength_sessions=2, long_run_km=18.0, deload=False
    )
    ctx = ValidationContext(
        budgets=budgets,
        quality_run_pick=WorkoutCard.vo2,
        band=ReadinessBand.green,
        knee_pain=0,
        week_plan_cards=frozenset({WorkoutCard.easy_run}),
        safety_gate_triggered=False,
    )
    assert ctx.budgets is budgets
    assert ctx.quality_run_pick is WorkoutCard.vo2
    assert ctx.band is ReadinessBand.green
    assert ctx.knee_pain == 0
    assert ctx.week_plan_cards == frozenset({WorkoutCard.easy_run})
    assert ctx.safety_gate_triggered is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.knee_pain = 5  # type: ignore[misc]


# --------------------------------------------------------------------------
# TASK-002 — validate_daily. Lightweight structural builders (the validators
# read `out`/`pick` attributes structurally — duck-typed — so a SimpleNamespace
# stands in for the real MODELS DailyBriefLLMOutput / SessionPick).
# --------------------------------------------------------------------------
def _pick(card, low, high):
    return SimpleNamespace(
        card=card, duration_min_low=low, duration_min_high=high
    )


def _daily_out(session, day_type, alternatives=None):
    return SimpleNamespace(
        session=session,
        alternatives=list(alternatives or []),
        day_type=day_type,
    )


def _daily_ctx(
    *,
    band=ReadinessBand.green,
    knee_pain=0,
    week_plan_cards=frozenset({C.easy_run}),
):
    # budgets are weekly-only; supply a placeholder so the daily ctx is complete.
    return ValidationContext(
        budgets=WeeklyBudgets(
            hard_days=2, strength_sessions=2, long_run_km=18.0, deload=False
        ),
        quality_run_pick=None,
        band=band,
        knee_pain=knee_pain,
        week_plan_cards=week_plan_cards,
        safety_gate_triggered=False,
    )


def _rules(violations):
    return {v.rule for v in violations}


def test_daily_clean_session_returns_empty():
    # In-plan easy_run, green band, in-band dose (25–50), dayType not below
    # easy_run's (non-)floor, ≤2 alternatives → clean.
    out = _daily_out(_pick(C.easy_run, 30, 45), DayType.moderate)
    assert validate_daily(out, _daily_ctx()) == []


def test_daily_card_not_in_plan_flags_unrelated_card():
    out = _daily_out(_pick(C.boxing, 60, 90), DayType.hard)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.easy_run}))
    v = validate_daily(out, ctx)
    assert _rules(v) == {"card_not_in_plan"}


def test_daily_downgrade_substitute_of_planned_card_is_accepted():
    # vo2 is planned; steady_cardio is its DOWNGRADE_MAP[vo2].amber sub → accepted.
    out = _daily_out(_pick(C.steady_cardio, 30, 50), DayType.moderate)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.vo2}))
    assert validate_daily(out, ctx) == []


def test_daily_red_requires_rest_card_flags_non_rest():
    # easy_run is day_type=moderate, not rest → flags under RED.
    out = _daily_out(_pick(C.easy_run, 30, 45), DayType.moderate)
    ctx = _daily_ctx(band=ReadinessBand.red, week_plan_cards=frozenset({C.easy_run}))
    assert "red_requires_rest_card" in _rules(validate_daily(out, ctx))


def test_daily_red_rest_type_card_is_clean():
    # active_recovery is day_type=rest → clean under RED.
    out = _daily_out(_pick(C.active_recovery, 20, 40), DayType.rest)
    ctx = _daily_ctx(
        band=ReadinessBand.red, week_plan_cards=frozenset({C.active_recovery})
    )
    assert validate_daily(out, ctx) == []


def test_daily_amber_blocks_vo2():
    out = _daily_out(_pick(C.vo2, 25, 45), DayType.hard)
    ctx = _daily_ctx(band=ReadinessBand.amber, week_plan_cards=frozenset({C.vo2}))
    assert "amber_full_intensity" in _rules(validate_daily(out, ctx))


def test_daily_amber_blocks_z5_card():
    # hiit targets Zone.z5 (and is not vo2) → still blocked under AMBER.
    out = _daily_out(_pick(C.hiit, 15, 25), DayType.hard)
    ctx = _daily_ctx(band=ReadinessBand.amber, week_plan_cards=frozenset({C.hiit}))
    assert "amber_full_intensity" in _rules(validate_daily(out, ctx))


def test_daily_vo2_under_green_is_clean_for_amber_rule():
    out = _daily_out(_pick(C.vo2, 25, 45), DayType.hard)
    ctx = _daily_ctx(band=ReadinessBand.green, week_plan_cards=frozenset({C.vo2}))
    assert "amber_full_intensity" not in _rules(validate_daily(out, ctx))


def test_daily_knee_blocks_impact_flag_card():
    # easy_run carries Flag.impact → blocked at knee_pain=5.
    out = _daily_out(_pick(C.easy_run, 30, 45), DayType.moderate)
    ctx = _daily_ctx(knee_pain=5, week_plan_cards=frozenset({C.easy_run}))
    assert "knee_impact_blocked" in _rules(validate_daily(out, ctx))


def test_daily_knee_does_not_block_low_impact_boxing():
    # boxing is Impact.low but carries NO Flag.impact → not knee-blocked
    # (the gate keys on the flag, not the column — E7·P1 round-1#1).
    out = _daily_out(_pick(C.boxing, 60, 90), DayType.hard)
    ctx = _daily_ctx(knee_pain=5, week_plan_cards=frozenset({C.boxing}))
    assert "knee_impact_blocked" not in _rules(validate_daily(out, ctx))


def test_daily_knee_does_not_block_strength_lower():
    out = _daily_out(_pick(C.strength_lower, 25, 35), DayType.moderate)
    ctx = _daily_ctx(knee_pain=5, week_plan_cards=frozenset({C.strength_lower}))
    assert "knee_impact_blocked" not in _rules(validate_daily(out, ctx))


def test_daily_dose_over_band_flags():
    # easy_run band is 25–50; 60 high is over.
    out = _daily_out(_pick(C.easy_run, 30, 60), DayType.moderate)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.easy_run}))
    assert "dose_out_of_band" in _rules(validate_daily(out, ctx))


def test_daily_dose_under_band_flags():
    # easy_run band is 25–50; 10 low is under.
    out = _daily_out(_pick(C.easy_run, 10, 20), DayType.moderate)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.easy_run}))
    assert "dose_out_of_band" in _rules(validate_daily(out, ctx))


def test_daily_long_run_open_ended_high_is_clean():
    # long_run has dose_min_high None → only the low bound (60) applies; 95 ok.
    out = _daily_out(_pick(C.long_run, 90, 95), DayType.hard)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.long_run}))
    assert "dose_out_of_band" not in _rules(validate_daily(out, ctx))


def test_daily_rest_nonzero_dose_flags():
    # rest band is (0,0); any non-zero dose is out of band.
    out = _daily_out(_pick(C.rest, 0, 10), DayType.rest)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.rest}))
    assert "dose_out_of_band" in _rules(validate_daily(out, ctx))


def test_daily_rest_zero_dose_is_clean():
    out = _daily_out(_pick(C.rest, 0, 0), DayType.rest)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.rest}))
    assert validate_daily(out, ctx) == []


def test_daily_fuel_floor_rejects_rest_on_hard_card():
    # vo2 floors dayType at hard; dayType=rest is under-fuelling.
    out = _daily_out(_pick(C.vo2, 25, 45), DayType.rest)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.vo2}))
    assert "day_type_below_floor" in _rules(validate_daily(out, ctx))


def test_daily_fuel_floor_rejects_moderate_on_long_run():
    out = _daily_out(_pick(C.long_run, 70, 90), DayType.moderate)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.long_run}))
    assert "day_type_below_floor" in _rules(validate_daily(out, ctx))


def test_daily_fuel_floor_accepts_hard_on_hard_card():
    out = _daily_out(_pick(C.vo2, 25, 45), DayType.hard)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.vo2}))
    assert "day_type_below_floor" not in _rules(validate_daily(out, ctx))


def test_daily_fuel_floor_does_not_fire_for_non_floor_card():
    # easy_run does not floor — any dayType (even rest) is clean for the floor rule.
    out = _daily_out(_pick(C.easy_run, 30, 45), DayType.rest)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.easy_run}))
    assert "day_type_below_floor" not in _rules(validate_daily(out, ctx))


def test_daily_too_many_alternatives_flags_three():
    alts = [
        _pick(C.steady_cardio, 30, 50),
        _pick(C.active_recovery, 20, 40),
        _pick(C.mobility, 10, 30),
    ]
    out = _daily_out(_pick(C.easy_run, 30, 45), DayType.moderate, alternatives=alts)
    ctx = _daily_ctx(
        week_plan_cards=frozenset(
            {C.easy_run, C.steady_cardio, C.active_recovery, C.mobility}
        )
    )
    assert "too_many_alternatives" in _rules(validate_daily(out, ctx))


def test_daily_two_alternatives_is_clean():
    alts = [_pick(C.steady_cardio, 30, 50), _pick(C.active_recovery, 20, 40)]
    out = _daily_out(_pick(C.easy_run, 30, 45), DayType.moderate, alternatives=alts)
    ctx = _daily_ctx(
        week_plan_cards=frozenset({C.easy_run, C.steady_cardio, C.active_recovery})
    )
    assert validate_daily(out, ctx) == []


def test_daily_offending_alternative_dose_flags():
    # primary is clean; an alternative is out-of-band → dose_out_of_band fires.
    alts = [_pick(C.easy_run, 30, 90)]  # over band 25–50
    out = _daily_out(_pick(C.easy_run, 30, 45), DayType.moderate, alternatives=alts)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.easy_run}))
    assert "dose_out_of_band" in _rules(validate_daily(out, ctx))


def test_daily_offending_alternative_impact_under_knee_flags():
    # primary boxing (no impact flag) clean for knee; an alt easy_run has impact.
    alts = [_pick(C.easy_run, 30, 45)]
    out = _daily_out(_pick(C.boxing, 60, 90), DayType.hard, alternatives=alts)
    ctx = _daily_ctx(
        knee_pain=5, week_plan_cards=frozenset({C.boxing, C.easy_run})
    )
    assert "knee_impact_blocked" in _rules(validate_daily(out, ctx))


def test_daily_multiple_breaks_return_multiple_violations():
    # vo2 not in plan + dayType=rest under floor → ≥2 violations.
    out = _daily_out(_pick(C.vo2, 25, 45), DayType.rest)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.easy_run}))
    v = validate_daily(out, ctx)
    assert len(v) >= 2
    assert {"card_not_in_plan", "day_type_below_floor"} <= _rules(v)


def test_daily_every_emitted_rule_is_in_daily_rules():
    # Drive several breaks and confirm all emitted rules are pinned.
    out = _daily_out(_pick(C.vo2, 5, 200), DayType.rest)
    ctx = _daily_ctx(
        band=ReadinessBand.amber, knee_pain=5, week_plan_cards=frozenset({C.easy_run})
    )
    v = validate_daily(out, ctx)
    assert _rules(v) <= DAILY_RULES


def test_daily_validators_never_raise():
    out = _daily_out(_pick(C.vo2, 25, 45), DayType.rest)
    ctx = _daily_ctx(week_plan_cards=frozenset({C.easy_run}))
    # Must return a list, not raise.
    assert isinstance(validate_daily(out, ctx), list)


# --------------------------------------------------------------------------
# TASK-003 — validate_weekly. A weekly pick carries card + an optional
# suggestedDay + an optional dose; the validator reads them structurally.
# --------------------------------------------------------------------------
def _wpick(card, day=None, low=None, high=None):
    return SimpleNamespace(
        card=card, suggested_day=day, duration_min_low=low, duration_min_high=high
    )


def _weekly_out(core, extras):
    return SimpleNamespace(core=list(core), extras=list(extras))


def _weekly_ctx(
    *,
    hard_days=2,
    strength_sessions=2,
    long_run_km=18.0,
    deload=False,
    quality_run_pick=None,
):
    return ValidationContext(
        budgets=WeeklyBudgets(
            hard_days=hard_days,
            strength_sessions=strength_sessions,
            long_run_km=long_run_km,
            deload=deload,
        ),
        quality_run_pick=quality_run_pick,
    )


def _clean_weekly():
    # 3 core + 2 extras (5 picks): 2 hard non-adjacent (boxing tue, vo2 fri),
    # 2 strength (strength_pull, strength_lower), 1 easy_run. All in-band.
    core = [
        _wpick(C.boxing, D.tue, 60, 90),
        _wpick(C.vo2, D.fri, 25, 45),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.wed, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    return _weekly_out(core, extras)


def test_weekly_clean_plan_returns_empty():
    out = _clean_weekly()
    ctx = _weekly_ctx(
        hard_days=2, strength_sessions=2, quality_run_pick=C.vo2
    )
    assert validate_weekly(out, ctx) == []


def test_weekly_hard_day_count_flags_three_hard():
    # 3 hard (boxing, vo2, threshold) with hard_days=2.
    core = [
        _wpick(C.boxing, D.mon, 60, 90),
        _wpick(C.vo2, D.wed, 25, 45),
        _wpick(C.threshold, D.fri, 30, 50),
    ]
    extras = [
        _wpick(C.strength_pull, D.tue, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    # threshold & vo2 mismatch quality pick — assert hard_day_count present.
    assert "hard_day_count" in _rules(validate_weekly(_weekly_out(core, extras), ctx))


def test_weekly_long_run_not_counted_as_hard():
    # long_run (is_hard=False) + 2 genuine hard under hard_days=2 → clean count.
    core = [
        _wpick(C.boxing, D.mon, 60, 90),
        _wpick(C.vo2, D.wed, 25, 45),
        _wpick(C.long_run, D.sat, 70, 90),
    ]
    extras = [
        _wpick(C.strength_pull, D.tue, 30, 45),
        _wpick(C.strength_lower, D.fri, 25, 35),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    assert "hard_day_count" not in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_spacing_flags_adjacent_hard():
    # boxing tue + vo2 wed → adjacent hard.
    core = [
        _wpick(C.boxing, D.tue, 60, 90),
        _wpick(C.vo2, D.wed, 25, 45),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.mon, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    assert "hard_day_spacing" in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_spacing_non_adjacent_is_clean():
    # tue + thu → not adjacent.
    core = [
        _wpick(C.boxing, D.tue, 60, 90),
        _wpick(C.vo2, D.thu, 25, 45),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.mon, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    assert "hard_day_spacing" not in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_spacing_no_sun_mon_wrap():
    # vo2 sun + boxing mon → not adjacent (no wrap; a plan is one ISO week).
    core = [
        _wpick(C.vo2, D.sun, 25, 45),
        _wpick(C.boxing, D.mon, 60, 90),
        _wpick(C.easy_run, D.wed, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.tue, 30, 45),
        _wpick(C.strength_lower, D.fri, 25, 35),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    assert "hard_day_spacing" not in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_spacing_skips_dayless_hard_pick_without_error():
    # Two hard picks, one with suggestedDay=None → excluded from spacing; no error.
    core = [
        _wpick(C.boxing, None, 60, 90),
        _wpick(C.vo2, D.wed, 25, 45),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.mon, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    v = validate_weekly(_weekly_out(core, extras), ctx)
    assert "hard_day_spacing" not in _rules(v)


def test_weekly_hard_run_after_boxing_flags():
    # boxing mon + threshold tue (a hard run: is_hard + Flag.impact) the day after.
    core = [
        _wpick(C.boxing, D.mon, 60, 90),
        _wpick(C.threshold, D.tue, 30, 50),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.thu, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.threshold)
    assert "hard_run_after_boxing" in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_boxing_then_non_run_hard_is_clean_for_after_boxing():
    # boxing mon + hiit tue (hiit is is_hard but NOT a run — no Flag.impact).
    core = [
        _wpick(C.boxing, D.mon, 60, 90),
        _wpick(C.hiit, D.tue, 15, 25),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.thu, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    # hiit + boxing = 2 hard adjacent → spacing will fire, but after_boxing must not.
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2)
    assert "hard_run_after_boxing" not in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_strength_count_over_flags():
    # 3 strength with strength_sessions=2.
    core = [
        _wpick(C.vo2, D.wed, 25, 45),
        _wpick(C.strength_push, D.mon, 30, 45),
        _wpick(C.strength_pull, D.thu, 30, 45),
    ]
    extras = [
        _wpick(C.strength_lower, D.sat, 25, 35),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    assert "strength_count" in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_strength_count_under_flags():
    # 1 strength with strength_sessions=2 (== check, so under flags too).
    core = [
        _wpick(C.boxing, D.tue, 60, 90),
        _wpick(C.vo2, D.fri, 25, 45),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.wed, 30, 45),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    assert "strength_count" in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_core_size_too_small_flags():
    core = [_wpick(C.vo2, D.wed, 25, 45)]  # 1 < 2
    extras = [
        _wpick(C.strength_pull, D.mon, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    assert "core_size" in _rules(validate_weekly(_weekly_out(core, extras), ctx))


def test_weekly_core_size_too_large_flags():
    core = [
        _wpick(C.boxing, D.tue, 60, 90),
        _wpick(C.vo2, D.fri, 25, 45),
        _wpick(C.easy_run, D.sun, 30, 45),
        _wpick(C.steady_cardio, D.mon, 30, 50),
    ]  # 4 > 3
    extras = [
        _wpick(C.strength_pull, D.wed, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    assert "core_size" in _rules(validate_weekly(_weekly_out(core, extras), ctx))


def test_weekly_extras_size_too_small_flags():
    core = [
        _wpick(C.boxing, D.tue, 60, 90),
        _wpick(C.vo2, D.fri, 25, 45),
        _wpick(C.strength_pull, D.wed, 30, 45),
    ]
    extras = []  # 0 < 1
    ctx = _weekly_ctx(hard_days=2, strength_sessions=1, quality_run_pick=C.vo2)
    assert "extras_size" in _rules(validate_weekly(_weekly_out(core, extras), ctx))


def test_weekly_extras_size_too_large_flags():
    core = [
        _wpick(C.boxing, D.tue, 60, 90),
        _wpick(C.vo2, D.fri, 25, 45),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.wed, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
        _wpick(C.steady_cardio, D.mon, 30, 50),
    ]  # 3 > 2
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    assert "extras_size" in _rules(validate_weekly(_weekly_out(core, extras), ctx))


def test_weekly_long_run_count_flags_two():
    core = [
        _wpick(C.long_run, D.tue, 70, 90),
        _wpick(C.long_run, D.fri, 70, 90),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.wed, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2)
    assert "long_run_count" in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_one_long_run_is_clean_for_count():
    core = [
        _wpick(C.long_run, D.tue, 70, 90),
        _wpick(C.vo2, D.fri, 25, 45),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.wed, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    assert "long_run_count" not in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_quality_run_mismatch_flags():
    # vo2 picked but quality_run_pick is threshold.
    core = [
        _wpick(C.boxing, D.tue, 60, 90),
        _wpick(C.vo2, D.fri, 25, 45),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.wed, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(
        hard_days=2, strength_sessions=2, quality_run_pick=C.threshold
    )
    assert "quality_run_mismatch" in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_quality_run_match_is_clean():
    out = _clean_weekly()
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    assert "quality_run_mismatch" not in _rules(validate_weekly(out, ctx))


def test_weekly_quality_run_none_never_flags():
    out = _clean_weekly()
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=None)
    assert "quality_run_mismatch" not in _rules(validate_weekly(out, ctx))


def test_weekly_deload_hard_cap_flags_two_hard():
    # 2 hard on a deload week → deload_hard_cap (distinct from hard_day_count).
    core = [
        _wpick(C.boxing, D.tue, 60, 90),
        _wpick(C.vo2, D.fri, 25, 45),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.wed, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(
        hard_days=2, strength_sessions=2, deload=True, quality_run_pick=C.vo2
    )
    v = _rules(validate_weekly(_weekly_out(core, extras), ctx))
    assert "deload_hard_cap" in v
    # hard_days=2 so hard_day_count must NOT fire — only the deload cap.
    assert "hard_day_count" not in v


def test_weekly_deload_one_hard_is_clean():
    core = [
        _wpick(C.vo2, D.fri, 25, 45),
        _wpick(C.easy_run, D.sun, 30, 45),
        _wpick(C.steady_cardio, D.mon, 30, 50),
    ]
    extras = [
        _wpick(C.strength_pull, D.wed, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(
        hard_days=2, strength_sessions=2, deload=True, quality_run_pick=C.vo2
    )
    assert "deload_hard_cap" not in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_dose_out_of_band_flags():
    # vo2 dose 25–90 is over band (25–45).
    core = [
        _wpick(C.boxing, D.tue, 60, 90),
        _wpick(C.vo2, D.fri, 25, 90),
        _wpick(C.easy_run, D.sun, 30, 45),
    ]
    extras = [
        _wpick(C.strength_pull, D.wed, 30, 45),
        _wpick(C.strength_lower, D.sat, 25, 35),
    ]
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2, quality_run_pick=C.vo2)
    assert "dose_out_of_band" in _rules(
        validate_weekly(_weekly_out(core, extras), ctx)
    )


def test_weekly_multiple_breaks_return_multiple_violations():
    # 3 hard (count) + adjacent (spacing) + wrong core size, etc.
    core = [_wpick(C.vo2, D.mon, 25, 45)]  # core too small + hard count contributes
    extras = [_wpick(C.threshold, D.tue, 30, 50)]  # adjacent hard
    ctx = _weekly_ctx(hard_days=1, strength_sessions=2, quality_run_pick=C.vo2)
    v = validate_weekly(_weekly_out(core, extras), ctx)
    assert len(v) >= 2


def test_weekly_every_emitted_rule_is_in_weekly_rules():
    core = [_wpick(C.vo2, D.mon, 5, 200)]
    extras = [_wpick(C.threshold, D.tue, 30, 50)]
    ctx = _weekly_ctx(
        hard_days=1, strength_sessions=2, deload=True, quality_run_pick=C.threshold
    )
    v = validate_weekly(_weekly_out(core, extras), ctx)
    assert _rules(v) <= WEEKLY_RULES


def test_weekly_validators_never_raise():
    out = _weekly_out([_wpick(C.vo2, None, 25, 45)], [])
    ctx = _weekly_ctx(hard_days=2, strength_sessions=2)
    assert isinstance(validate_weekly(out, ctx), list)
