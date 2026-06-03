"""App-factory tests (E1·P1 TASK-002).

`create_app()` must load and validate settings *at construction time* so a
missing required env var fails the boot (and therefore `uvicorn app.main:app`),
not lazily inside a lifespan hook a bare TestClient could skip.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.app import create_app
from app.core.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set_required(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("APP_DB_PATH", "/tmp/app.db")


def test_create_app_returns_fastapi(monkeypatch):
    _set_required(monkeypatch)
    app = create_app()
    assert isinstance(app, FastAPI)


def test_testclient_builds_and_openapi_exposed(monkeypatch):
    _set_required(monkeypatch)
    client = TestClient(create_app())
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["openapi"].startswith("3.")


def test_missing_required_env_makes_create_app_raise(monkeypatch, tmp_path):
    # chdir to a dir with no `.env` so the failure is driven purely by env.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("APP_DB_PATH", raising=False)
    with pytest.raises(ValidationError):
        create_app()
