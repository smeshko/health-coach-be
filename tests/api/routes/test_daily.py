"""E11·P3 TASK-002: POST /brief/daily endpoint tests (over a migrated temp app.db).

The route is the thin HTTP shell over the TASK-001 get-or-generate service. The
``DAILY_ADJUSTER`` workflow is **mocked**: ``get_daily_generator`` is overridden with a
counting stub that mirrors ``PersistSuggestionNode`` (inserts one ``suggestions`` row on the
request session, no commit) — so no LLM/network runs, but the realistic row-write + commit
path the service owns is exercised end-to-end. ``get_clock`` is pinned so the default-date
resolution is deterministic.
"""

from __future__ import annotations

import json
import sqlite3
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
from app.core.agent_node import BriefGenerationError
from app.core.settings import get_settings
from app.core.time import get_clock
from app.database.engine import get_engine, get_session
from app.database.models import Suggestions
from app.services.daily_brief import GeneratedDailyBrief

VALID_TOKEN = "test-api-token-0123456789"
AUTH = {"Authorization": f"Bearer {VALID_TOKEN}"}

# 2026-06-04 09:00 UTC → Europe/Sofia (UTC+3 summer) 2026-06-04 → the "current" date.
FIXED_UTC = datetime(2026, 6, 4, 9, 0, 0, tzinfo=timezone.utc)
CURRENT_DATE = "2026-06-04"


def _migrate(db_path) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.attributes["test_db_url"] = f"sqlite:///{db_path}"
    command.upgrade(cfg, "head")


def _data(date: str, *, marker: str = "v1", gated: bool = False, intake: bool = True) -> dict:
    gate = (
        {"triggered": True, "reasons": ["knee_pain_high"], "overrideTo": "mobility"}
        if gated
        else {"triggered": False, "reasons": [], "overrideTo": None}
    )
    return {
        "date": date,
        "readiness": {"score": 82, "band": "green", "penalties": []},
        "safetyGate": gate,
        "session": {
            "card": "mobility" if gated else "easy_run",
            "intensity": "recovery" if gated else "easy",
            "zoneTarget": None if gated else "z2",
            "durationMinLow": 20 if gated else 30,
            "durationMinHigh": 30 if gated else 40,
            "hrCapBpm": None,
            "cadenceSpm": None if gated else 165,
            "flags": [],
        },
        "alternatives": [],
        "skipOk": True if gated else False,
        "dayType": "rest" if gated else "moderate",
        "macroFocus": {
            "dayType": "rest" if gated else "moderate",
            "caloriesKcal": 2200 if gated else 2510,
            "proteinG": 140,
            "carbsG": 150 if gated else 250,
            "fatGLow": 70,
            "fatGHigh": 90,
            "hydrationLLow": 2.5,
            "hydrationLHigh": 3.5,
        },
        "intakeYesterday": (
            {
                "date": "2026-06-03",
                "caloriesKcal": 2610,
                "proteinG": 138,
                "carbsG": 250,
                "fatG": 82,
                "fiberG": 21,
                "waterL": 2.4,
                "vsTarget": {"caloriesPct": 1.04, "proteinHit": False},
            }
            if intake and not gated
            else None
        ),
        "marker": marker,
    }


def _narrative(gated: bool = False) -> list[dict]:
    if gated:
        return [{"type": "caution", "heading": "Recovery", "body": "Rest it today."}]
    return [{"type": "summary", "heading": "Steady", "body": "Keep it aerobic."}]


class _StubGenerator:
    """Mirrors ``PersistSuggestionNode``: inserts one ``suggestions`` row (no commit)."""

    def __init__(self, *, marker: str = "v1", gated: bool = False) -> None:
        self.calls = 0
        self.marker = marker
        self.gated = gated

    def __call__(self, session: Session, date: str) -> GeneratedDailyBrief:
        self.calls += 1
        data = _data(date, marker=self.marker, gated=self.gated)
        narrative = _narrative(self.gated)
        session.execute(
            insert(Suggestions).values(
                date=date,
                payload=json.dumps({"data": data, "narrative": narrative}),
                readiness_score=82,
                band="green",
                safety_gate_tripped=1 if self.gated else 0,
                gate_reason="knee_pain_high" if self.gated else None,
                inputs_snapshot=json.dumps({"readiness": data["readiness"]}),
                model=None if self.gated else "claude-opus-4-8",
                constitution_version="2026.1",
                created_at="2026-06-04T12:00:00+03:00",
            )
        )
        return GeneratedDailyBrief(
            data=data,
            narrative=narrative,
            readiness_score=82,
            band="green",
            safety_gate_tripped=1 if self.gated else 0,
            gate_reason="knee_pain_high" if self.gated else None,
            model=None if self.gated else "claude-opus-4-8",
            constitution_version="2026.1",
            generated_at="2026-06-04T12:00:00+03:00",
        )


class _RaisingGenerator:
    """The `(date) -> brief` seam, but raises an in-engine failure (no row written)."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.calls = 0

    def __call__(self, date: str) -> GeneratedDailyBrief:
        self.calls += 1
        raise BriefGenerationError(code=self.code)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    _migrate(db_path)
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", str(db_path))
    get_settings.cache_clear()
    get_engine.cache_clear()
    app = create_app()
    app.dependency_overrides[get_clock] = lambda: (lambda: FIXED_UTC)
    client = TestClient(app, raise_server_exceptions=False)
    yield client, app, db_path
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


class _BoundGenerator:
    def __init__(self, stub, session) -> None:
        self._stub = stub
        self._session = session

    def __call__(self, date: str) -> GeneratedDailyBrief:
        return self._stub(self._session, date)


def _use_generator(app, stub) -> None:
    def _provider(session: Session = Depends(get_session)):
        return _BoundGenerator(stub, session)

    app.dependency_overrides[get_daily_generator] = _provider


def _count(db_path) -> int:
    with sqlite3.connect(db_path) as raw:
        return raw.execute("SELECT COUNT(*) FROM suggestions").fetchone()[0]


# --------------------------------------------------------------------------- #
# Miss → 200, cached=false, one row, code readiness/gate, intakeYesterday.
# --------------------------------------------------------------------------- #
def test_miss_returns_200_cached_false_one_row(ctx):
    client, app, db_path = ctx
    stub = _StubGenerator()
    _use_generator(app, stub)

    resp = client.post("/brief/daily", json={}, headers=AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["cached"] is False
    assert body["data"]["date"] == CURRENT_DATE  # default = fixed clock's Sofia date
    assert body["data"]["readiness"]["band"] == "green"
    assert body["data"]["safetyGate"]["triggered"] is False
    assert body["data"]["intakeYesterday"]["caloriesKcal"] == 2610
    assert stub.calls == 1
    assert _count(db_path) == 1


def test_hit_returns_cached_true_no_regenerate(ctx):
    client, app, db_path = ctx
    stub = _StubGenerator()
    _use_generator(app, stub)

    first = client.post("/brief/daily", json={}, headers=AUTH).json()
    second_resp = client.post("/brief/daily", json={}, headers=AUTH)
    second = second_resp.json()
    assert second_resp.status_code == 200
    assert second["data"]["cached"] is True
    assert stub.calls == 1  # not re-invoked
    # The bodies match except `cached`.
    assert second["narrative"] == first["narrative"]
    assert second["data"]["intakeYesterday"] == first["data"]["intakeYesterday"]
    assert _count(db_path) == 1


def test_refresh_regenerates(ctx):
    client, app, db_path = ctx
    _use_generator(app, _StubGenerator(marker="v1"))
    client.post("/brief/daily", json={}, headers=AUTH)
    stub2 = _StubGenerator(marker="v2")
    _use_generator(app, stub2)

    resp = client.post("/brief/daily?refresh=true", json={}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["data"]["cached"] is False
    assert stub2.calls == 1
    assert _count(db_path) == 1


def test_explicit_date_honored(ctx):
    client, app, db_path = ctx
    stub = _StubGenerator()
    _use_generator(app, stub)
    resp = client.post("/brief/daily", json={"date": "2026-05-30"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["data"]["date"] == "2026-05-30"


@pytest.mark.parametrize("bad", ["garbage", "2026-13-40"])
def test_malformed_date_422(ctx, bad):
    client, app, _ = ctx
    _use_generator(app, _StubGenerator())
    resp = client.post("/brief/daily", json={"date": bad}, headers=AUTH)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_gate_tripped_is_200_normal_brief(ctx):
    client, app, db_path = ctx
    stub = _StubGenerator(gated=True)
    _use_generator(app, stub)

    resp = client.post("/brief/daily", json={}, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["safetyGate"]["triggered"] is True
    assert body["data"]["session"]["card"] == "mobility"
    assert body["data"]["alternatives"] == []
    assert body["narrative"]  # non-empty code narrative
    assert _count(db_path) == 1  # persisted (a success, not an error)


def test_auth_required(ctx):
    client, app, _ = ctx
    _use_generator(app, _StubGenerator())

    no_header = client.post("/brief/daily", json={})
    assert no_header.status_code == 401
    assert no_header.json()["error"]["code"] == "unauthorized"
    assert no_header.headers.get("WWW-Authenticate") == "Bearer"

    wrong = client.post("/brief/daily", json={}, headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    ("code", "status"),
    [("brief_generation_failed", 502), ("upstream_timeout", 504)],
)
def test_workflow_failure_maps_envelope_no_row(ctx, code, status):
    client, app, db_path = ctx

    def _provider(session: Session = Depends(get_session)):
        return _RaisingGenerator(code)

    app.dependency_overrides[get_daily_generator] = _provider

    resp = client.post("/brief/daily", json={}, headers=AUTH)
    assert resp.status_code == status
    assert resp.json()["error"]["code"] == code
    assert _count(db_path) == 0  # nothing cached on a failure
