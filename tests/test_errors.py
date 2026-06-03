"""Error envelope + exception handler tests (E1·P2 TASK-001)."""

import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app.api.errors import Error, ErrorCode, ErrorResponse, register_exception_handlers
from app.core.settings import get_settings

VALID_TOKEN = "test-api-token-0123456789"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", "/tmp/app.db")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _app_with_routes() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    class Body(BaseModel):
        n: int

    @app.get("/raise-404")
    def _r404():
        raise HTTPException(status_code=404)

    @app.get("/raise-400")
    def _r400():
        raise HTTPException(status_code=400)

    @app.get("/raise-401")
    def _r401():
        raise HTTPException(status_code=401)

    @app.get("/boom")
    def _boom():
        raise RuntimeError("secret internal detail")

    @app.get("/raise-500-detail")
    def _r500_detail():
        raise HTTPException(status_code=500, detail="db password leaked")

    @app.get("/raise-400-detail")
    def _r400_detail():
        raise HTTPException(status_code=400, detail="internal sql: SELECT secret")

    @app.post("/validate")
    def _validate(body: Body):
        return {"ok": body.n}

    return app


def test_404_envelope():
    resp = TestClient(_app_with_routes()).get("/raise-404")
    assert resp.status_code == 404
    err = resp.json()["error"]
    assert set(err) == {"code", "message", "detail"}
    assert err["code"] == "not_found"
    assert isinstance(err["message"], str) and err["message"]
    assert err["detail"] is None


def test_unknown_path_is_not_found_envelope():
    resp = TestClient(_app_with_routes()).get("/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_unmapped_status_falls_back_to_internal_error():
    resp = TestClient(_app_with_routes()).get("/raise-400")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "internal_error"


def test_no_detail_http_exceptions_have_message_and_null_detail():
    client = TestClient(_app_with_routes())
    for path, status in [("/raise-401", 401), ("/raise-404", 404), ("/raise-400", 400)]:
        resp = client.get(path)
        assert resp.status_code == status
        err = resp.json()["error"]
        assert isinstance(err["message"], str) and err["message"].strip()
        assert err["detail"] is None


def test_internal_error_never_echoes_caller_detail():
    # An HTTPException that resolves to internal_error must not leak its detail,
    # even when the caller passed one (review round-1 #1).
    client = TestClient(_app_with_routes())
    for path in ("/raise-500-detail", "/raise-400-detail"):
        resp = client.get(path)
        err = resp.json()["error"]
        assert err["code"] == "internal_error"
        assert err["detail"] is None
        assert "leaked" not in json.dumps(resp.json())
        assert "secret" not in json.dumps(resp.json())


def test_http_exception_headers_are_preserved():
    # A 405 must still carry its Allow header through the envelope (review round-1 #2).
    resp = TestClient(_app_with_routes()).post("/raise-404")
    assert resp.status_code == 405
    assert "allow" in {k.lower() for k in resp.headers}
    assert resp.json()["error"]["code"] == "internal_error"


def test_validation_error_envelope():
    resp = TestClient(_app_with_routes()).post("/validate", json={"n": "not-an-int"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_unhandled_exception_is_internal_error_without_leak():
    client = TestClient(_app_with_routes(), raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    err = resp.json()["error"]
    assert err["code"] == "internal_error"
    assert err["detail"] is None
    assert "secret internal detail" not in json.dumps(resp.json())


def test_error_model_camel_and_null_detail():
    payload = ErrorResponse(error=Error(code=ErrorCode.not_found, message="x"))
    assert json.loads(payload.model_dump_json()) == {
        "error": {"code": "not_found", "message": "x", "detail": None}
    }
    assert Error(code=ErrorCode.not_found, message="x").detail is None
    assert Error(code=ErrorCode.not_found, message="x", detail=None).detail is None


def test_invalid_code_rejected():
    with pytest.raises(ValidationError):
        Error(code="totally_made_up", message="x")


def test_create_app_wires_handlers():
    from app.api.app import create_app

    resp = TestClient(create_app()).get("/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
