"""E5·P2 TASK-003: POST /sync endpoint tests (over a migrated temp app.db)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.core.settings import get_settings
from app.core.time import get_clock
from app.database.engine import get_engine

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


def test_sync_does_not_touch_daily_metrics(ctx) -> None:
    client, _app, db_path = ctx
    client.post("/sync", json=BODY, headers=AUTH)
    assert _table_count(db_path, "daily_metrics") == 0  # no recompute this phase
