"""Bearer-token auth dependency tests (E1·P2 TASK-002)."""

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.auth import require_auth
from app.core.settings import get_settings

VALID_TOKEN = "test-api-token-0123456789"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", "/tmp/app.db")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _client() -> TestClient:
    app = create_app()

    @app.get("/protected")
    def _protected(_: str = Depends(require_auth)):
        return {"ok": True}

    @app.get("/protected-2")
    def _protected2(_: str = Depends(require_auth)):
        return {"ok": True}

    return TestClient(app)


def _assert_bearer_challenge(resp):
    # Every 401 must carry the RFC 7235 Bearer challenge (review round-2 #2).
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_missing_header_is_unauthorized_envelope():
    resp = _client().get("/protected")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    assert resp.json()["error"]["detail"] is None
    _assert_bearer_challenge(resp)


def test_wrong_token_is_unauthorized():
    resp = _client().get("/protected", headers={"Authorization": "Bearer wrong-token-value"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    _assert_bearer_challenge(resp)


def test_non_bearer_scheme_is_unauthorized():
    resp = _client().get("/protected", headers={"Authorization": "Basic abc123"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    _assert_bearer_challenge(resp)


def test_correct_token_passes():
    resp = _client().get("/protected", headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_dependency_is_reusable_on_a_second_route():
    client = _client()
    assert client.get("/protected-2").status_code == 401
    ok = client.get("/protected-2", headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    assert ok.status_code == 200
