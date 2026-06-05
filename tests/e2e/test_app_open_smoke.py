"""E12·P3 end-to-end smoke — the app-open sequence (epic R5; ARCHITECTURE §4).

Drives the real `POST /sync` → `POST /brief/daily` → `POST /brief/weekly` over a fresh
migrated temp `app.db` (the E2 pattern), with the brief **generators stubbed** via the
E10·P3/E11·P3 `dependency_overrides` seam (no Claude call, no network) and a fixed clock.
It asserts the `{ data, narrative }` shapes and the get-or-generate **cache behaviour**
(second call → `cached=true`, the generator not re-invoked). Langfuse is off (no keys →
no-op). It asserts no computed metric value — only that the sequence is green end-to-end.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.api.app import create_app
from app.api.routes.daily import get_daily_generator
from app.api.routes.weekly import get_weekly_generator
from app.core.settings import get_settings
from app.core.time import get_clock
from app.database.engine import get_engine, get_session
from app.database.models import Plans, Suggestions
from app.services.daily_brief import GeneratedDailyBrief
from app.services.weekly_plan import GeneratedWeeklyPlan

VALID_TOKEN = "test-api-token-0123456789"
AUTH = {"Authorization": f"Bearer {VALID_TOKEN}"}

# 2026-06-04 09:00 UTC → Europe/Sofia 2026-06-04 (Thu), ISO week 2026-W23.
FIXED_UTC = datetime(2026, 6, 4, 9, 0, 0, tzinfo=timezone.utc)
TODAY = "2026-06-04"
ISO_WEEK = "2026-W23"
STAMP = "2026-06-04T12:00:00+03:00"


def _migrate(db_path) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.attributes["test_db_url"] = f"sqlite:///{db_path}"
    command.upgrade(cfg, "head")


def _sync_body() -> dict:
    return {
        "records": [
            {
                "uuid": "smoke-r1",
                "type": "heart_rate",
                "start": f"{TODAY}T08:00:00+03:00",
                "end": f"{TODAY}T08:00:30+03:00",
                "value": 57.0,
                "unit": "count/min",
            },
            {
                "uuid": "smoke-r2",
                "type": "body_mass",
                "start": f"{TODAY}T07:00:00+03:00",
                "end": f"{TODAY}T07:00:00+03:00",
                "value": 78.4,
                "unit": "kg",
            },
        ],
        "checkin": {
            "date": TODAY,
            "giSymptoms": False,
            "kneePain": 0,
            "illness": False,
        },
    }


def _daily_data() -> dict:
    return {
        "date": TODAY,
        "readiness": {"score": 82, "band": "green", "penalties": []},
        "safetyGate": {"triggered": False, "reasons": [], "overrideTo": None},
        "session": {
            "card": "easy_run",
            "intensity": "easy",
            "zoneTarget": "z2",
            "durationMinLow": 30,
            "durationMinHigh": 40,
            "hrCapBpm": 146,
            "cadenceSpm": 165,
            "flags": ["impact"],
        },
        "alternatives": [],
        "skipOk": False,
        "dayType": "moderate",
        "macroFocus": {
            "dayType": "moderate",
            "caloriesKcal": 2510,
            "proteinG": 140,
            "carbsG": 250,
            "fatGLow": 70,
            "fatGHigh": 90,
            "hydrationLLow": 2.5,
            "hydrationLHigh": 3.5,
        },
        "intakeYesterday": None,
    }


def _weekly_data() -> dict:
    return {
        "isoWeek": ISO_WEEK,
        "weekStart": "1970-01-01",  # overwritten by the route from the resolved key
        "budgets": {"hard_days": 3, "strength_sessions": 2, "long_run_km": None, "deload": False},
        "core": [
            {
                "card": "easy_run",
                "tier": "core",
                "intensity": "easy",
                "isHardDay": False,
                "suggestedDay": None,
                "zoneTarget": "z2",
                "durationMinLow": 40,
                "durationMinHigh": 50,
                "flags": [],
            }
        ],
        "extras": [],
        "targets": {
            "totalRunKm": 30.0,
            "easyRunRatio": 0.8,
            "strengthSessions": 2,
            "hardDays": 3,
            "cadenceSpm": 180,
        },
        "nutrition": {
            "proteinG": 150,
            "fatGLow": 60,
            "fatGHigh": 80,
            "hydrationLLow": 2.5,
            "hydrationLHigh": 3.5,
            "avgCaloriesKcal": 2600,
            "dayTypePattern": [],
            "lastWeek": None,
        },
        "constantsRecomputed": False,
    }


class _DailyStub:
    """Mirrors `PersistSuggestionNode`: inserts one `suggestions` row (no commit), counts."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, session: Session, date: str) -> GeneratedDailyBrief:
        self.calls += 1
        data = _daily_data()
        narrative = [{"type": "summary", "heading": "Steady", "body": "Keep it aerobic."}]
        session.execute(
            insert(Suggestions).values(
                date=date,
                payload=json.dumps({"data": data, "narrative": narrative}),
                readiness_score=82,
                band="green",
                safety_gate_tripped=0,
                inputs_snapshot=json.dumps({"readiness": data["readiness"]}),
                model="claude-opus-4-8",
                constitution_version="v1",
                created_at=STAMP,
            )
        )
        return GeneratedDailyBrief(
            data=data,
            narrative=narrative,
            readiness_score=82,
            band="green",
            safety_gate_tripped=0,
            model="claude-opus-4-8",
            constitution_version="v1",
            generated_at=STAMP,
        )


class _WeeklyStub:
    """Mirrors `PersistPlanNode`: inserts one `plans` row (no commit), counts."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, session: Session, iso_week: str) -> GeneratedWeeklyPlan:
        self.calls += 1
        data = _weekly_data()
        narrative = [{"type": "plan", "heading": "Week ahead", "body": "Build base."}]
        session.execute(
            insert(Plans).values(
                iso_week=iso_week,
                payload=json.dumps(data),
                rationale=json.dumps(narrative),
                inputs_snapshot=json.dumps({"aggregates": {}, "constants": None}),
                model="claude-opus-4-8",
                constitution_version="v1",
                created_at=STAMP,
            )
        )
        return GeneratedWeeklyPlan(
            data=data,
            narrative=narrative,
            rationale=json.dumps(narrative),
            inputs_snapshot={"aggregates": {}, "constants": None},
            model="claude-opus-4-8",
            constitution_version="v1",
            generated_at=STAMP,
        )


@pytest.fixture
def smoke(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    _migrate(db_path)
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", str(db_path))
    get_settings.cache_clear()
    get_engine.cache_clear()

    app = create_app()
    app.dependency_overrides[get_clock] = lambda: (lambda: FIXED_UTC)

    daily_stub = _DailyStub()
    weekly_stub = _WeeklyStub()

    # The generator seam takes only the period key; bind the stub to the request session
    # (the same one the service commits / the next request's lookup reads) — the real cache.
    def _daily_provider(session: Session = Depends(get_session)):
        return lambda date: daily_stub(session, date)

    def _weekly_provider(session: Session = Depends(get_session)):
        return lambda iso_week: weekly_stub(session, iso_week)

    app.dependency_overrides[get_daily_generator] = _daily_provider
    app.dependency_overrides[get_weekly_generator] = _weekly_provider

    client = TestClient(app, raise_server_exceptions=False)
    yield client, daily_stub, weekly_stub
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_app_open_sequence_end_to_end(smoke):
    client, daily_stub, weekly_stub = smoke

    # --- Step 1: POST /sync ---
    sync = client.post("/sync", json=_sync_body(), headers=AUTH)
    assert sync.status_code == 200, sync.text
    sr = sync.json()
    assert sr["recordsUpserted"] >= 0
    assert sr["checkinSaved"] is True

    # --- Step 2: POST /brief/daily (default → today) ---
    d1 = client.post("/brief/daily", json={}, headers=AUTH)
    assert d1.status_code == 200, d1.text
    db1 = d1.json()
    assert set(db1) >= {"data", "narrative"}
    assert db1["data"]["date"] == TODAY
    assert db1["data"]["cached"] is False  # first call generates
    assert db1["narrative"]
    # Second call for the same day → cache hit, generator NOT re-invoked.
    d2 = client.post("/brief/daily", json={}, headers=AUTH)
    assert d2.status_code == 200
    assert d2.json()["data"]["cached"] is True
    assert daily_stub.calls == 1

    # --- Step 3: POST /brief/weekly (default → current ISO week) ---
    w1 = client.post("/brief/weekly", json={}, headers=AUTH)
    assert w1.status_code == 200, w1.text
    wb1 = w1.json()
    assert set(wb1) >= {"data", "narrative"}
    assert wb1["data"]["isoWeek"] == ISO_WEEK
    assert wb1["data"]["cached"] is False  # first call generates
    assert wb1["narrative"]
    # Second call → cache hit, generator NOT re-invoked.
    w2 = client.post("/brief/weekly", json={}, headers=AUTH)
    assert w2.status_code == 200
    assert w2.json()["data"]["cached"] is True
    assert weekly_stub.calls == 1


def test_app_open_sequence_requires_auth(smoke):
    client, _daily_stub, _weekly_stub = smoke
    # The auth gate: the first authed endpoint with NO token → 401 unauthorized.
    no_token = client.post("/sync", json=_sync_body())
    assert no_token.status_code == 401
    assert no_token.json()["error"]["code"] == "unauthorized"
