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

**Runtime measured max-HR source (Phase 19.6):** `measured_max_hr` supplies the runtime
anchor `rederive_zones` re-derives from — a read-only, `session`-scoped `func.max` over the
`records` table (the ONE DB read this module hosts, alongside the otherwise-pure helpers).

Otherwise pure: no FastAPI/HTTP imports, no DB **writes**, no LLM, no `profile.yaml` write.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas.sync import SyncRequest
from app.core.healthkit import RECORD_TYPE_TO_HK, filter_whitelisted_records
from app.core.profile import Profile
from app.core.time import to_sofia
from app.database.models import Records
from scripts.compute_zones import compute_zones


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


# --- Quality alternation (constitution §9; LLM §3 "deterministic flip off last week") ---


class QualityFocus(StrEnum):
    """The weekly run-quality kind — the closed two-value set §9 alternates between.

    Lowercase wire values (`"threshold"`/`"vo2"`) match the docs; fed to the LLM as a
    fixed constraint (LLM §3), never computed by it (DECISIONS 8).
    """

    THRESHOLD = "threshold"
    VO2 = "vo2"


def next_quality_focus(last_week: QualityFocus | None) -> QualityFocus:
    """Flip the weekly quality focus off last week's plan (§9; LLM §3).

    A pure, stateless **involution**: `threshold → vo2`, `vo2 → threshold`. A cold start
    (`last_week is None` — no prior plan to flip off) opens on `THRESHOLD`, the milder,
    base-phase quality day (§3 prioritises aerobic base before top-end VO₂; DECISIONS 9).
    Total + exhaustive over the enum.
    """
    if last_week is QualityFocus.THRESHOLD:
        return QualityFocus.VO2
    if last_week is QualityFocus.VO2:
        return QualityFocus.THRESHOLD
    return QualityFocus.THRESHOLD


# --- Strength-test trend smoothing (constitution §9/§10 "trend-smoothed") ---
# §10 is the **monthly** recompute over a **weekly** test → ~4 tests/window; the trailing
# SMA over the last `span` present weeks is transparent + exactly reproducible (DECISIONS 2).
STRENGTH_SMOOTH_SPAN = 4
# A smoothed mean is a float; a sub-rep wobble (e.g. +0.25 rep) is noise, not a trend, so the
# direction only fires `up`/`down` beyond a ±0.5-rep dead-band — else `flat` (DECISIONS 3).
STRENGTH_FLAT_EPS = 0.5

# The smoothed window mean is a float, so an exact ±eps boundary can land a hair off after
# binary float arithmetic. The dead-band OWNS its edge (an exact ±eps delta is `flat`), so
# `up`/`down` use STRICT tolerant comparisons — matching readiness.py/safety_gate.py/budgets.py.
_BOUNDARY_REL_TOL = 1e-9
_BOUNDARY_ABS_TOL = 1e-12


def _at_boundary(value: float, boundary: float) -> bool:
    """``value`` equals ``boundary`` within float noise."""
    return math.isclose(value, boundary, rel_tol=_BOUNDARY_REL_TOL, abs_tol=_BOUNDARY_ABS_TOL)


def _strictly_above(value: float, boundary: float) -> bool:
    """``value > boundary``, but an exact boundary (within float noise) is **not** above."""
    return value > boundary and not _at_boundary(value, boundary)


def _strictly_below(value: float, boundary: float) -> bool:
    """``value < boundary``, but an exact boundary (within float noise) is **not** below."""
    return value < boundary and not _at_boundary(value, boundary)


@dataclass(frozen=True)
class StrengthPoint:
    """One metric's weekly max for a single ISO week.

    `value is None` = a missed test that week (`strength_tests.max_*` is nullable) — "no
    data", dropped before smoothing, **never** read as 0 reps (DECISIONS 10).
    """

    iso_week: str
    value: int | None


@dataclass(frozen=True)
class StrengthTrend:
    """The smoothed trend for one metric: the smoothed latest level + a direction.

    `smoothed`/`direction` are `None` and `n == 0` for an empty / all-missing series (the
    function is total — no exception on no data; DECISIONS 10).
    """

    smoothed: float | None
    direction: Literal["up", "flat", "down"] | None
    n: int


def smooth_strength_trend(
    series: list[StrengthPoint], *, span: int = STRENGTH_SMOOTH_SPAN
) -> StrengthTrend:
    """Smooth one metric's noisy weekly max into a trend value + direction (§9/§10).

    Orders by `iso_week`, **drops** missed (`None`) weeks (a missed test ≠ 0 reps —
    DECISIONS 10), then takes a **trailing simple moving average** over the last `span`
    present weeks as the smoothed level (DECISIONS 2). `direction` compares that window
    against the prior `span`-week window with the `STRENGTH_FLAT_EPS` dead-band — `up`
    beyond +eps, `down` beyond −eps, else `flat` (a sub-rep wobble is `flat`, not noise;
    DECISIONS 3); with no prior window to compare → `flat`. An empty / all-`None` series →
    a null trend `(None, None, 0)`. Operates on **one** metric; the E10 node runs it once
    per metric (`max_pushups`, `max_pullups`).
    """
    present = [
        point.value
        for point in sorted(series, key=lambda p: p.iso_week)
        if point.value is not None
    ]
    if not present:
        return StrengthTrend(smoothed=None, direction=None, n=0)

    window = present[-span:]
    smoothed = statistics.mean(window)

    prior = present[-2 * span : -span]
    if prior:
        delta = smoothed - statistics.mean(prior)
        if _strictly_above(delta, STRENGTH_FLAT_EPS):
            direction: Literal["up", "flat", "down"] = "up"
        elif _strictly_below(delta, -STRENGTH_FLAT_EPS):
            direction = "down"
        else:
            direction = "flat"
    else:
        # No prior window (only the current one) — nothing to trend against yet.
        direction = "flat"

    return StrengthTrend(smoothed=smoothed, direction=direction, n=len(present))


# --- TASK-004: zone re-derivation on anchor move (reuses the E4·P2 kernel) ---

#: An anchor "moved" when it shifts by ≥ this many bpm (CONSTITUTION §10 recompute;
#: avoids rewriting identical git-diffable zones — DECISIONS 5).
ANCHOR_MIN_DELTA_BPM = 1


@dataclass(frozen=True)
class ZoneRederivation:
    """The zone-recompute result the E10·P2 node merges into the loaded ``Profile``.

    ``changed`` is ``True`` iff an anchor moved ≥ ``ANCHOR_MIN_DELTA_BPM``; ``zones`` is
    the new ``compute_zones`` output (``{"z1": (lo, hi), …}``) when ``changed``, else
    ``None`` (no-op — don't rewrite identical zones). ``new_max_hr``/``new_rhr`` echo the
    candidate anchors so the node has them in one place.
    """

    changed: bool
    zones: dict[str, tuple[int, int]] | None
    new_max_hr: int
    new_rhr: int


def rederive_zones(
    *, current_max_hr: int, current_rhr: int, new_max_hr: int, new_rhr: int
) -> ZoneRederivation:
    """Re-derive the HR zones **only when the max-HR/RHR anchors moved** (§10).

    Returns a no-op ``ZoneRederivation(False, None, …)`` when neither anchor shifted by
    ≥ ``ANCHOR_MIN_DELTA_BPM`` bpm; otherwise re-runs the **E4·P2 ``compute_zones`` kernel**
    (reused, never re-implemented — so the result "matches ``compute_zones``" by
    construction and passes the E3·P1 ``Zones``/``Profile`` validators). **HRV is not a
    parameter** (not a ``compute_zones`` input), so an HRV-only change cannot trigger this.
    This helper only **returns** the new zones; the atomic ``profile.yaml`` write is the
    E10·P2 node's (DECISIONS 4).
    """
    moved = (
        abs(new_max_hr - current_max_hr) >= ANCHOR_MIN_DELTA_BPM
        or abs(new_rhr - current_rhr) >= ANCHOR_MIN_DELTA_BPM
    )
    if not moved:
        return ZoneRederivation(changed=False, zones=None, new_max_hr=new_max_hr, new_rhr=new_rhr)
    return ZoneRederivation(
        changed=True,
        zones=compute_zones(new_max_hr, new_rhr),
        new_max_hr=new_max_hr,
        new_rhr=new_rhr,
    )


# ---------------------------------------------------------------------------
# Phase 19.6 — runtime measured max-HR anchor source (feeds `rederive_zones`)
# ---------------------------------------------------------------------------

#: Physiological HR window, MIRRORED from ``scripts/derive_constants.py``
#: (``HR_FLOOR = 80.0`` / ``HR_CEILING = 205.0``) so the runtime anchor is clamped
#: exactly like the offline seed derivation. The offline module is deliberately NOT
#: imported (its bare ``from compute_zones import compute_zones`` needs ``scripts/`` on
#: ``sys.path`` and has no package path). A parity test in
#: ``tests/scripts/test_derive_constants.py`` guards against drift (PLAN D4 / R1).
_HR_FLOOR = 80.0
_HR_CEILING = 205.0


def measured_max_hr(session: Session, *, as_of: date, current_max_hr: int) -> int:
    """The runtime measured max-HR anchor — a SQLAlchemy port of the offline
    ``scripts/derive_constants.py:derive_max_hr`` (§ parity), fed to ``rederive_zones``.

    Runs a single ``func.max(records.value)`` over the **whole corpus** (NOT date-windowed
    — a recent window could miss the true peak), matching **both** HR type spellings (the
    snake-case wire alias ``heart_rate`` that live ``/sync`` rows store AND the HK identifier
    ``HKQuantityTypeIdentifierHeartRate`` that seeded rows store; alias set derived from
    ``RECORD_TYPE_TO_HK``), physiologically clamped to ``[_HR_FLOOR, _HR_CEILING]`` so a
    sensor artifact can't inflate it.

    **``as_of`` cutoff** — a single conservative-inclusive, *device-local-date* lexical bound
    ``records.start_date < (as_of + 1 day)``. ``start_date`` is ISO-8601 TEXT with the device
    offset preserved verbatim, so its date-prefix is the device-local date; a ``func.max()``
    aggregate cannot re-narrow by Sofia date in Python (unlike ``daily_metrics_engine._window``),
    so the bound is deliberately biased **inclusive** — an in-week peak is never dropped, while
    a near-future row within ~1 day may be included (immaterial for an up-only whole-corpus
    ceiling; production carries no future HR). See PLAN R3.

    **Ratchet-up only** (D2): the returned anchor never drops below ``current_max_hr``, so
    ``rederive_zones``'s ``ANCHOR_MIN_DELTA_BPM`` gate can only ever fire on an upward move.
    An empty / thin corpus (no in-range HR rows) returns ``current_max_hr`` unchanged — never
    raises (D3), unlike the build-time offline derivation, so a weekly brief can't crash.
    """
    aliases = {"heart_rate", RECORD_TYPE_TO_HK["heart_rate"]}
    upper_bound = (as_of + timedelta(days=1)).isoformat()
    stmt = (
        select(func.max(Records.value))
        .where(Records.type.in_(aliases))
        .where(Records.value >= _HR_FLOOR)
        .where(Records.value <= _HR_CEILING)
        .where(Records.start_date < upper_bound)
    )
    raw = session.execute(stmt).scalar_one_or_none()
    if raw is None:
        return current_max_hr
    return max(current_max_hr, int(round(raw)))
