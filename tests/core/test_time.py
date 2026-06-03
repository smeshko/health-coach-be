"""Europe/Sofia period-key + timestamp-helper tests (E2·P1 TASK-003).

Period keys are derived through the `Europe/Sofia` tz database (DST-aware), never
a fixed offset; timestamps are stored as ISO-8601 TEXT carrying the offset the
sample emitted, byte-for-byte. Expected values are the tz-database ground truth.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.time import (
    iso_week,
    iso_week_of,
    parse_ts,
    period_date,
    period_date_of,
    store_ts,
    to_sofia,
)


def test_tzdata_available():
    # tzdata dependency present — ZoneInfo resolves in CI/containers.
    assert ZoneInfo("Europe/Sofia") is not None


@pytest.mark.parametrize(
    ("ts", "expected_date", "expected_week"),
    [
        # Winter EET (+02): a fixed +03 would roll this to 01-16 — it must not.
        ("2026-01-15T21:30:00+00:00", "2026-01-15", "2026-W03"),
        # Summer EEST (+03): a fixed +02 would keep this at 06-15 — it must not.
        ("2026-06-15T21:30:00+00:00", "2026-06-16", "2026-W25"),
        # Either side of the spring-forward / fall-back transitions.
        ("2026-03-28T23:30:00+00:00", "2026-03-29", "2026-W13"),
        ("2026-10-25T23:30:00+00:00", "2026-10-26", "2026-W44"),
        # Travel offset (+09:00) still resolves to the Sofia-local key.
        ("2026-06-15T23:30:00+09:00", "2026-06-15", "2026-W25"),
        # ISO year-boundary weeks: a 2025 date in ISO-year 2026-W01, and a 2027
        # date in ISO-year 2026-W53.
        ("2025-12-29T10:00:00+02:00", "2025-12-29", "2026-W01"),
        ("2027-01-01T10:00:00+02:00", "2027-01-01", "2026-W53"),
    ],
)
def test_period_date_and_iso_week_dst_aware(ts, expected_date, expected_week):
    dt = datetime.fromisoformat(ts)
    assert period_date(dt) == expected_date
    assert iso_week(dt) == expected_week
    # String convenience wrappers parse first, same result.
    assert period_date_of(ts) == expected_date
    assert iso_week_of(ts) == expected_week


def test_iso_week_is_zero_padded():
    # 2026-W03 / 2026-W01, not 2026-W3 / 2026-W1.
    assert iso_week(datetime.fromisoformat("2026-01-15T12:00:00+02:00")) == "2026-W03"


@pytest.mark.parametrize(
    "ts",
    [
        "2026-01-15T08:30:00+02:00",
        "2026-06-15T08:30:00+03:00",
        "2026-06-15T08:30:00+0300",  # compact offset preserved verbatim
        "2026-06-15T23:30:00+09:00",  # non-Sofia travel offset
        "2026-06-15T08:30:00.123456+03:00",  # fractional seconds preserved
    ],
)
def test_store_ts_returns_exact_string(ts):
    # No offset reformatting, no UTC normalization — the stored bytes are the input.
    assert store_ts(ts) == ts
    # parse_ts preserves the same offset.
    assert parse_ts(ts).utcoffset() == datetime.fromisoformat(ts).utcoffset()


@pytest.mark.parametrize("naive", ["2026-06-15T08:30:00", "2026-06-15 08:30:00"])
def test_parse_and_store_reject_naive_string(naive):
    with pytest.raises(ValueError):
        parse_ts(naive)
    with pytest.raises(ValueError):
        store_ts(naive)


def test_naive_datetime_rejected():
    # No host-tz fallback: reproducible cache keys across dev/CI/containers.
    naive = datetime(2026, 6, 15, 8, 30)
    with pytest.raises(ValueError):
        to_sofia(naive)
    with pytest.raises(ValueError):
        period_date(naive)
    with pytest.raises(ValueError):
        iso_week(naive)


def test_to_sofia_converts_aware_datetime():
    dt = datetime.fromisoformat("2026-06-15T21:30:00+00:00")
    sofia = to_sofia(dt)
    assert sofia.tzinfo == ZoneInfo("Europe/Sofia")
    assert sofia.isoformat() == "2026-06-16T00:30:00+03:00"
