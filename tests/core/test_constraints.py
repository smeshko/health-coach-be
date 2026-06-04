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

import pytest

from app.core.constraints import (
    DAILY_RULES,
    WEEKLY_RULES,
    Severity,
    ValidationContext,
    Violation,
    WeeklyBudgets,
)
from app.core.enums import ReadinessBand, WorkoutCard

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
