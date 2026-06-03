# TASK-001: HealthKit type whitelist module

Depends on: None
Suggested commit: `feat(core): add HealthKit type whitelist (shared with sync)`

## Goal

Add `app/core/healthkit.py` — the finalized, exact HealthKit `HK…Identifier` whitelist (the single source of
truth shared with E5 `/sync`) that decides which `records` sample `type`s are stored.

## Files

- `app/core/healthkit.py` — **new**. Pure data + helpers, **no DB/IO** (so the seed and E5 `/sync` share it
  and it never opens `baseline.db`):
  - `ACTIVITY_RECOVERY_TYPES: frozenset[str]` — `HKQuantityTypeIdentifierHeartRate`,
    `HKQuantityTypeIdentifierHeartRateVariabilitySDNN`, `HKQuantityTypeIdentifierRestingHeartRate`,
    `HKCategoryTypeIdentifierSleepAnalysis`, `HKQuantityTypeIdentifierStepCount`,
    `HKQuantityTypeIdentifierActiveEnergyBurned`, `HKQuantityTypeIdentifierBasalEnergyBurned`,
    `HKQuantityTypeIdentifierPhysicalEffort`, `HKQuantityTypeIdentifierVO2Max`,
    `HKQuantityTypeIdentifierBodyMass`, `HKQuantityTypeIdentifierRunningSpeed`,
    `HKQuantityTypeIdentifierRunningStrideLength`, `HKQuantityTypeIdentifierRunningVerticalOscillation`,
    `HKQuantityTypeIdentifierRunningGroundContactTime`, `HKQuantityTypeIdentifierRunningPower`.
  - `DIETARY_TYPES: frozenset[str]` — `HKQuantityTypeIdentifierDietaryEnergyConsumed`,
    `…DietaryProtein`, `…DietaryCarbohydrates`, `…DietaryFatTotal`, `…DietaryFiber`, `…DietarySodium`,
    `…DietaryWater`.
  - `WHITELISTED_TYPES: frozenset[str] = ACTIVITY_RECOVERY_TYPES | DIETARY_TYPES`.
  - `CADENCE_TYPE: str` — a named constant for the running-cadence/step-rate identifier (varies by export
    version; confirm against the real corpus, like E4·P2's `CADENCE_TYPE`). Either it is already in
    `ACTIVITY_RECOVERY_TYPES` (e.g. `RunningSpeed`) or it is added to the set explicitly — the set is the
    authority, the constant just names it for the seed/derivation.
  - `def is_whitelisted(type_: str) -> bool: return type_ in WHITELISTED_TYPES`.
- `tests/core/test_healthkit.py` — **new**: assert the set's completeness, the helper, and immutability.

## Acceptance

- [ ] `WHITELISTED_TYPES` is a `frozenset` and contains every required identifier: HR, HRV SDNN, RHR, sleep
      analysis, steps, active + basal energy, PhysicalEffort, VO₂max, **`HKQuantityTypeIdentifierBodyMass`**,
      the five running-dynamics types, **and** all seven `HKQuantityTypeIdentifierDietary*`.
- [ ] `is_whitelisted("HKQuantityTypeIdentifierDietaryProtein")` and
      `is_whitelisted("HKQuantityTypeIdentifierBodyMass")` are `True`.
- [ ] `is_whitelisted("HKQuantityTypeIdentifierEnvironmentalAudioExposure")` is `False`.
- [ ] `DIETARY_TYPES` has exactly the seven dietary identifiers; `WHITELISTED_TYPES ==
      ACTIVITY_RECOVERY_TYPES | DIETARY_TYPES`.
- [ ] The module imports nothing from `app.database` / SQLAlchemy / `baseline.db` (pure data).

## Steps

### RED
- [ ] `tests/core/test_healthkit.py`: assert `WHITELISTED_TYPES` is a `frozenset`; every required identifier
      is a member (parametrize over the dietary list + `body_mass` + the activity/recovery list);
      `is_whitelisted` True for an in-set type, False for `…EnvironmentalAudioExposure`;
      `WHITELISTED_TYPES == ACTIVITY_RECOVERY_TYPES | DIETARY_TYPES`. (Fails — module doesn't exist.)

### GREEN
- [ ] Add `app/core/healthkit.py` with the two named subsets, the union `WHITELISTED_TYPES`, `CADENCE_TYPE`,
      and `is_whitelisted`. Smallest code to pass.

### REFACTOR
- [ ] Group the identifiers with short comments (activity / recovery / dietary), keep the constants
      `frozenset` (immutable), and ensure no stray imports.

## Notes

This module is **runtime-shared** (E5 `/sync` reuses it), so it lives in `app/core/`, **not** `scripts/` —
DB.md §1 ("only the whitelisted types … are stored") + the phase NOTES. It is **pure data** (no DB access),
so hosting it in `app/` does not violate "`baseline.db` never opened at runtime" (ARCHITECTURE §6). The exact
running-cadence `type` varies by export version; pin it as `CADENCE_TYPE` and confirm against the real corpus
rather than hard-guessing (same resolution as E4·P2). The whitelist gates **`records.type`** only — `workouts`
and `activity_summary` are seeded by window, not by `type` (DB.md §1).
