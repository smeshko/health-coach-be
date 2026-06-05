"""E14·P1 TASK-002: GET /profile endpoint tests — authed, camelCase, side-effect-free.

The endpoint is a pure `load_profile()` read (no DB), so the env fixture only sets API_TOKEN +
APP_DB_PATH (the latter for Settings validation; the route never opens a session) — no Alembic
migration needed, mirroring tests/test_auth.py.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.core.profile import load_profile
from app.core.settings import get_settings

VALID_TOKEN = "test-api-token-0123456789"
AUTH = {"Authorization": f"Bearer {VALID_TOKEN}"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", "/tmp/app.db")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def test_profile_requires_auth():
    resp = _client().get("/profile")  # no token
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_profile_returns_camel_constants():
    resp = _client().get("/profile", headers=AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    profile = load_profile()

    assert set(body) == {"athlete", "zones", "thresholds", "meta"}
    assert set(body["athlete"]) == {"age", "sex", "heightCm", "goalWeightKg"}
    assert body["athlete"]["heightCm"] == profile.athlete.height_cm
    assert body["athlete"]["goalWeightKg"] == profile.athlete.goal_weight_kg

    thresholds = body["thresholds"]
    assert set(thresholds) == {
        "maxHr", "rhrBaseline", "hrvBaselineMs", "easyHrCap",
        "cadenceCurrentSpm", "cadenceTargetSpm",
    }
    assert thresholds["maxHr"] == profile.thresholds.max_hr
    assert thresholds["hrvBaselineMs"] == profile.thresholds.hrv_baseline_ms
    assert thresholds["cadenceCurrentSpm"] == profile.thresholds.cadence_current_spm

    assert body["meta"]["constitutionVersion"] == profile.meta.constitution_version
    assert "constantsRecomputedWeek" in body["meta"]


def test_profile_zone_ranges_low_high():
    resp = _client().get("/profile", headers=AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    profile = load_profile()
    bounds = profile.zone_bounds()

    assert set(body["zones"]) == {"z1", "z2", "z3", "z4", "z5"}
    z4_low, z4_high = bounds["z4"]
    assert body["zones"]["z4"] == {"low": z4_low, "high": z4_high}
    # The top zone's high bound is the max HR (the §4.2 ceiling).
    assert body["zones"]["z5"]["high"] == profile.thresholds.max_hr


def test_profile_is_side_effect_free():
    """Structural guarantee: the route's only data source is load_profile() — it declares no DB
    session and triggers no recompute (so it cannot write or mutate state)."""
    import app.api.routes.profile as profile_module

    src = inspect.getsource(profile_module)
    for forbidden in ("get_session", "Session", "recompute"):
        assert forbidden not in src


def test_profile_excludes_nutrition_and_current_weight():
    body_text = _client().get("/profile", headers=AUTH).text
    for forbidden in (
        "activityFactor", "deficitPct", "proteinGPerKg", "bodyWeight", "currentWeight",
    ):
        assert forbidden not in body_text
