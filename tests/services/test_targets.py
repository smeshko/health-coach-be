"""Pure unit tests for ``compute_targets`` (E10·P2; MODELS ``WeeklyTargets``).

Table-driven, no DB/HTTP/LLM: the kernel is thin arithmetic over already-expanded
``PlannedSession``s (E7·P2), so every input is a hand-built session list + a fixture
``Profile``. Pins the MODELS worked example (``totalRunKm: 28.0``, ``easyRunRatio: 0.8``,
``strengthSessions: 2``, ``hardDays: 2``, ``cadenceSpm: 160``) and proves the cadence
cue tracks the **profile attribute**, never a literal.
"""

from __future__ import annotations

import copy

from app.core.enums import Intensity, Tier, WorkoutCard, Zone
from app.core.profile import Profile
from app.services.derive.plan import PlannedSession
from app.services.targets import EASY_PACE_MIN_PER_KM, compute_targets

from tests.core.test_profile import valid_profile_dict


def _profile(*, cadence_current_spm: int = 160) -> Profile:
    d = copy.deepcopy(valid_profile_dict())
    d["thresholds"]["cadence_current_spm"] = cadence_current_spm
    return Profile(**d)


def _session(
    card: WorkoutCard,
    *,
    intensity: Intensity,
    is_hard_day: bool,
    low: int | None = None,
    high: int | None = None,
    tier: Tier = Tier.core,
    zone: Zone | None = None,
) -> PlannedSession:
    return PlannedSession(
        card=card,
        tier=tier,
        intensity=intensity,
        is_hard_day=is_hard_day,
        suggested_day=None,
        zone_target=zone,
        duration_min_low=low,
        duration_min_high=high,
        flags=[],
    )


def _worked_example_sessions() -> list[PlannedSession]:
    """A session list reproducing the MODELS ``WeeklyTargets`` worked example.

    Run minutes: easy 40 + easy 94 + quality 34 = 168 → 28.0 km at 6.0 min/km;
    easy share 134/168 = 0.80. Two strength cards, two hard days.
    """
    return [
        _session(WorkoutCard.easy_run, intensity=Intensity.easy, is_hard_day=False, low=30, high=50),
        _session(WorkoutCard.easy_run, intensity=Intensity.easy, is_hard_day=False, low=80, high=108),
        _session(WorkoutCard.vo2, intensity=Intensity.quality, is_hard_day=True, low=24, high=44),
        _session(WorkoutCard.boxing, intensity=Intensity.quality, is_hard_day=True, low=60, high=90),
        _session(WorkoutCard.strength_push, intensity=Intensity.quality, is_hard_day=False, low=30, high=45),
        _session(WorkoutCard.strength_pull, intensity=Intensity.quality, is_hard_day=False, low=30, high=45),
    ]


def test_models_worked_example():
    targets = compute_targets(_worked_example_sessions(), _profile(cadence_current_spm=160))
    assert targets.total_run_km == 28.0
    assert targets.easy_run_ratio == 0.8
    assert targets.strength_sessions == 2
    assert targets.hard_days == 2
    assert targets.cadence_spm == 160


def test_cadence_spm_tracks_profile_attribute_not_a_literal():
    # The cue is read off the profile; a different profile yields a different cue.
    profile = _profile(cadence_current_spm=168)
    targets = compute_targets(_worked_example_sessions(), profile)
    assert targets.cadence_spm == 168
    assert targets.cadence_spm == profile.thresholds.cadence_current_spm


def test_total_run_km_uses_dose_midpoint_and_pace_model():
    # One easy_run, dose 30–50 (midpoint 40) → 40 / 6.0 = 6.67 km.
    sessions = [
        _session(WorkoutCard.easy_run, intensity=Intensity.easy, is_hard_day=False, low=30, high=50),
    ]
    targets = compute_targets(sessions, _profile())
    assert targets.total_run_km == round(40 / EASY_PACE_MIN_PER_KM, 1)
    assert targets.easy_run_ratio == 1.0


def test_no_run_card_yields_none_total_and_zero_ratio():
    # A week of only strength + rest cards: no run distance to sum.
    sessions = [
        _session(WorkoutCard.strength_push, intensity=Intensity.quality, is_hard_day=False, low=30, high=45),
        _session(WorkoutCard.rest, intensity=Intensity.recovery, is_hard_day=False),
    ]
    targets = compute_targets(sessions, _profile())
    assert targets.total_run_km is None
    assert targets.easy_run_ratio == 0.0
    assert targets.strength_sessions == 1
    assert targets.hard_days == 0


def test_run_card_without_dose_contributes_no_minutes():
    # A day-less, dose-less run pick (sequencing only) adds no km.
    sessions = [
        _session(WorkoutCard.easy_run, intensity=Intensity.easy, is_hard_day=False),
    ]
    targets = compute_targets(sessions, _profile())
    assert targets.total_run_km is None
    assert targets.easy_run_ratio == 0.0


def test_hard_days_counts_is_hard_day_flag():
    sessions = [
        _session(WorkoutCard.vo2, intensity=Intensity.quality, is_hard_day=True, low=25, high=45),
        _session(WorkoutCard.threshold, intensity=Intensity.quality, is_hard_day=True, low=30, high=50),
        _session(WorkoutCard.long_run, intensity=Intensity.easy, is_hard_day=False, low=60, high=90),
    ]
    targets = compute_targets(sessions, _profile())
    assert targets.hard_days == 2  # long_run is is_hard_day False (the two-axes rule)
