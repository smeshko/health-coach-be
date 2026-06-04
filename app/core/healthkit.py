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
