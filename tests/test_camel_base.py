"""CamelModel casing + null-vs-absent tests (E1·P1 TASK-004)."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.schemas.base import CamelModel


class _Sample(CamelModel):
    first_name: str
    last_seen: str | None = None


def test_raw_dump_emits_camel_without_by_alias():
    # Aliasing is configured on the model, so no by_alias=True at the call site.
    data = json.loads(_Sample(first_name="Ada").model_dump_json())
    assert data == {"firstName": "Ada", "lastSeen": None}


def test_accepts_both_camel_and_snake_input():
    assert _Sample(firstName="Ada").first_name == "Ada"  # alias (camelCase)
    assert _Sample(first_name="Ada").first_name == "Ada"  # field name (snake_case)


def test_optional_accepts_omission_and_explicit_null():
    assert _Sample(first_name="Ada").last_seen is None  # omitted
    assert _Sample(first_name="Ada", lastSeen=None).last_seen is None  # explicit null (alias)
    assert _Sample(first_name="Ada", last_seen=None).last_seen is None  # explicit null (field)


def test_route_returns_camel_wire_json():
    app = FastAPI()

    @app.get("/sample", response_model=_Sample)
    def _get() -> _Sample:
        return _Sample(first_name="Ada", last_seen="today")

    resp = TestClient(app).get("/sample")
    assert resp.status_code == 200
    assert resp.json() == {"firstName": "Ada", "lastSeen": "today"}
