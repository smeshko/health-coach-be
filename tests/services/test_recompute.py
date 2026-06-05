"""E5·P3 TASK-003: recompute seam — affected_dates fan-out + noop default.

E8·P5 (this phase) extends the SAME module with the four pure §10 monthly-recompute
helpers (cadence ramp, threshold↔VO₂ alternation, strength-test smoothing, zone
re-derivation). The seam tests above are preserved; the helper tests follow.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.api.schemas.sync import SyncRequest
from app.core.profile import Profile
from app.services.recompute import (
    CADENCE_RAMP_MIN_WEEKS,
    CADENCE_STEP_SPM,
    CadenceRamp,
    QualityFocus,
    affected_dates,
    next_quality_focus,
    noop_recompute,
    ramp_cadence,
    ramp_cadence_for,
)


def test_affected_dates_exact_sofia_union() -> None:
    request = SyncRequest.model_validate(
        {
            "records": [
                {
                    "uuid": "r1",
                    "type": "heart_rate",
                    "start": "2026-06-01T08:00:00+03:00",
                    "end": "2026-06-01T08:00:30+03:00",
                    "value": 57.0,
                    "unit": "count/min",
                }
            ],
            "workouts": [
                {
                    "uuid": "w1",
                    "type": "boxing",
                    "start": "2026-06-10T18:00:00+03:00",
                    "end": "2026-06-10T18:45:00+03:00",
                    "durationS": 2700.0,
                }
            ],
            "activitySummary": [
                {
                    "date": "2026-06-04",
                    "activeEnergyKcal": 620.0,
                    "exerciseMinutes": 48,
                    "standHours": 11,
                }
            ],
            "checkin": {"date": "2026-06-05", "giSymptoms": False, "kneePain": 0, "illness": False},
            "strengthTest": {"date": "2026-06-06", "maxPushups": 42, "maxPullups": 11},
        }
    )
    assert affected_dates(request) == {
        date(2026, 6, 1),
        date(2026, 6, 10),
        date(2026, 6, 4),
        date(2026, 6, 5),
        date(2026, 6, 6),
    }


def test_offset_crossing_start_buckets_to_sofia_date() -> None:
    # 23:30 UTC on 06-02 is 02:30 Sofia (EEST +03:00) on 06-03 → Sofia date wins.
    request = SyncRequest.model_validate(
        {
            "records": [
                {
                    "uuid": "r1",
                    "type": "heart_rate",
                    "start": "2026-06-02T23:30:00+00:00",
                    "end": "2026-06-02T23:30:30+00:00",
                    "value": 60.0,
                    "unit": "count/min",
                }
            ]
        }
    )
    result = affected_dates(request)
    assert result == {date(2026, 6, 3)}
    assert date(2026, 6, 2) not in result  # not the wire-offset date


def test_empty_body_returns_empty_set() -> None:
    assert affected_dates(SyncRequest.model_validate({})) == set()


def test_only_non_whitelisted_records_returns_empty_set() -> None:
    # respiratory_rate is a valid RecordType but not stored — it changes no day's
    # data, so it contributes no affected date.
    request = SyncRequest.model_validate(
        {
            "records": [
                {
                    "uuid": "r1",
                    "type": "respiratory_rate",
                    "start": "2026-06-02T08:00:00+03:00",
                    "end": "2026-06-02T08:00:30+03:00",
                    "value": 14.0,
                    "unit": "count/min",
                }
            ]
        }
    )
    assert affected_dates(request) == set()


def test_dedup_across_records_and_workouts() -> None:
    request = SyncRequest.model_validate(
        {
            "records": [
                {
                    "uuid": "r1",
                    "type": "heart_rate",
                    "start": "2026-06-01T08:00:00+03:00",
                    "end": "2026-06-01T08:00:30+03:00",
                    "value": 57.0,
                    "unit": "count/min",
                }
            ],
            "workouts": [
                {
                    "uuid": "w1",
                    "type": "running",
                    "start": "2026-06-01T18:00:00+03:00",
                    "end": "2026-06-01T18:30:00+03:00",
                    "durationS": 1800.0,
                }
            ],
        }
    )
    assert affected_dates(request) == {date(2026, 6, 1)}  # deduped


def test_noop_recompute_is_a_safe_no_op() -> None:
    assert noop_recompute(set()) is None
    assert noop_recompute({date(2026, 6, 1)}) is None


# ---------------------------------------------------------------------------
# E8·P5 — monthly recompute helpers
# ---------------------------------------------------------------------------


def _profile_with(*, cadence_current_spm: int, cadence_target_spm: int) -> Profile:
    """A minimal valid `Profile` carrying the given cadence anchors.

    Mirrors the `profile.yaml` fixture so the E3·P1 `Thresholds`/`Zones`/`Profile`
    validators run for real (the cadence invariant + `z5.high == max_hr`).
    """
    return Profile(
        athlete={"age": 34, "sex": "male", "height_cm": 174, "goal_weight_kg": 75},
        thresholds={
            "max_hr": 192,
            "rhr_baseline": 58,
            "hrv_baseline_ms": 38,
            "easy_hr_cap": 146,
            "cadence_target_spm": cadence_target_spm,
            "cadence_current_spm": cadence_current_spm,
        },
        zones={
            "z1": (96, 125),
            "z2": (125, 150),
            "z3": (150, 167),
            "z4": (167, 177),
            "z5": (177, 192),
        },
        nutrition={
            "activity_factor": 1.50,
            "deficit_pct": 0.12,
            "protein_g_per_kg": 1.8,
            "fat_g_per_kg_low": 0.8,
            "fat_g_per_kg_high": 1.0,
            "carbs_g_per_kg": {
                "hard_low": 4,
                "hard_high": 5,
                "moderate": 3,
                "rest_low": 2,
                "rest_high": 2.5,
            },
            "hydration_l_low": 3.0,
            "hydration_l_high": 3.5,
            "fiber_g_low": 25,
            "fiber_g_high": 35,
        },
        meta={
            "derived_from": "baseline.db",
            "computed_at": "2026-06-02",
            "constitution_version": "v1",
        },
    )


def test_constants_match_constitution() -> None:
    # §9 "+5 spm"; §9 "every 2–3 weeks" → the minimum-dwell lower edge is 2.
    assert CADENCE_STEP_SPM == 5
    assert CADENCE_RAMP_MIN_WEEKS == 2


@pytest.mark.parametrize("weeks", [0, 1])
def test_ramp_cadence_holds_within_dwell(weeks: int) -> None:
    # < 2 weeks since the last bump → hold (don't ramp every week — §3).
    result = ramp_cadence(current_spm=160, target_spm=172, weeks_since_last_bump=weeks)
    assert result == CadenceRamp(new_spm=160, bumped=False)


@pytest.mark.parametrize("weeks", [2, 3])
def test_ramp_cadence_bumps_after_dwell(weeks: int) -> None:
    # 2 or 3 weeks (the "2–3 weeks" window) → bump +5.
    result = ramp_cadence(current_spm=160, target_spm=172, weeks_since_last_bump=weeks)
    assert result == CadenceRamp(new_spm=165, bumped=True)


def test_ramp_cadence_clamps_at_target() -> None:
    # 169 + 5 = 174 > 172 → clamp to exactly 172 (never overshoot; E3·P1 invariant).
    result = ramp_cadence(current_spm=169, target_spm=172, weeks_since_last_bump=2)
    assert result == CadenceRamp(new_spm=172, bumped=True)


def test_ramp_cadence_holds_at_target() -> None:
    result = ramp_cadence(current_spm=172, target_spm=172, weeks_since_last_bump=3)
    assert result == CadenceRamp(new_spm=172, bumped=False)


def test_ramp_cadence_holds_over_target() -> None:
    # Defensive: an already-over-target input holds, never bumps further up.
    result = ramp_cadence(current_spm=175, target_spm=172, weeks_since_last_bump=3)
    assert result == CadenceRamp(new_spm=175, bumped=False)


@pytest.mark.parametrize(
    ("current", "target", "weeks"),
    [
        (160, 172, 0),
        (160, 172, 1),
        (160, 172, 2),
        (160, 172, 3),
        (169, 172, 2),
        (172, 172, 3),
        (170, 172, 2),
        (171, 172, 2),
    ],
)
def test_ramp_cadence_invariant_never_overshoots_target(
    current: int, target: int, weeks: int
) -> None:
    result = ramp_cadence(current_spm=current, target_spm=target, weeks_since_last_bump=weeks)
    assert result.new_spm <= target
    # A Profile carrying the new cue re-validates under the E3·P1 cadence invariant.
    profile = _profile_with(cadence_current_spm=result.new_spm, cadence_target_spm=target)
    assert profile.thresholds.cadence_current_spm == result.new_spm


def test_ramp_cadence_for_reads_live_profile() -> None:
    profile = _profile_with(cadence_current_spm=160, cadence_target_spm=172)
    via_profile = ramp_cadence_for(profile, weeks_since_last_bump=2)
    via_keyword = ramp_cadence(current_spm=160, target_spm=172, weeks_since_last_bump=2)
    assert via_profile == via_keyword == CadenceRamp(new_spm=165, bumped=True)


# --- TASK-002: quality alternation (threshold ↔ vo2) ---


def test_next_quality_focus_threshold_flips_to_vo2() -> None:
    assert next_quality_focus(QualityFocus.THRESHOLD) == QualityFocus.VO2


def test_next_quality_focus_vo2_flips_to_threshold() -> None:
    assert next_quality_focus(QualityFocus.VO2) == QualityFocus.THRESHOLD


def test_next_quality_focus_cold_start_defaults_to_threshold() -> None:
    # No prior plan (week one) → base-phase threshold, not VO₂ (DECISIONS 9).
    assert next_quality_focus(None) == QualityFocus.THRESHOLD


def test_next_quality_focus_is_an_involution() -> None:
    # threshold → vo2 → threshold: consecutive weeks never repeat a focus (§9).
    assert (
        next_quality_focus(next_quality_focus(QualityFocus.THRESHOLD)) == QualityFocus.THRESHOLD
    )
    assert next_quality_focus(next_quality_focus(QualityFocus.VO2)) == QualityFocus.VO2


def test_quality_focus_universe_is_exactly_two_lowercase_values() -> None:
    assert {f.value for f in QualityFocus} == {"threshold", "vo2"}
