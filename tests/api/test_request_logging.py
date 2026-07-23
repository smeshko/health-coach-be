"""Request/response debug-log middleware tests (app/api/request_logging.py).

Exercises the REQUEST_LOG_PATH-armed path through the real app factory: JSON
lines with both bodies, secret redaction, /health exclusion, body-size caps,
and the default-off behavior when the env var is absent.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.core.settings import get_settings

VALID_TOKEN = "test-api-token-0123456789"
AUTH = {"Authorization": f"Bearer {VALID_TOKEN}"}


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    path = tmp_path / "requests.jsonl"
    # Run away from the repo root so the developer/deploy `.env` (REQUEST_LOG_*
    # included, once deployed) can never leak into these assertions.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("REQUEST_LOG_PATH", str(path))
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


def _lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_logs_full_request_and_response_pair(log_path):
    # /sync reads + validates the body before touching the DB; a wrong-typed known
    # field exercises body capture end-to-end and answers with the 422 envelope.
    resp = TestClient(create_app()).post("/sync", json={"records": "nope"}, headers=AUTH)
    assert resp.status_code == 422

    (line,) = _lines(log_path)
    assert line["method"] == "POST"
    assert line["path"] == "/sync"
    assert line["status"] == 422
    assert line["requestBody"] == {"records": "nope"}  # parsed JSON, not an opaque string
    assert line["responseBody"]["error"]["code"] == "validation_error"
    assert isinstance(line["durationMs"], float)
    assert line["ts"]  # ISO timestamp present


def test_authorization_header_is_redacted(log_path):
    TestClient(create_app()).post("/sync", json={}, headers=AUTH)

    (line,) = _lines(log_path)
    assert line["requestHeaders"]["authorization"] == "<redacted>"
    assert VALID_TOKEN not in log_path.read_text()  # the secret never lands on disk


def test_health_polling_is_excluded(log_path):
    client = TestClient(create_app())
    assert client.get("/health").status_code == 200
    assert client.get("/probe").status_code == 401  # unauthenticated → logged

    (line,) = _lines(log_path)  # exactly one line: /health skipped, /probe kept
    assert line["path"] == "/probe"
    assert line["status"] == 401
    assert line["responseBody"]["error"]["code"] == "unauthorized"


def test_oversized_body_is_truncated_with_true_size_recorded(log_path, monkeypatch):
    monkeypatch.setenv("REQUEST_LOG_MAX_BODY", "64")
    get_settings.cache_clear()

    payload = {"blob": "x" * 500}
    TestClient(create_app()).post("/sync", json=payload, headers=AUTH)

    (line,) = _lines(log_path)
    assert line["requestBodyBytesTotal"] >= 500  # true size survives the cap
    assert isinstance(line["requestBody"], str)  # truncated capture no longer parses
    assert len(line["requestBody"]) <= 64


def test_disabled_without_request_log_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # a deploy `.env` sets REQUEST_LOG_PATH; keep it out
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("REQUEST_LOG_PATH", raising=False)
    get_settings.cache_clear()
    try:
        app = create_app()
        assert TestClient(app).get("/health").status_code == 200
        assert app.user_middleware == []  # middleware not installed when unset
    finally:
        get_settings.cache_clear()
