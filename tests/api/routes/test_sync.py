"""E5·P2 TASK-003: POST /sync endpoint tests (over a migrated temp app.db)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.routes.sync import get_recompute
from app.api.schemas.sync import SyncRequest
from app.core.settings import get_settings
from app.core.time import get_clock
from app.database.engine import get_engine
from app.services.recompute import affected_dates

VALID_TOKEN = "test-api-token-0123456789"
AUTH = {"Authorization": f"Bearer {VALID_TOKEN}"}

BODY = {
    "records": [
        {
            "uuid": "r1",
            "type": "heart_rate",
            "start": "2026-06-01T08:00:00+03:00",
            "end": "2026-06-01T08:00:30+03:00",
            "value": 57.0,
            "unit": "count/min",
        },
        {
            "uuid": "r2",
            "type": "body_mass",
            "start": "2026-06-01T07:00:00+03:00",
            "end": "2026-06-01T07:00:00+03:00",
            "value": 78.4,
            "unit": "kg",
        },
    ],
    "workouts": [
        {
            "uuid": "w1",
            "type": "boxing",
            "start": "2026-06-01T18:00:00+03:00",
            "end": "2026-06-01T18:45:00+03:00",
            "durationS": 2700.0,
            "statistics": [{"type": "avg_hr", "value": 150.0, "unit": "count/min"}],
        }
    ],
    "activitySummary": [
        {
            "date": "2026-06-01",
            "activeEnergyKcal": 620.0,
            "exerciseMinutes": 48,
            "standHours": 11,
        }
    ],
}


def _migrate(db_path) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.attributes["test_db_url"] = f"sqlite:///{db_path}"
    command.upgrade(cfg, "head")


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    _migrate(db_path)
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", str(db_path))
    get_settings.cache_clear()
    get_engine.cache_clear()
    app = create_app()
    client = TestClient(app)
    yield client, app, db_path
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


def _table_count(db_path, table: str) -> int:
    with sqlite3.connect(db_path) as raw:
        return raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_sync_success_returns_camel_counts(ctx) -> None:
    client, _app, _db = ctx
    resp = client.post("/sync", json=BODY, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["recordsUpserted"] == 2
    assert body["recordsDuplicate"] == 0
    assert body["workoutsUpserted"] == 1
    assert body["activityDaysUpserted"] == 1
    assert body["checkinSaved"] is False
    assert body["strengthTestSaved"] is False
    assert body["recomputeOk"] is True  # real engine recompute succeeded
    assert "serverTime" in body
    assert datetime.fromisoformat(body["serverTime"]).utcoffset() is not None  # aware


@pytest.mark.parametrize(
    "utc_instant, expected_offset_hours",
    [
        (datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc), 2),  # winter +02:00
        (datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc), 3),  # summer +03:00
    ],
)
def test_server_time_dst_offset(ctx, utc_instant, expected_offset_hours) -> None:
    client, app, _db = ctx
    app.dependency_overrides[get_clock] = lambda: (lambda: utc_instant)
    resp = client.post("/sync", json={}, headers=AUTH)
    assert resp.status_code == 200
    parsed = datetime.fromisoformat(resp.json()["serverTime"])
    assert parsed.utcoffset().total_seconds() == expected_offset_hours * 3600


def test_sync_replay_is_idempotent(ctx) -> None:
    client, _app, db_path = ctx
    first = client.post("/sync", json=BODY, headers=AUTH)
    assert first.status_code == 200
    rec_before = _table_count(db_path, "records")
    wo_before = _table_count(db_path, "workouts")
    stat_before = _table_count(db_path, "workout_statistics")
    second = client.post("/sync", json=BODY, headers=AUTH)
    body = second.json()
    assert body["recordsUpserted"] == 0
    assert body["recordsDuplicate"] == 2
    assert body["workoutsUpserted"] == 0
    assert _table_count(db_path, "records") == rec_before
    assert _table_count(db_path, "workouts") == wo_before
    assert _table_count(db_path, "workout_statistics") == stat_before


def test_sync_requires_auth(ctx) -> None:
    client, _app, _db = ctx
    no_token = client.post("/sync", json=BODY)
    assert no_token.status_code == 401
    assert no_token.json()["error"]["code"] == "unauthorized"
    wrong = client.post("/sync", json=BODY, headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"
    ok = client.post("/sync", json=BODY, headers=AUTH)
    assert ok.status_code == 200


def test_non_whitelisted_record_not_stored(ctx) -> None:
    client, _app, db_path = ctx
    body = {
        "records": [
            {
                "uuid": "keep",
                "type": "body_mass",
                "start": "2026-06-01T07:00:00+03:00",
                "end": "2026-06-01T07:00:00+03:00",
                "value": 78.0,
                "unit": "kg",
            },
            {
                "uuid": "drop",
                "type": "respiratory_rate",
                "start": "2026-06-01T07:00:00+03:00",
                "end": "2026-06-01T07:00:30+03:00",
                "value": 14.0,
                "unit": "count/min",
            },
        ]
    }
    resp = client.post("/sync", json=body, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["recordsUpserted"] == 1
    with sqlite3.connect(db_path) as raw:
        uuids = {row[0] for row in raw.execute("SELECT uuid FROM records").fetchall()}
    assert "keep" in uuids
    assert "drop" not in uuids


def test_sync_real_engine_persists_daily_metrics_row(ctx) -> None:
    # E6·P1 swapped the recompute provider to the real engine: a sync now persists a
    # daily_metrics row for the affected Sofia day, with readiness left null (E8/E11).
    client, _app, db_path = ctx
    resp = client.post("/sync", json=BODY, headers=AUTH)
    assert resp.status_code == 200
    with sqlite3.connect(db_path) as raw:
        rows = raw.execute(
            "SELECT date, readiness_score, band FROM daily_metrics"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "2026-06-01"  # the single affected Sofia day
    assert rows[0][1] is None  # readiness_score null this phase
    assert rows[0][2] is None  # band null this phase


def test_sync_cross_midnight_sample_refreshes_both_sofia_days(ctx) -> None:
    # A single HR sample spanning the Sofia midnight: E5·P3 fans out only its start
    # day, but the engine expands its work-set to recompute BOTH Sofia days from one
    # sync (round-2 #1), so neither neighbour daily_metrics row is left stale.
    client, _app, db_path = ctx
    body = {
        "records": [
            {
                "uuid": "hr-cross",
                "type": "heart_rate",
                "start": "2026-06-01T23:50:00+03:00",
                "end": "2026-06-02T00:10:00+03:00",
                "value": 130.0,
                "unit": "count/min",
            }
        ]
    }
    resp = client.post("/sync", json=body, headers=AUTH)
    assert resp.status_code == 200
    with sqlite3.connect(db_path) as raw:
        dates = {r[0] for r in raw.execute("SELECT date FROM daily_metrics").fetchall()}
    assert dates == {"2026-06-01", "2026-06-02"}  # both rows refreshed from one sync


# ---------------------------------------------------------------------------
# E5·P3: check-in / strength-test persistence + recompute seam.
# ---------------------------------------------------------------------------

BODY_FULL = {
    **BODY,
    "checkin": {"date": "2026-06-01", "giSymptoms": True, "kneePain": 3, "illness": False},
    "strengthTest": {"date": "2026-06-01", "maxPushups": 42, "maxPullups": 11},
}


class _RecomputeSpy:
    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, dates) -> None:
        self.calls.append(dates)


def test_checkin_and_strength_saved_flags_and_rows(ctx) -> None:
    client, _app, db_path = ctx
    resp = client.post("/sync", json=BODY_FULL, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["checkinSaved"] is True
    assert body["strengthTestSaved"] is True
    assert _table_count(db_path, "checkins") == 1
    assert _table_count(db_path, "strength_tests") == 1
    with sqlite3.connect(db_path) as raw:
        iso_week = raw.execute("SELECT iso_week FROM strength_tests").fetchone()[0]
    assert iso_week == "2026-W23"  # 2026-06-01 is a Monday in ISO week 23


def test_absent_checkin_strength_flags_false(ctx) -> None:
    client, _app, db_path = ctx
    resp = client.post("/sync", json=BODY, headers=AUTH)  # no checkin/strengthTest
    body = resp.json()
    assert body["checkinSaved"] is False
    assert body["strengthTestSaved"] is False
    assert _table_count(db_path, "checkins") == 0
    assert _table_count(db_path, "strength_tests") == 0


def test_recompute_spy_called_once_with_affected_dates(ctx) -> None:
    client, app, _db = ctx
    spy = _RecomputeSpy()
    app.dependency_overrides[get_recompute] = lambda: spy
    resp = client.post("/sync", json=BODY_FULL, headers=AUTH)
    assert resp.status_code == 200
    assert len(spy.calls) == 1
    assert spy.calls[0] == affected_dates(SyncRequest.model_validate(BODY_FULL))


def test_recompute_called_with_empty_set_on_empty_body(ctx) -> None:
    client, app, _db = ctx
    spy = _RecomputeSpy()
    app.dependency_overrides[get_recompute] = lambda: spy
    resp = client.post("/sync", json={}, headers=AUTH)
    assert resp.status_code == 200
    assert spy.calls == [set()]  # called once, with the empty affected set


def test_sync_empty_body_writes_no_daily_metrics(ctx) -> None:
    # An empty body fans out to an empty affected set, so the real engine returns
    # before any DB work — no daily_metrics row is written.
    client, _app, db_path = ctx
    resp = client.post("/sync", json={}, headers=AUTH)
    assert resp.status_code == 200
    assert _table_count(db_path, "daily_metrics") == 0


def test_sync_recompute_failure_acks_200_with_recompute_ok_false(ctx) -> None:
    # The recompute seam fires AFTER /sync's commit. If the engine raises, the route
    # CATCHES it and acks 200 with recomputeOk=False (data-safety hardening): the
    # already-committed, idempotent ingest must not be reported as a failure, and one
    # poison day must not 5xx the client into a permanent retry loop that blocks the
    # brief. The affected day's daily_metrics is simply re-derived on the next sync.
    client, app, db_path = ctx

    def failing_recompute():
        def _raise(_dates) -> None:
            raise RuntimeError("recompute boom")

        return _raise

    app.dependency_overrides[get_recompute] = failing_recompute
    resp = client.post("/sync", json=BODY, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["recomputeOk"] is False
    # Ingest committed before recompute fired → durable.
    assert _table_count(db_path, "records") == 2
    assert _table_count(db_path, "workouts") == 1
    # The recompute never completed → no daily_metrics row (re-derived next sync).
    assert _table_count(db_path, "daily_metrics") == 0


def test_replay_keeps_checkin_strength_one_row(ctx) -> None:
    client, _app, db_path = ctx
    client.post("/sync", json=BODY_FULL, headers=AUTH)
    second = client.post("/sync", json=BODY_FULL, headers=AUTH)
    body = second.json()
    assert body["checkinSaved"] is True
    assert body["strengthTestSaved"] is True
    assert _table_count(db_path, "checkins") == 1  # upsert, not duplicate
    assert _table_count(db_path, "strength_tests") == 1
