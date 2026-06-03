"""Health + auth-probe route tests (E1·P2 TASK-003)."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.routes.health import get_clock
from app.core.settings import get_settings

VALID_TOKEN = "test-api-token-0123456789"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", "/tmp/app.db")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_health_ok_without_auth():
    resp = TestClient(create_app()).get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "serverTime" in body  # camelCase wire key
    assert datetime.fromisoformat(body["serverTime"]).utcoffset() is not None  # aware


@pytest.mark.parametrize(
    "utc_instant, expected_iso",
    [
        # Inject only the base UTC instant; the real ZoneInfo conversion must run.
        (datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc), "2026-01-15T14:00:00+02:00"),  # winter
        (datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc), "2026-07-15T15:00:00+03:00"),  # summer
    ],
)
def test_server_time_is_instant_preserving_dst_conversion(utc_instant, expected_iso):
    app = create_app()
    # Override only the UTC clock source — the astimezone(Sofia) conversion stays
    # in the production path, so a relabel or a fixed offset would fail this.
    app.dependency_overrides[get_clock] = lambda: (lambda: utc_instant)
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    parsed = datetime.fromisoformat(resp.json()["serverTime"])
    expected = datetime.fromisoformat(expected_iso)
    assert parsed == expected  # same instant (catches a relabel)
    assert parsed.utcoffset() == expected.utcoffset()  # DST offset (catches a fixed offset)
    assert parsed.hour == expected.hour  # wall-clock (catches a relabel)


def test_health_never_returns_401():
    resp = TestClient(create_app()).get("/health", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 200


def test_probe_demonstrates_auth_gate():
    client = TestClient(create_app())
    assert client.get("/probe").status_code == 401
    assert client.get("/probe").json()["error"]["code"] == "unauthorized"
    assert (
        client.get("/probe", headers={"Authorization": "Bearer wrong-token-value"}).status_code == 401
    )
    ok = client.get("/probe", headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert ok.status_code == 200
