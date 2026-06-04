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


# ---------------------------------------------------------------------------
# TASK-003: the wire↔HK bridge + record filter (shared with E5 /sync).
# ---------------------------------------------------------------------------


def test_record_type_to_hk_covers_every_wire_value() -> None:
    from app.api.schemas.sync import RecordType

    assert set(healthkit.RECORD_TYPE_TO_HK) == {m.value for m in RecordType}


def test_is_record_type_whitelisted_agrees_with_is_whitelisted() -> None:
    from app.api.schemas.sync import RecordType

    for member in RecordType:
        mapped = healthkit.RECORD_TYPE_TO_HK[member.value]
        assert healthkit.is_record_type_whitelisted(member.value) == healthkit.is_whitelisted(mapped)


def test_is_record_type_whitelisted_known_and_unknown() -> None:
    assert healthkit.is_record_type_whitelisted("dietary_protein") is True
    assert healthkit.is_record_type_whitelisted("body_mass") is True
    # Unknown wire string maps to nothing → not whitelisted.
    assert healthkit.is_record_type_whitelisted("blood_glucose") is False


def test_respiratory_rate_recognised_but_unstored() -> None:
    # respiratory_rate is a valid RecordType on the wire but absent from E4's
    # storage whitelist — the recognised-but-unstored case the filter must drop.
    from app.api.schemas.sync import RecordType

    assert RecordType("respiratory_rate")
    assert healthkit.is_record_type_whitelisted("respiratory_rate") is False


def _record(uuid: str, type_: str) -> "object":
    from app.api.schemas.sync import HealthRecord

    return HealthRecord.model_validate(
        {
            "uuid": uuid,
            "type": type_,
            "start": "2026-06-01T08:00:00+03:00",
            "end": "2026-06-01T08:00:00+03:00",
        }
    )


def test_filter_keeps_whitelisted_and_drops_unstored() -> None:
    kept_a = _record("a", "dietary_protein")
    dropped = _record("b", "respiratory_rate")
    kept_b = _record("c", "body_mass")
    result = healthkit.filter_whitelisted_records([kept_a, dropped, kept_b])
    assert result == [kept_a, kept_b]  # order-preserving, drop removed


def test_filter_is_pure_returns_new_list() -> None:
    records = [_record("a", "body_mass")]
    result = healthkit.filter_whitelisted_records(records)
    assert result is not records
    assert result == records
