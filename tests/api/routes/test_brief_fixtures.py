"""BRIEF_FIXTURES mode: the brief endpoints serve canned briefs with no LLM.

When ``BRIEF_FIXTURES=1``, ``create_app()`` overrides the two generator providers with
static-fixture ones (``app/api/brief_fixtures.py``). These tests assert that — without any
workflow/LLM stub of their own — ``POST /brief/weekly`` and ``POST /brief/daily`` return a
valid ``200`` brief for any requested period, write **no** ``plans``/``suggestions`` row
(``cached`` stays ``false``), and stay idempotent across repeated calls. This is the seam the
iOS app / curl use to exercise the API at zero LLM cost; if the shipped fixtures drift out of
the wire contract, this fails loudly at the boundary rather than 500-ing a real client.
"""

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
FIXED_UTC = datetime(2026, 6, 4, 9, 0, 0, tzinfo=timezone.utc)


def _migrate(db_path) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.attributes["test_db_url"] = f"sqlite:///{db_path}"
    command.upgrade(cfg, "head")


def _count(db_path, table: str) -> int:
    with sqlite3.connect(db_path) as raw:
        return raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    _migrate(db_path)
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", str(db_path))
    monkeypatch.setenv("BRIEF_FIXTURES", "1")
    get_settings.cache_clear()
    get_engine.cache_clear()
    app = create_app()
    app.dependency_overrides[get_clock] = lambda: (lambda: FIXED_UTC)
    yield TestClient(app, raise_server_exceptions=False), db_path
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_weekly_fixture_served_without_llm(client):
    http, db_path = client
    resp = http.post("/brief/weekly", json={"isoWeek": "2026-W24"}, headers=AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["isoWeek"] == "2026-W24"
    assert body["data"]["weekStart"] == "2026-06-08"  # Monday of ISO 2026-W24
    assert body["data"]["cached"] is False
    assert body["data"]["generatedAt"] is not None
    assert body["data"]["budgets"]["hardDays"] == 3
    assert len(body["narrative"]) >= 1
    # The fixture generator writes no row — nothing is persisted.
    assert _count(db_path, "plans") == 0


def test_daily_fixture_served_without_llm(client):
    http, db_path = client
    resp = http.post("/brief/daily", json={"date": "2026-06-04"}, headers=AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["date"] == "2026-06-04"
    assert body["data"]["cached"] is False
    assert body["data"]["readiness"]["band"] == "green"
    assert body["data"]["session"]["card"] == "threshold"
    assert len(body["narrative"]) >= 1
    assert _count(db_path, "suggestions") == 0


def test_default_period_resolves_from_pinned_clock(client):
    """An empty body targets the current Europe/Sofia period — still served, still free."""
    http, _ = client
    assert http.post("/brief/weekly", json={}, headers=AUTH).json()["data"]["isoWeek"] == "2026-W23"
    assert http.post("/brief/daily", json={}, headers=AUTH).json()["data"]["date"] == "2026-06-04"


def test_fixture_mode_is_idempotent_and_unauthenticated_still_401(client):
    http, _ = client
    # Repeated calls keep returning the fixture (no LLM, no error).
    for _ in range(3):
        assert http.post("/brief/daily", json={"date": "2026-06-04"}, headers=AUTH).status_code == 200
    # Auth is unchanged — fixtures mode does not open the gate.
    assert http.post("/brief/daily", json={}).status_code == 401
