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

import dataclasses
import inspect

from app.core.constraints import WeeklyBudgets as ValidatorWeeklyBudgets
from app.services.budgets import (
    BASE_HARD_DAYS,
    DELOAD_EVERY_N_WEEKS,
    DELOAD_HARD_DAYS,
    DELOAD_VOLUME_FACTOR,
    HARD3_SLEEP_MIN_H,
    MAX_HARD_DAYS,
    RAMP_CAP,
    STRENGTH_SESSIONS,
    UNDERRECOVERY_HRV_SD_BELOW,
    UNDERRECOVERY_MIN_SIGNALS,
    UNDERRECOVERY_RHR_DELTA_BPM,
    UNDERRECOVERY_SLEEP_MAX_H,
    WeeklyBudgets,
    compute_budgets,
    hard_day_budget,
    is_deload_week,
    long_run_cap_km,
    strength_sessions,
)
from app.api.schemas.base import CamelModel

# Subjective self-report parameters that must NEVER appear on the budget signature
# (objective-only discipline, parity with readiness/§11 data-contract).
_SUBJECTIVE_PARAMS = {"energy", "soreness", "motivation", "mood", "stress", "rpe"}


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


# --------------------------------------------------------------------------
# TASK-003 — is_deload_week + compute_budgets + the WeeklyBudgets result.
# --------------------------------------------------------------------------
def test_deload_constants_match_constitution():
    assert DELOAD_EVERY_N_WEEKS == 4  # §5.1/§9 "every 4th week"
    assert UNDERRECOVERY_SLEEP_MAX_H == 5.5  # §8.4 "7-day sleep <5.5 h"
    assert UNDERRECOVERY_RHR_DELTA_BPM == 7  # §8.4 "RHR >+7 bpm"
    assert UNDERRECOVERY_HRV_SD_BELOW == 1.0  # §8.4 "HRV >1 SD below baseline"
    assert UNDERRECOVERY_MIN_SIGNALS == 2  # §8.4 "any two"


def _calm_deload_kwargs(**overrides):
    """A non-firing baseline for is_deload_week — no cadence/GI/under-recovery signal."""
    base = dict(
        iso_week_index=0,
        sleep_avg_7d_h=8.0,
        hrv_avg_7d=60.0,
        hrv_30d_mean=60.0,
        hrv_30d_sd=5.0,
        rhr_avg_7d=50.0,
        rhr_30d_mean=50.0,
        gi_flare=False,
        extra_underrecovery_signals=0,
    )
    base.update(overrides)
    return base


def test_deload_cadence_fires_on_fourth_week_only():
    # The 4th week of each 0-based block is index 3/7/11 — (index + 1) % 4 == 0
    # (review round-1 #2 / Decision 8). It does NOT deload on week 1 (index 0).
    for idx in (3, 7, 11):
        assert is_deload_week(**_calm_deload_kwargs(iso_week_index=idx)) is True
    for idx in (0, 1, 2, 4):
        assert is_deload_week(**_calm_deload_kwargs(iso_week_index=idx)) is False


def test_deload_fires_on_gi_flare_non_cadence_week():
    # §5.3/§8.1 — any GI symptom logged → this is a deload week.
    assert is_deload_week(**_calm_deload_kwargs(iso_week_index=1, gi_flare=True)) is True


def test_deload_fires_on_any_two_underrecovery_signals():
    # §8.4 "any two": 7-day sleep 5.0 (<5.5) AND 7-day RHR +8 (>+7) → deload.
    two = _calm_deload_kwargs(
        iso_week_index=1, sleep_avg_7d_h=5.0, rhr_avg_7d=58.0, rhr_30d_mean=50.0
    )
    assert is_deload_week(**two) is True


def test_deload_does_not_fire_on_single_underrecovery_signal():
    # Only one signal (sleep <5.5) → not a deload (§8.4 needs ≥2).
    one = _calm_deload_kwargs(iso_week_index=1, sleep_avg_7d_h=5.0)
    assert is_deload_week(**one) is False


def test_deload_underrecovery_boundaries_are_strict():
    # §8.4 thresholds are STRICT: sleep == 5.5 / RHR Δ == +7 / HRV z == 1 SD do NOT fire.
    at_boundary = _calm_deload_kwargs(
        iso_week_index=1,
        sleep_avg_7d_h=5.5,  # not < 5.5
        rhr_avg_7d=57.0,
        rhr_30d_mean=50.0,  # Δ == +7, not > +7
        hrv_avg_7d=55.0,
        hrv_30d_mean=60.0,
        hrv_30d_sd=5.0,  # z == 1.0, not > 1.0
    )
    assert is_deload_week(**at_boundary) is False


def test_deload_hrv_signal_fires_when_strictly_more_than_one_sd_below():
    # HRV z = (60 - 53)/5 = 1.4 SD below > 1.0 → 1 signal; plus RHR +8 → 2 → deload.
    two = _calm_deload_kwargs(
        iso_week_index=1,
        hrv_avg_7d=53.0,
        hrv_30d_mean=60.0,
        hrv_30d_sd=5.0,
        rhr_avg_7d=58.0,
        rhr_30d_mean=50.0,
    )
    assert is_deload_week(**two) is True


def test_deload_none_inputs_not_counted_as_signals():
    # All under-recovery inputs None → no signal counted; not a deload (Decision 5).
    sparse = _calm_deload_kwargs(
        iso_week_index=1,
        sleep_avg_7d_h=None,
        hrv_avg_7d=None,
        hrv_30d_mean=None,
        hrv_30d_sd=None,
        rhr_avg_7d=None,
        rhr_30d_mean=None,
    )
    assert is_deload_week(**sparse) is False


def test_deload_extra_signals_combine_with_computed():
    # One computed signal (sleep <5.5) + one caller-supplied extra (soreness) → ≥2 → deload.
    combined = _calm_deload_kwargs(
        iso_week_index=1, sleep_avg_7d_h=5.0, extra_underrecovery_signals=1
    )
    assert is_deload_week(**combined) is True


def test_deload_hrv_zero_sd_does_not_crash_or_fire():
    # Degenerate baseline (sd <= 0) → no divide-by-zero, the HRV signal does not fire.
    degenerate = _calm_deload_kwargs(
        iso_week_index=1,
        hrv_avg_7d=10.0,
        hrv_30d_mean=60.0,
        hrv_30d_sd=0.0,
        sleep_avg_7d_h=5.0,  # one real signal — but HRV must not count → only 1 → no deload
    )
    assert is_deload_week(**degenerate) is False


def _normal_budget_kwargs(**overrides):
    base = dict(
        iso_week_index=1,
        sleep_avg_7d_h=7.0,
        hrv_avg_7d=60.0,
        hrv_30d_mean=60.0,
        hrv_30d_sd=5.0,
        rhr_avg_7d=50.0,
        rhr_30d_mean=50.0,
        gi_symptoms_this_week=False,
        prior_week_long_run_km=10.0,
        extra_underrecovery_signals=0,
    )
    base.update(overrides)
    return base


def test_compute_budgets_default_two_worked_example():
    # Normal week, HRV JUST BELOW baseline so the 3-day gate fails on one condition
    # (review round-3 #1) → {2, 2, 11.0, False}.
    out = compute_budgets(**_normal_budget_kwargs(hrv_avg_7d=59.0))
    assert out == WeeklyBudgets(
        hard_days=2, strength_sessions=2, long_run_km=11.0, deload=False
    )


def test_compute_budgets_three_gate_week():
    # All three gate conditions hold (sleep ≥6.5 AND HRV ≥ baseline AND no GI),
    # non-deload → hard_days == 3.
    out = compute_budgets(**_normal_budget_kwargs(sleep_avg_7d_h=7.5, hrv_avg_7d=60.0))
    assert out.hard_days == 3
    assert out.deload is False


def test_compute_budgets_deload_week_cadence():
    # Cadence deload (index 3) → 1 hard day, long run down-ramped 10.0 → 6.0,
    # deload True, strength still 2.
    out = compute_budgets(**_normal_budget_kwargs(iso_week_index=3))
    assert out == WeeklyBudgets(
        hard_days=1, strength_sessions=2, long_run_km=6.0, deload=True
    )


def test_compute_budgets_gi_deload_keeps_strength_two():
    # A GI flare forces a deload (1 hard day, down-ramped run) but strength STAYS 2
    # — it is never reduced on any deload (review round-1 #1).
    out = compute_budgets(**_normal_budget_kwargs(gi_symptoms_this_week=True))
    assert out.deload is True
    assert out.hard_days == 1
    assert out.strength_sessions == 2
    assert out.long_run_km == 6.0


def test_compute_budgets_sparse_week_fails_closed():
    # All aggregates None, no prior history, no GI/extra → the safe default, no exception.
    out = compute_budgets(
        iso_week_index=1,
        sleep_avg_7d_h=None,
        hrv_avg_7d=None,
        hrv_30d_mean=None,
        hrv_30d_sd=None,
        rhr_avg_7d=None,
        rhr_30d_mean=None,
        gi_symptoms_this_week=False,
        prior_week_long_run_km=None,
    )
    assert out == WeeklyBudgets(
        hard_days=2, strength_sessions=2, long_run_km=None, deload=False
    )


def test_weekly_budgets_has_exactly_four_fields():
    field_names = {f.name for f in dataclasses.fields(WeeklyBudgets)}
    assert field_names == {"hard_days", "strength_sessions", "long_run_km", "deload"}
    # No easyRatioTarget / cadence leak (those are WeeklyTargets'/E8·P5's).
    assert "easy_ratio_target" not in field_names
    assert not any("cadence" in n for n in field_names)


def test_weekly_budgets_is_the_validator_type():
    # The budget engine's output type IS the type the E7·P3 weekly validator reads
    # (app.core.constraints.WeeklyBudgets) — one canonical type, not two.
    assert WeeklyBudgets is ValidatorWeeklyBudgets


def test_weekly_budgets_serializes_to_camel_wire_keys():
    # The snake→camel mapping is REAL (three multi-word fields). Pin the wire keys via a
    # CamelModel round-trip (review round-1 #3): exactly hardDays/strengthSessions/
    # longRunKm/deload.
    class _WeeklyBudgetsWire(CamelModel):
        hard_days: int
        strength_sessions: int
        long_run_km: float | None
        deload: bool

    budgets = WeeklyBudgets(
        hard_days=2, strength_sessions=2, long_run_km=11.0, deload=False
    )
    wire = _WeeklyBudgetsWire.model_validate(budgets).model_dump(mode="json")
    assert set(wire) == {"hardDays", "strengthSessions", "longRunKm", "deload"}
    assert wire == {
        "hardDays": 2,
        "strengthSessions": 2,
        "longRunKm": 11.0,
        "deload": False,
    }


def test_compute_budgets_signature_is_objective_only():
    params = set(inspect.signature(compute_budgets).parameters)
    assert params & _SUBJECTIVE_PARAMS == set()
