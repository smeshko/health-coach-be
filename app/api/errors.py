"""Error envelope + exception handlers (E1·P2 TASK-001).

Every non-2xx response is the single wrapper `{ "error": { code, message, detail } }`
(MODELS "Errors"). `code` is a **closed** enum — the five MODELS codes plus one named
`internal_error` fallback for unmapped statuses / unhandled exceptions — so a handler
can never emit a code outside the contract, and `message` is always a non-empty public
string (never raw exception text), keeping internals off the wire.
"""

import http
from enum import Enum

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.api.schemas.base import CamelModel


class ErrorCode(str, Enum):
    """Closed set of stable machine codes (MODELS "Errors" + the internal_error fallback)."""

    validation_error = "validation_error"
    unauthorized = "unauthorized"
    not_found = "not_found"
    brief_generation_failed = "brief_generation_failed"
    upstream_timeout = "upstream_timeout"
    internal_error = "internal_error"


class Error(CamelModel):
    code: ErrorCode
    message: str
    detail: str | None = None


class ErrorResponse(CamelModel):
    """The wire wrapper: `{ "error": { … } }`."""

    error: Error


# status -> (code, default public message). Any status not listed falls back to
# internal_error, so an unmapped HTTPException can never produce an out-of-set code.
STATUS_TO_CODE: dict[int, tuple[ErrorCode, str]] = {
    401: (ErrorCode.unauthorized, "Authentication required."),
    404: (ErrorCode.not_found, "Resource not found."),
}
_DEFAULT_CODE_MESSAGE: tuple[ErrorCode, str] = (
    ErrorCode.internal_error,
    "An internal error occurred.",
)
_VALIDATION_MESSAGE = "Request validation failed."


def error_response(
    code: ErrorCode, message: str, status_code: int, detail: str | None = None
) -> JSONResponse:
    """Render the `{ "error": { … } }` envelope as a JSON response at `status_code`."""
    payload = ErrorResponse(error=Error(code=code, message=message, detail=detail))
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def _status_phrase(status_code: int) -> str | None:
    try:
        return http.HTTPStatus(status_code).phrase
    except ValueError:
        return None


def _http_detail(exc: StarletteHTTPException) -> str | None:
    # Starlette auto-fills `detail` with the status phrase ("Not Found", …) when the
    # caller passes none. Treat that auto-fill (and blanks) as "no detail" so a bare
    # HTTPException — like auth's 401 — renders `detail: null`, never a status phrase.
    detail = exc.detail
    if not isinstance(detail, str) or not detail.strip():
        return None
    if detail == _status_phrase(exc.status_code):
        return None
    return detail


def _summarize_validation(exc: RequestValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = err.get("msg", "")
        parts.append(f"{loc}: {msg}".strip(": ") if loc else msg)
    return "; ".join(p for p in parts if p) or "Invalid request."


def register_exception_handlers(app: FastAPI) -> None:
    """Register the validation / HTTP / catch-all handlers so every non-2xx uses the envelope."""

    @app.exception_handler(RequestValidationError)
    async def _on_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            ErrorCode.validation_error,
            _VALIDATION_MESSAGE,
            status_code=422,
            detail=_summarize_validation(exc),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _on_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = STATUS_TO_CODE.get(exc.status_code, _DEFAULT_CODE_MESSAGE)
        # Never echo caller-supplied detail on the internal_error fallback (unmapped
        # statuses) — that path must leak nothing, even if a route passed a detail.
        detail = None if code is ErrorCode.internal_error else _http_detail(exc)
        return error_response(code, message, status_code=exc.status_code, detail=detail)

    @app.exception_handler(Exception)
    async def _on_unhandled(request: Request, exc: Exception) -> JSONResponse:
        code, message = _DEFAULT_CODE_MESSAGE
        return error_response(code, message, status_code=500, detail=None)
