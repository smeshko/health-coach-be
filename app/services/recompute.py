"""`daily_metrics` recompute SEAM (E5·P3 TASK-003) + the §10 monthly recompute helpers (E8·P5).

**Seam (E5·P3):** DB.md §6 says the `/sync` write path ends with "recompute
`daily_metrics` for affected dates" — but **computing** those values is E6. This module
ships the *seam*: the `RecomputeDailyMetrics` protocol E6's engine implements, a no-op
default, and the `affected_dates(...)` fan-out. The `/sync` route injects the provider,
so E6 swaps in the real engine by overriding the provider — no route change.

**Monthly recompute helpers (E8·P5):** the four pure §10 deterministic helpers the E10·P2
`RecomputeConstants` node calls — `ramp_cadence` (the +5-spm-/-2–3-wk cadence ramp),
`next_quality_focus` (the threshold↔VO₂ weekly flip), `smooth_strength_trend` (the
trend-smoothed push-up/pull-up KPI), and `rederive_zones` (re-run `compute_zones` when the
max-HR/RHR anchors move). Each takes already-resolved inputs (or a loaded `Profile`) and
**returns a value object** — it decides no staleness, merges into no `Profile`, and writes
**no** `profile.yaml` (that atomic write is the E10·P2 node's; ARCHITECTURE §5, epic §3).

Pure: no FastAPI/HTTP imports, no DB persistence, no LLM, no `profile.yaml` write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from app.api.schemas.sync import SyncRequest
from app.core.healthkit import filter_whitelisted_records
from app.core.profile import Profile
from app.core.time import to_sofia


@runtime_checkable
class RecomputeDailyMetrics(Protocol):
    """The recompute contract E6 implements. This phase ships a no-op default."""

    def __call__(self, dates: set[date]) -> None: ...


def noop_recompute(dates: set[date]) -> None:
    """Default seam implementation — does nothing (the engine is E6; DB.md §6)."""
    return None


def affected_dates(request: SyncRequest) -> set[date]:
    """The set of Europe/Sofia dates this sync changed — the recompute fan-out.

    Every touched datum is bucketed to its **Europe/Sofia** date (not the wire
    offset), so an offset that crosses the Sofia day boundary lands on the Sofia day
    (ARCHITECTURE §4). Only **whitelisted** records contribute (a non-whitelisted
    record is not stored, so it changes no day's data). Workouts and activity
    summaries are not type-gated, so all contribute. Returns a de-duplicated set,
    possibly empty (an empty body, or one whose only records are non-whitelisted).
    """
    dates: set[date] = set()
    for record in filter_whitelisted_records(request.records):
        dates.add(to_sofia(record.start).date())
    for workout in request.workouts:
        dates.add(to_sofia(workout.start).date())
    for summary in request.activity_summary:
        dates.add(summary.date)
    if request.checkin is not None:
        dates.add(request.checkin.date)
    if request.strength_test is not None:
        dates.add(request.strength_test.date)
    return dates


# ---------------------------------------------------------------------------
# E8·P5 — §10 monthly recompute helpers (pure; the E10·P2 node owns the write)
# ---------------------------------------------------------------------------

# --- Cadence ramp (constitution §3/§9; LLM §3; MODELS `cadenceSpm`) ---
# §9 "Cadence: +5 spm every 2–3 weeks until cadence_target_spm" — the per-step magnitude.
CADENCE_STEP_SPM = 5
# §9 "every 2–3 weeks" — the dwell gate's lower edge (the minimum weeks between bumps; the
# E10 node measures `weeks_since_last_bump`, this helper applies the rule — DECISIONS 7).
CADENCE_RAMP_MIN_WEEKS = 2


@dataclass(frozen=True)
class CadenceRamp:
    """The result of one cadence-ramp step.

    `bumped` is load-bearing for the E10 node: it distinguishes "held (too soon / at
    target)" from "advanced", so the node can reset its dwell counter (DECISIONS 8).
    """

    new_spm: int
    bumped: bool


def ramp_cadence(*, current_spm: int, target_spm: int, weeks_since_last_bump: int) -> CadenceRamp:
    """Advance `cadence_current_spm` by +5 toward target, gated + clamped (§3/§9).

    **Holds** (`bumped=False`, `new_spm == current_spm`) when already at/over the target
    (no overshoot — "until `cadence_target_spm`") **or** the dwell hasn't elapsed
    (`weeks_since_last_bump < CADENCE_RAMP_MIN_WEEKS` — "don't jump straight there", §3).
    Otherwise **bumps** `new_spm = min(current_spm + CADENCE_STEP_SPM, target_spm)` — the
    `min` clamps at the target (a 169→172 ramp lands on 172, not 174), so the output always
    satisfies the E3·P1 `Thresholds` invariant `cadence_current_spm <= cadence_target_spm`.
    Total: no exception on any int input (DECISIONS 6/7).
    """
    if current_spm >= target_spm or weeks_since_last_bump < CADENCE_RAMP_MIN_WEEKS:
        return CadenceRamp(new_spm=current_spm, bumped=False)
    new_spm = min(current_spm + CADENCE_STEP_SPM, target_spm)
    return CadenceRamp(new_spm=new_spm, bumped=True)


def ramp_cadence_for(profile: Profile, *, weeks_since_last_bump: int) -> CadenceRamp:
    """`ramp_cadence` reading the live anchors off a loaded `Profile` (pure — no write).

    A thin convenience adapter for the E10 node; reads
    `profile.thresholds.cadence_current_spm`/`cadence_target_spm` and returns the same
    `CadenceRamp` as the keyword form. Writes nothing (DECISIONS 4).
    """
    return ramp_cadence(
        current_spm=profile.thresholds.cadence_current_spm,
        target_spm=profile.thresholds.cadence_target_spm,
        weeks_since_last_bump=weeks_since_last_bump,
    )
