"""E5·P3 TASK-003: recompute seam — affected_dates fan-out + noop default."""

from __future__ import annotations

from datetime import date

from app.api.schemas.sync import SyncRequest
from app.services.recompute import affected_dates, noop_recompute


def test_affected_dates_exact_sofia_union() -> None:
    request = SyncRequest.model_validate(
        {
            "records": [
                {
                    "uuid": "r1",
                    "type": "heart_rate",
                    "start": "2026-06-01T08:00:00+03:00",
                    "end": "2026-06-01T08:00:30+03:00",
                    "value": 57.0,
                    "unit": "count/min",
                }
            ],
            "workouts": [
                {
                    "uuid": "w1",
                    "type": "boxing",
                    "start": "2026-06-10T18:00:00+03:00",
                    "end": "2026-06-10T18:45:00+03:00",
                    "durationS": 2700.0,
                }
            ],
            "activitySummary": [
                {
                    "date": "2026-06-04",
                    "activeEnergyKcal": 620.0,
                    "exerciseMinutes": 48,
                    "standHours": 11,
                }
            ],
            "checkin": {"date": "2026-06-05", "giSymptoms": False, "kneePain": 0, "illness": False},
            "strengthTest": {"date": "2026-06-06", "maxPushups": 42, "maxPullups": 11},
        }
    )
    assert affected_dates(request) == {
        date(2026, 6, 1),
        date(2026, 6, 10),
        date(2026, 6, 4),
        date(2026, 6, 5),
        date(2026, 6, 6),
    }


def test_offset_crossing_start_buckets_to_sofia_date() -> None:
    # 23:30 UTC on 06-02 is 02:30 Sofia (EEST +03:00) on 06-03 → Sofia date wins.
    request = SyncRequest.model_validate(
        {
            "records": [
                {
                    "uuid": "r1",
                    "type": "heart_rate",
                    "start": "2026-06-02T23:30:00+00:00",
                    "end": "2026-06-02T23:30:30+00:00",
                    "value": 60.0,
                    "unit": "count/min",
                }
            ]
        }
    )
    result = affected_dates(request)
    assert result == {date(2026, 6, 3)}
    assert date(2026, 6, 2) not in result  # not the wire-offset date


def test_empty_body_returns_empty_set() -> None:
    assert affected_dates(SyncRequest.model_validate({})) == set()


def test_only_non_whitelisted_records_returns_empty_set() -> None:
    # respiratory_rate is a valid RecordType but not stored — it changes no day's
    # data, so it contributes no affected date.
    request = SyncRequest.model_validate(
        {
            "records": [
                {
                    "uuid": "r1",
                    "type": "respiratory_rate",
                    "start": "2026-06-02T08:00:00+03:00",
                    "end": "2026-06-02T08:00:30+03:00",
                    "value": 14.0,
                    "unit": "count/min",
                }
            ]
        }
    )
    assert affected_dates(request) == set()


def test_dedup_across_records_and_workouts() -> None:
    request = SyncRequest.model_validate(
        {
            "records": [
                {
                    "uuid": "r1",
                    "type": "heart_rate",
                    "start": "2026-06-01T08:00:00+03:00",
                    "end": "2026-06-01T08:00:30+03:00",
                    "value": 57.0,
                    "unit": "count/min",
                }
            ],
            "workouts": [
                {
                    "uuid": "w1",
                    "type": "running",
                    "start": "2026-06-01T18:00:00+03:00",
                    "end": "2026-06-01T18:30:00+03:00",
                    "durationS": 1800.0,
                }
            ],
        }
    )
    assert affected_dates(request) == {date(2026, 6, 1)}  # deduped


def test_noop_recompute_is_a_safe_no_op() -> None:
    assert noop_recompute(set()) is None
    assert noop_recompute({date(2026, 6, 1)}) is None
