"""Offline derivation: baseline.db → constants for profile.yaml (E4·P2).

Reads the read-only `baseline.db` corpus (E4·P1), derives the athlete / threshold
/ zone / nutrition constants, and (in the CLI) writes a `profile.yaml` that passes
the **E3·P1 `Profile` validator** verbatim with `meta` stamped (DB.md §5/§6;
constitution §3/§7). Deterministic for a fixed corpus + `computed_at`.

Offline build step: plain `sqlite3` + stdlib + a YAML dump. The only `app/` import
is `app.core.profile` (reused as the validator); `app/` never imports this script
and `baseline.db` is opened **read-only** and never at runtime (ARCHITECTURE §6;
DB.md §0).

Split of constants (PLAN Decisions):
- **data-derived** from `records`: `max_hr`, `rhr_baseline`, `hrv_baseline_ms`,
  `cadence_current_spm`.
- **computed**: `easy_hr_cap = 180 − age` (Maffetone, constitution §3).
- **config anchors** (clinician/profile constants, not fitted from samples): the
  `athlete` block, `cadence_target_spm`, and the whole `nutrition` block.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from compute_zones import compute_zones

# --- HealthKit record types (DB.md §1; confirmed against the corpus) ----------
HR_TYPE = "HKQuantityTypeIdentifierHeartRate"
RHR_TYPE = "HKQuantityTypeIdentifierRestingHeartRate"
HRV_TYPE = "HKQuantityTypeIdentifierHeartRateVariabilitySDNN"
# The real corpus carries no first-class running-cadence (steps/min) sample — only
# RunningSpeed/StrideLength/GroundContactTime/Power/StepCount. This is the
# semantically correct identifier a cadence sample would use; when absent, the
# derivation falls back to the config anchor (see derive_cadence_current_spm).
CADENCE_TYPE = "HKQuantityTypeIdentifierRunningCadence"

# Physiological clamp so an artifact spike/dropout can't move max_hr.
HR_FLOOR = 80.0
HR_CEILING = 220.0

# Rolling anchors (rhr/hrv/cadence) use the trailing window from the latest
# sample so a multi-year corpus yields a *current monthly* anchor, not a lifetime
# mean (DB.md §5 "monthly anchor" / §6 trailing window).
RECENT_DAYS = 90

# Apple emits ISO-8601 with a space and a numeric offset, e.g. "2025-04-15 07:32:11 +0300".
_TS_FORMAT = "%Y-%m-%d %H:%M:%S %z"


@dataclass(frozen=True)
class DerivationConfig:
    """Config anchors carried through, not fitted from samples (DB.md §5; §7).

    Defaults match the DB.md §5 anchors; a real deploy injects the true values.
    """

    # athlete
    age: int = 34
    sex: str = "male"
    height_cm: int = 174
    goal_weight_kg: float = 75.0
    # cadence ramp END target; current is data-derived (with this as a fallback)
    cadence_target_spm: int = 172
    cadence_current_spm: int = 160
    # nutrition (§7 medical/clinician constants the macro engine reads)
    activity_factor: float = 1.65
    deficit_pct: float = 0.12
    protein_g_per_kg: float = 1.8
    fat_g_per_kg_low: float = 0.8
    fat_g_per_kg_high: float = 1.0
    carbs_hard_low: float = 4.0
    carbs_hard_high: float = 5.0
    carbs_moderate: float = 3.0
    carbs_rest_low: float = 2.0
    carbs_rest_high: float = 2.5
    hydration_l_low: float = 3.0
    hydration_l_high: float = 3.5
    fiber_g_low: float = 25.0
    fiber_g_high: float = 35.0


def open_readonly(db_path: str | Path) -> sqlite3.Connection:
    """Open `baseline.db` strictly read-only (a build input, never mutated)."""
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _median(values: Sequence[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        raise ValueError("median of no samples")
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2


def _windowed_values(con: sqlite3.Connection, hk_type: str, recent_days: int = RECENT_DAYS) -> list[float]:
    """Values for `hk_type` within `recent_days` of that type's latest sample."""
    rows = con.execute(
        "SELECT value, start_date FROM records WHERE type = ? AND value IS NOT NULL",
        (hk_type,),
    ).fetchall()
    parsed = [(float(v), datetime.strptime(d, _TS_FORMAT)) for v, d in rows if d]
    if not parsed:
        return []
    latest = max(dt for _, dt in parsed)
    cutoff = latest - timedelta(days=recent_days)
    return [v for v, dt in parsed if dt >= cutoff]


def derive_max_hr(con: sqlite3.Connection) -> int:
    """Bounded max of HR over the **whole corpus** — a near-stationary ceiling
    "from observed boxing peaks" (constitution §3). Clamped to a physiological
    window so an artifact can't inflate it; NOT date-windowed (a recent window
    could miss the true peak)."""
    row = con.execute(
        "SELECT MAX(value) FROM records WHERE type = ? AND value >= ? AND value <= ?",
        (HR_TYPE, HR_FLOOR, HR_CEILING),
    ).fetchone()
    if row is None or row[0] is None:
        raise ValueError("no in-range HKQuantityTypeIdentifierHeartRate samples in baseline.db")
    return int(round(row[0]))


def derive_rhr_baseline(con: sqlite3.Connection) -> int:
    """Median of recent resting-HR — the monthly zone-derivation anchor (DB.md §5
    ¹; NOT the live readiness baseline, which reads rolling daily_metrics)."""
    return int(round(_median(_windowed_values(con, RHR_TYPE))))


def derive_hrv_baseline_ms(con: sqlite3.Connection) -> int:
    """Median of recent HRV SDNN in ms (informational; DB.md §5)."""
    return int(round(_median(_windowed_values(con, HRV_TYPE))))


def derive_cadence_current_spm(con: sqlite3.Connection) -> int | None:
    """Median of recent running cadence ("THIS month's cue", DB.md §5), or None
    when the corpus carries no cadence sample (caller falls back to the anchor)."""
    values = _windowed_values(con, CADENCE_TYPE)
    if not values:
        return None
    return int(round(_median(values)))


def derive_constants(con: sqlite3.Connection, config: DerivationConfig) -> dict:
    """Assemble the data-derived + computed + config-anchor constants as the five
    §5 sections (minus `meta`, stamped in the CLI). Keys mirror DB.md §5 1:1."""
    max_hr = derive_max_hr(con)
    rhr_baseline = derive_rhr_baseline(con)
    hrv_baseline_ms = derive_hrv_baseline_ms(con)
    cadence_current = derive_cadence_current_spm(con)
    if cadence_current is None:
        cadence_current = config.cadence_current_spm

    return {
        "athlete": {
            "age": config.age,
            "sex": config.sex,
            "height_cm": config.height_cm,
            "goal_weight_kg": config.goal_weight_kg,
        },
        "thresholds": {
            "max_hr": max_hr,
            "rhr_baseline": rhr_baseline,
            "hrv_baseline_ms": hrv_baseline_ms,
            "easy_hr_cap": 180 - config.age,  # Maffetone (constitution §3)
            "cadence_target_spm": config.cadence_target_spm,
            "cadence_current_spm": cadence_current,
        },
        "zones": compute_zones(max_hr, rhr_baseline),
        "nutrition": {
            "activity_factor": config.activity_factor,
            "deficit_pct": config.deficit_pct,
            "protein_g_per_kg": config.protein_g_per_kg,
            "fat_g_per_kg_low": config.fat_g_per_kg_low,
            "fat_g_per_kg_high": config.fat_g_per_kg_high,
            "carbs_g_per_kg": {
                "hard_low": config.carbs_hard_low,
                "hard_high": config.carbs_hard_high,
                "moderate": config.carbs_moderate,
                "rest_low": config.carbs_rest_low,
                "rest_high": config.carbs_rest_high,
            },
            "hydration_l_low": config.hydration_l_low,
            "hydration_l_high": config.hydration_l_high,
            "fiber_g_low": config.fiber_g_low,
            "fiber_g_high": config.fiber_g_high,
        },
    }
