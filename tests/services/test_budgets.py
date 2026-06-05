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
    DELOAD_VOLUME_FACTOR,
    HARD3_SLEEP_MIN_H,
    MAX_HARD_DAYS,
    RAMP_CAP,
    STRENGTH_SESSIONS,
    hard_day_budget,
    long_run_cap_km,
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


# --------------------------------------------------------------------------
# TASK-002 — long_run_cap_km (the §9 ≤10%/wk ramp cap + the deload down-ramp).
# --------------------------------------------------------------------------
def test_ramp_constants_match_constitution():
    assert RAMP_CAP == 1.10  # §9 "≤10%/wk increase"
    assert DELOAD_VOLUME_FACTOR == 0.60  # §5.1 deload "cut volume ~40 %"


def test_long_run_cap_none_history_is_none():
    # No prior history → unconstrained (MODELS longRunKm nullable; Decision 2).
    assert long_run_cap_km(None, deload=False) is None


def test_long_run_cap_tidy_prior_is_110_percent():
    # ×1.10 — the §4 "≤110% of the prior week".
    assert long_run_cap_km(10.0, deload=False) == 11.0


def test_long_run_cap_floor_rounds_non_tidy_prior_never_overshoots():
    # 10.05 × 1.10 = 11.055 → floors to 11.0, NOT round()-to-11.1 (review round-2 #3):
    # nearest-rounding would push the cap over 110 %, a >10%/wk jump (§8.3/§9).
    assert long_run_cap_km(10.05, deload=False) == 11.0


def test_long_run_cap_never_exceeds_110_percent_property():
    # The cap is a flat-feet safety ceiling — it must NEVER exceed prior × 1.10.
    for prior in (10.0, 10.05, 11.0, 28.0, 13.37):
        cap = long_run_cap_km(prior, deload=False)
        assert cap is not None
        assert cap <= prior * 1.10
        assert cap != prior  # never a raw-prior pass-through on a build week


def test_long_run_cap_deload_down_ramps_40_percent():
    # On a deload the long run is CUT ~40 % (§5.1), not ramped up (Decision 3).
    assert long_run_cap_km(10.0, deload=True) == 6.0


def test_long_run_cap_deload_none_history_is_none():
    # No history → still None on a deload, no fabricated cap (Decision 5).
    assert long_run_cap_km(None, deload=True) is None
