"""E8·P4 weekly-budget tests — pure table-driven unit tests (no session/TestClient/LLM).

Mirrors CONSTITUTION §5.1's worked points (2 hard days to start; 3 only when 7-day sleep
≥6.5 h AND the 7-day HRV avg ≥ the rolling baseline AND no GI; strength 2 protected as
core; long run progressed ≤10%/wk; deload every 4th week, cut volume ~40 % and drop to 1
hard day, also auto-triggered by §8.4 / a GI flare), §9 (≤10%/wk ramp + 4th-week deload),
and §8.4 (the "any two" under-recovery guardrail) — plus the epic §4 acceptance bundle and
the fail-closed / floor-rounding edges. Every input is a plain number — no DB row, no HTTP,
no LLM here (epic R6).
"""

from __future__ import annotations

from app.services.budgets import (
    BASE_HARD_DAYS,
    DELOAD_HARD_DAYS,
    HARD3_SLEEP_MIN_H,
    MAX_HARD_DAYS,
    STRENGTH_SESSIONS,
    hard_day_budget,
    strength_sessions,
)


# --------------------------------------------------------------------------
# Pinned constants transcribed from CONSTITUTION §5.1 (the hard-day gate).
# --------------------------------------------------------------------------
def test_hard_day_constants_match_constitution():
    assert BASE_HARD_DAYS == 2  # §5.1 "2 hard/quality days to start"
    assert MAX_HARD_DAYS == 3  # §5.1 "allow 3 only when …"
    assert DELOAD_HARD_DAYS == 1  # §5.1 deload "drop to 1 hard day"
    assert STRENGTH_SESSIONS == 2  # §5.1 strength "protected as core"
    assert HARD3_SLEEP_MIN_H == 6.5  # §5.1 "7-day avg sleep ≥6.5 h"


# --------------------------------------------------------------------------
# TASK-001 — hard_day_budget (the 3-day gate) + strength_sessions (constant 2).
# --------------------------------------------------------------------------
def test_hard_day_budget_three_when_all_gate_conditions_hold():
    # §5.1: 3 only when 7-day sleep ≥6.5 AND HRV ≥ baseline AND no GI.
    assert (
        hard_day_budget(
            sleep_avg_7d_h=7.0,
            hrv_avg_7d=50,
            hrv_30d_mean=50,
            gi_symptoms_this_week=False,
            deload=False,
        )
        == 3
    )


def test_hard_day_budget_three_at_inclusive_sleep_and_hrv_boundaries():
    # Sleep ≥6.5 is INCLUSIVE (exactly 6.5 qualifies); HRV "at/above" baseline is
    # inclusive (exactly == baseline qualifies). (§5.1)
    assert (
        hard_day_budget(
            sleep_avg_7d_h=6.5,
            hrv_avg_7d=50.0,
            hrv_30d_mean=50.0,
            gi_symptoms_this_week=False,
            deload=False,
        )
        == 3
    )


def test_hard_day_budget_two_when_sleep_below_threshold():
    # 6.4 h < 6.5 → upgrade denied.
    assert (
        hard_day_budget(
            sleep_avg_7d_h=6.4,
            hrv_avg_7d=50,
            hrv_30d_mean=50,
            gi_symptoms_this_week=False,
            deload=False,
        )
        == 2
    )


def test_hard_day_budget_two_when_hrv_below_baseline():
    # 49 < 50 → HRV below baseline → upgrade denied.
    assert (
        hard_day_budget(
            sleep_avg_7d_h=7.0,
            hrv_avg_7d=49,
            hrv_30d_mean=50,
            gi_symptoms_this_week=False,
            deload=False,
        )
        == 2
    )


def test_hard_day_budget_two_when_gi_symptoms_present():
    assert (
        hard_day_budget(
            sleep_avg_7d_h=7.0,
            hrv_avg_7d=50,
            hrv_30d_mean=50,
            gi_symptoms_this_week=True,
            deload=False,
        )
        == 2
    )


def test_hard_day_budget_one_on_deload_overrides_upgrade():
    # Deload forces 1 even when the gate inputs would otherwise grant 3 (Decision 3).
    assert (
        hard_day_budget(
            sleep_avg_7d_h=7.0,
            hrv_avg_7d=50,
            hrv_30d_mean=50,
            gi_symptoms_this_week=False,
            deload=True,
        )
        == 1
    )


def test_hard_day_budget_fails_closed_on_missing_inputs():
    # A None in any gate input → upgrade denied → 2, no exception (Decision 5).
    for kwargs in (
        {"sleep_avg_7d_h": None, "hrv_avg_7d": 50, "hrv_30d_mean": 50},
        {"sleep_avg_7d_h": 7.0, "hrv_avg_7d": None, "hrv_30d_mean": 50},
        {"sleep_avg_7d_h": 7.0, "hrv_avg_7d": 50, "hrv_30d_mean": None},
    ):
        assert (
            hard_day_budget(
                gi_symptoms_this_week=False,
                deload=False,
                **kwargs,
            )
            == 2
        )


def test_strength_sessions_is_always_two():
    # §5.1 "protected as core"; MODELS "protected at 2"; no deload/GI parameter lowers it.
    assert strength_sessions() == 2
