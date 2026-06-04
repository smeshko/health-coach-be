"""TASK-001: the finalized HealthKit type whitelist (shared with E5 /sync)."""

from __future__ import annotations

import pytest

from app.core import healthkit

REQUIRED_ACTIVITY_RECOVERY = [
    "HKQuantityTypeIdentifierHeartRate",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
    "HKQuantityTypeIdentifierRestingHeartRate",
    "HKCategoryTypeIdentifierSleepAnalysis",
    "HKQuantityTypeIdentifierStepCount",
    "HKQuantityTypeIdentifierActiveEnergyBurned",
    "HKQuantityTypeIdentifierBasalEnergyBurned",
    "HKQuantityTypeIdentifierPhysicalEffort",
    "HKQuantityTypeIdentifierVO2Max",
    "HKQuantityTypeIdentifierBodyMass",
    "HKQuantityTypeIdentifierRunningSpeed",
    "HKQuantityTypeIdentifierRunningStrideLength",
    "HKQuantityTypeIdentifierRunningVerticalOscillation",
    "HKQuantityTypeIdentifierRunningGroundContactTime",
    "HKQuantityTypeIdentifierRunningPower",
]

REQUIRED_DIETARY = [
    "HKQuantityTypeIdentifierDietaryEnergyConsumed",
    "HKQuantityTypeIdentifierDietaryProtein",
    "HKQuantityTypeIdentifierDietaryCarbohydrates",
    "HKQuantityTypeIdentifierDietaryFatTotal",
    "HKQuantityTypeIdentifierDietaryFiber",
    "HKQuantityTypeIdentifierDietarySodium",
    "HKQuantityTypeIdentifierDietaryWater",
]


def test_whitelist_is_frozenset() -> None:
    assert isinstance(healthkit.WHITELISTED_TYPES, frozenset)
    assert isinstance(healthkit.ACTIVITY_RECOVERY_TYPES, frozenset)
    assert isinstance(healthkit.DIETARY_TYPES, frozenset)


@pytest.mark.parametrize("type_", REQUIRED_ACTIVITY_RECOVERY + REQUIRED_DIETARY)
def test_required_types_present(type_: str) -> None:
    assert type_ in healthkit.WHITELISTED_TYPES
    assert healthkit.is_whitelisted(type_)


def test_body_mass_and_dietary_whitelisted() -> None:
    assert healthkit.is_whitelisted("HKQuantityTypeIdentifierBodyMass")
    assert healthkit.is_whitelisted("HKQuantityTypeIdentifierDietaryProtein")


def test_non_whitelisted_type_rejected() -> None:
    assert not healthkit.is_whitelisted("HKQuantityTypeIdentifierEnvironmentalAudioExposure")


def test_dietary_set_is_exactly_seven() -> None:
    assert healthkit.DIETARY_TYPES == frozenset(REQUIRED_DIETARY)
    assert len(healthkit.DIETARY_TYPES) == 7


def test_whitelist_is_union_of_subsets() -> None:
    assert healthkit.WHITELISTED_TYPES == (
        healthkit.ACTIVITY_RECOVERY_TYPES | healthkit.DIETARY_TYPES
    )


def test_cadence_type_named_and_whitelisted() -> None:
    # CADENCE_TYPE names the running-cadence identifier; it is part of the set.
    assert healthkit.CADENCE_TYPE in healthkit.WHITELISTED_TYPES
