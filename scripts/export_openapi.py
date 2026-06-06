"""Export the full OpenAPI 3.1 spec for the iOS client.

FastAPI already derives a spec from the live route models, but the raw
`app.openapi()` output omits things an external client needs and gets one thing
wrong:

  * no `servers` block (the client has no base URL to target);
  * the only documented non-2xx is FastAPI's default `422`, whose schema is
    `{detail: [...]}` — but `register_exception_handlers` (app/api/errors.py)
    rewrites *every* non-2xx into the single `{ "error": { code, message,
    detail } }` envelope, so the generated `422` shape is wrong and `401`/`500`/
    `502`/`504` aren't described at all;
  * auto-generated `operationId`s (`weekly_brief_brief_weekly_post`) make ugly
    Swift method names.

This script builds the base spec, overlays the real error contract, clean
`operationId`s, tags, servers and convention docs, then writes both
`openapi.json` and `openapi.yaml` at the repo root. Run it whenever the wire
models change so the handed-off spec stays in sync with the code:

    uv run python scripts/export_openapi.py        # or: .venv/bin/python …
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Minimal config so create_app()'s startup validation passes when this is run
# outside a configured shell — these never reach the wire, they only satisfy the
# Settings validators (a non-placeholder token + a durable, non-forbidden db path).
os.environ.setdefault("API_TOKEN", "openapi-export-dummy-token-0123456789")
os.environ.setdefault("APP_DB_PATH", "./app.db")

import yaml  # noqa: E402  (after env defaults so the import graph boots clean)

from app.api.app import create_app  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

INFO_DESCRIPTION = """\
Backend for the Coach App — deterministic health-metric ingestion plus LLM-authored
training/nutrition briefs. This spec is the contract for the iOS client.

## Conventions

- **JSON casing** — every field on the wire is **camelCase**. Input is accepted in
  either casing, but responses are always camelCase.
- **Authentication** — every route except `GET /health` requires
  `Authorization: Bearer <token>`, a single long-lived token shared by the one user
  (no per-user accounts). A missing or wrong token returns `401` with the error
  envelope and a `WWW-Authenticate: Bearer` header.
- **Errors** — every non-2xx response is the single envelope
  `{ "error": { "code", "message", "detail" } }`. `code` is a closed enum
  (`validation_error`, `unauthorized`, `not_found`, `brief_generation_failed`,
  `upstream_timeout`, `internal_error`); `message` is a safe public string;
  `detail` is an optional extra string (populated for validation errors, otherwise
  `null`). Internal exception text is never put on the wire.
- **Timestamps** — `serverTime` / `generatedAt` are ISO-8601 instants rendered in
  **Europe/Sofia** local time (DST-aware: +02:00 winter, +03:00 summer).
- **Nulls vs absent** — optional fields may be omitted or sent as explicit `null`;
  the two are treated identically.

## Briefs: get-or-generate + caching

`POST /brief/weekly` and `POST /brief/daily` are **get-or-generate**: they return a
cached brief for the requested period if one exists, otherwise generate (LLM) and
persist it. Send `{}` as the body to target the current Europe/Sofia period, or set
`isoWeek` / `date` to target a specific one. Pass `?refresh=true` to force
regeneration. The response's `data.cached` flag tells you which path ran.

A **tripped safety gate** on the daily brief is a normal `200` response
(`data.safetyGate.triggered = true` with an override session), never an error.
Brief generation failures surface as `502` (`brief_generation_failed`) or `504`
(`upstream_timeout`).
"""

# Reusable bearer-token scheme description (the scheme itself is auto-detected from
# the HTTPBearer dependency; we only enrich its docs).
SECURITY_SCHEME = {
    "type": "http",
    "scheme": "bearer",
    "bearerFormat": "opaque",
    "description": (
        "Single long-lived bearer token shared by the one user. Send as "
        "`Authorization: Bearer <token>` on every route except `GET /health`."
    ),
}

# Per-route overlay: clean operationId, tag, summary, whether it is auth-gated, and
# which error statuses it can actually emit (drives the response refs below).
ROUTES: dict[tuple[str, str], dict] = {
    ("get", "/health"): {
        "operationId": "getHealth",
        "tags": ["System"],
        "summary": "Liveness ping (unauthenticated)",
        "auth": False,
        "errors": [500],
    },
    ("get", "/probe"): {
        "operationId": "probeAuth",
        "tags": ["System"],
        "summary": "Auth probe — 200 with a valid token, 401 without",
        "auth": True,
        "errors": [401, 500],
    },
    ("post", "/sync"): {
        "operationId": "syncHealthData",
        "tags": ["Ingest"],
        "summary": "Ingest HealthKit records, workouts, activity, check-in & strength test",
        "auth": True,
        "errors": [401, 422, 500],
    },
    ("post", "/brief/weekly"): {
        "operationId": "getWeeklyBrief",
        "tags": ["Briefs"],
        "summary": "Get or generate the weekly training/nutrition brief",
        "auth": True,
        "errors": [401, 422, 500, 502, 504],
    },
    ("post", "/brief/daily"): {
        "operationId": "getDailyBrief",
        "tags": ["Briefs"],
        "summary": "Get or generate the daily brief (readiness + tuned session)",
        "auth": True,
        "errors": [401, 422, 500, 502, 504],
    },
    ("get", "/profile"): {
        "operationId": "getProfile",
        "tags": ["Profile"],
        "summary": "Read profile constants (athlete, HR zones, thresholds, meta)",
        "auth": True,
        "errors": [401, 500],
    },
}

# Error status -> the reusable response component it maps to.
ERROR_RESPONSE_REF = {
    401: "Unauthorized",
    422: "RequestValidationError",
    500: "InternalError",
    502: "BriefGenerationFailed",
    504: "UpstreamTimeout",
}

TAGS = [
    {"name": "System", "description": "Liveness and auth probes."},
    {"name": "Ingest", "description": "HealthKit data ingestion."},
    {"name": "Briefs", "description": "Get-or-generate weekly and daily coaching briefs."},
    {"name": "Profile", "description": "Read-only profile constants."},
]


def _error_schemas() -> dict[str, dict]:
    """The `{ "error": { code, message, detail } }` envelope, as JSON Schema."""
    return {
        "ErrorCode": {
            "type": "string",
            "enum": [
                "validation_error",
                "unauthorized",
                "not_found",
                "brief_generation_failed",
                "upstream_timeout",
                "internal_error",
            ],
            "description": "Closed set of stable machine-readable error codes.",
        },
        "Error": {
            "type": "object",
            "required": ["code", "message"],
            "properties": {
                "code": {"$ref": "#/components/schemas/ErrorCode"},
                "message": {"type": "string", "description": "Safe public message."},
                "detail": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "Optional extra context (e.g. which field failed validation).",
                },
            },
        },
        "ErrorResponse": {
            "type": "object",
            "required": ["error"],
            "properties": {"error": {"$ref": "#/components/schemas/Error"}},
            "description": "The single error envelope returned for every non-2xx response.",
        },
    }


def _error_response(description: str, *, with_challenge: bool = False) -> dict:
    body = {
        "description": description,
        "content": {
            "application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}
        },
    }
    if with_challenge:
        body["headers"] = {
            "WWW-Authenticate": {
                "description": "RFC 7235 auth challenge.",
                "schema": {"type": "string", "example": "Bearer"},
            }
        }
    return body


def _reusable_responses() -> dict[str, dict]:
    return {
        "Unauthorized": _error_response(
            "Missing or invalid bearer token (`unauthorized`).", with_challenge=True
        ),
        "RequestValidationError": _error_response("Request failed validation (`validation_error`)."),
        "InternalError": _error_response("Unhandled server error (`internal_error`)."),
        "BriefGenerationFailed": _error_response(
            "The brief workflow failed to produce a valid result (`brief_generation_failed`)."
        ),
        "UpstreamTimeout": _error_response("The brief model timed out (`upstream_timeout`)."),
    }


def enrich(spec: dict) -> dict:
    """Overlay servers, the real error contract, clean operationIds, and tags."""
    spec["info"]["description"] = INFO_DESCRIPTION
    spec["servers"] = [
        {"url": "http://localhost:8000", "description": "Local development"},
        {
            "url": "https://{host}",
            "description": "Deployment (set host to your server)",
            "variables": {"host": {"default": "coach.example.com"}},
        },
    ]
    spec["tags"] = TAGS

    components = spec.setdefault("components", {})
    components.setdefault("securitySchemes", {})["HTTPBearer"] = SECURITY_SCHEME

    schemas = components.setdefault("schemas", {})
    # The real 422 body is our envelope, not FastAPI's default {detail:[...]} —
    # drop the now-unreferenced default schemas so the spec is self-consistent.
    schemas.pop("HTTPValidationError", None)
    schemas.pop("ValidationError", None)
    schemas.update(_error_schemas())

    components["responses"] = _reusable_responses()

    for (method, path), cfg in ROUTES.items():
        op = spec["paths"][path][method]
        op["operationId"] = cfg["operationId"]
        op["tags"] = cfg["tags"]
        op["summary"] = cfg["summary"]
        for status in cfg["errors"]:
            op.setdefault("responses", {})[str(status)] = {
                "$ref": f"#/components/responses/{ERROR_RESPONSE_REF[status]}"
            }

    return spec


def main() -> None:
    spec = enrich(create_app().openapi())

    json_path = REPO_ROOT / "openapi.json"
    yaml_path = REPO_ROOT / "openapi.yaml"
    json_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    yaml_path.write_text(
        yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8"
    )

    paths = spec.get("paths", {})
    schemas = spec.get("components", {}).get("schemas", {})
    print(f"openapi {spec['openapi']} — {len(paths)} paths, {len(schemas)} schemas")
    print(f"wrote {json_path.relative_to(REPO_ROOT)} and {yaml_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
