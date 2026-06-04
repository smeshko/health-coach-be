"""Finalized HealthKit type whitelist — the single source of truth for which
sample `type`s are stored (DB.md §1, §7; epic R4).

**Shared with E5 `/sync`**: the offline seed (E4·P3) and the live `/sync` path both
filter incoming `records` through this exact set, so it must be importable at
runtime — hence `app/core/`, not `scripts/`. It is **pure data** (frozensets of
`HK…Identifier` strings + `is_whitelisted`); it opens no DB and never touches
`baseline.db`, so hosting it in `app/` does not violate "baseline.db never opened
at runtime" (ARCHITECTURE §6).

The whitelist gates **`records.type`** only — `workouts` (sessions) and
`activity_summary` (per-day rings) are seeded by window, not by `type`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a core→api import cycle
    from collections.abc import Iterable

    from app.api.schemas.sync import HealthRecord

# Activity / recovery metrics (DB.md §1). `StepCount` covers cadence-derived step
# counts; the dedicated running-cadence identifier varies by export version, so
# CADENCE_TYPE (below) names it explicitly and is included in the set (consistent
# with E4·P2's CADENCE_TYPE resolution).
ACTIVITY_RECOVERY_TYPES: frozenset[str] = frozenset(
    {
        "HKQuantityTypeIdentifierHeartRate",
        "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
        "HKQuantityTypeIdentifierRestingHeartRate",
        "HKCategoryTypeIdentifierSleepAnalysis",
        "HKQuantityTypeIdentifierStepCount",
        "HKQuantityTypeIdentifierActiveEnergyBurned",
        "HKQuantityTypeIdentifierBasalEnergyBurned",
        "HKQuantityTypeIdentifierPhysicalEffort",  # METs proxy
        "HKQuantityTypeIdentifierVO2Max",
        "HKQuantityTypeIdentifierBodyMass",  # single live-weight source (DB.md §1)
        # Running dynamics
        "HKQuantityTypeIdentifierRunningSpeed",
        "HKQuantityTypeIdentifierRunningStrideLength",
        "HKQuantityTypeIdentifierRunningVerticalOscillation",
        "HKQuantityTypeIdentifierRunningGroundContactTime",
        "HKQuantityTypeIdentifierRunningPower",
        "HKQuantityTypeIdentifierRunningCadence",
    }
)

# Dietary intake (DB.md §1 "Dietary intake (NEW)") — the HKQuantityTypeIdentifierDietary* family.
DIETARY_TYPES: frozenset[str] = frozenset(
    {
        "HKQuantityTypeIdentifierDietaryEnergyConsumed",
        "HKQuantityTypeIdentifierDietaryProtein",
        "HKQuantityTypeIdentifierDietaryCarbohydrates",
        "HKQuantityTypeIdentifierDietaryFatTotal",
        "HKQuantityTypeIdentifierDietaryFiber",
        "HKQuantityTypeIdentifierDietarySodium",
        "HKQuantityTypeIdentifierDietaryWater",
    }
)

WHITELISTED_TYPES: frozenset[str] = ACTIVITY_RECOVERY_TYPES | DIETARY_TYPES

# The running-cadence (steps/min) identifier. The current corpus carries no
# first-class cadence sample (cadence is derivable from speed/stride or step
# count), but pinning it here keeps the seed/sync forward-compatible if an export
# starts emitting it — and matches E4·P2's CADENCE_TYPE.
CADENCE_TYPE: str = "HKQuantityTypeIdentifierRunningCadence"


def is_whitelisted(type_: str) -> bool:
    """True iff `type_` is a stored sample type (DB.md §1 — only these are kept)."""
    return type_ in WHITELISTED_TYPES


# ---------------------------------------------------------------------------
# Wire↔HK bridge (shared with E5 /sync, E5·P1 TASK-003).
#
# Maps each `RecordType` wire value (snake_case, MODELS "Enums") to its
# `HK…Identifier`. Storage membership for a wire type is then *derived* from the
# `WHITELISTED_TYPES` frozenset above — there is exactly one stored-types list,
# so the wire enum and the storage whitelist can never silently drift (a wire
# type added without a map entry is caught by a completeness test).
#
# `respiratory_rate` maps to its identifier but is **not** in `WHITELISTED_TYPES`
# — it is accepted on the wire yet filtered from storage (epic R3).
# ---------------------------------------------------------------------------
RECORD_TYPE_TO_HK: dict[str, str] = {
    "heart_rate": "HKQuantityTypeIdentifierHeartRate",
    "heart_rate_variability_sdnn": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
    "resting_heart_rate": "HKQuantityTypeIdentifierRestingHeartRate",
    "sleep_analysis": "HKCategoryTypeIdentifierSleepAnalysis",
    "step_count": "HKQuantityTypeIdentifierStepCount",
    "active_energy_burned": "HKQuantityTypeIdentifierActiveEnergyBurned",
    "basal_energy_burned": "HKQuantityTypeIdentifierBasalEnergyBurned",
    "physical_effort": "HKQuantityTypeIdentifierPhysicalEffort",
    "vo2_max": "HKQuantityTypeIdentifierVO2Max",
    "body_mass": "HKQuantityTypeIdentifierBodyMass",
    "running_speed": "HKQuantityTypeIdentifierRunningSpeed",
    "running_power": "HKQuantityTypeIdentifierRunningPower",
    "running_cadence": "HKQuantityTypeIdentifierRunningCadence",
    "running_stride_length": "HKQuantityTypeIdentifierRunningStrideLength",
    "running_ground_contact_time": "HKQuantityTypeIdentifierRunningGroundContactTime",
    "running_vertical_oscillation": "HKQuantityTypeIdentifierRunningVerticalOscillation",
    # Recognised on the wire but NOT in WHITELISTED_TYPES → filtered from storage.
    "respiratory_rate": "HKQuantityTypeIdentifierRespiratoryRate",
    "dietary_energy_consumed": "HKQuantityTypeIdentifierDietaryEnergyConsumed",
    "dietary_protein": "HKQuantityTypeIdentifierDietaryProtein",
    "dietary_carbohydrates": "HKQuantityTypeIdentifierDietaryCarbohydrates",
    "dietary_fat_total": "HKQuantityTypeIdentifierDietaryFatTotal",
    "dietary_fiber": "HKQuantityTypeIdentifierDietaryFiber",
    "dietary_sodium": "HKQuantityTypeIdentifierDietarySodium",
    "dietary_water": "HKQuantityTypeIdentifierDietaryWater",
}


def is_record_type_whitelisted(record_type: str) -> bool:
    """True iff a wire `HealthRecord.type` maps to a stored `HK…Identifier`.

    Membership is derived from E4's `WHITELISTED_TYPES` via `RECORD_TYPE_TO_HK`
    (no second list). An unknown wire string (no map entry) is never stored.
    """
    return is_whitelisted(RECORD_TYPE_TO_HK.get(record_type, ""))


def filter_whitelisted_records(records: Iterable[HealthRecord]) -> list[HealthRecord]:
    """Return only records whose wire `type` is whitelisted-for-storage.

    Pure (no DB/IO) and order-preserving — `/sync` (E5·P2) calls it before the
    upsert. `Workout` / `ActivitySummary` are not `type`-whitelisted (DB.md §1
    gates `records.type` only), so this applies to `HealthRecord`s alone.
    """
    return [r for r in records if is_record_type_whitelisted(r.type.value)]
