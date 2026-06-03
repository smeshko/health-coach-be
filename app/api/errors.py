"""Error envelope + exception handlers (E1·P2 TASK-001).

Every non-2xx response is the single wrapper `{ "error": { code, message, detail } }`
(MODELS "Errors"). `code` is a **closed** enum — the five MODELS codes plus one named
`internal_error` fallback for unmapped statuses / unhandled exceptions — so a handler
can never emit a code outside the contract, and `message` is always a non-empty public
string (never raw exception text), keeping internals off the wire.
"""

import logging
from enum import Enum

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.api.schemas.base import CamelModel

logger = logging.getLogger(__name__)


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
    code: ErrorCode,
    message: str,
    status_code: int,
    detail: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Render the `{ "error": { … } }` envelope as a JSON response at `status_code`."""
    payload = ErrorResponse(error=Error(code=code, message=message, detail=detail))
    return JSONResponse(
        status_code=status_code, content=payload.model_dump(mode="json"), headers=headers
    )


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
        # Safe by default: never echo a route's HTTPException detail onto the wire —
        # the public message comes from the status table, and detail stays null so no
        # caller text (auto status phrase or sensitive string) can leak. The only
        # handler that sets a detail is the validation one, which builds it itself.
        # Preserve HTTP recovery headers (405 Allow, 401 WWW-Authenticate, Retry-After, …)
        # that Starlette attached to the exception; the fresh JSONResponse would drop them.
        return error_response(
            code, message, status_code=exc.status_code, detail=None, headers=exc.headers
        )

    @app.exception_handler(Exception)
    async def _on_unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Record the full stack + request context server-side so a sanitized 500 still
        # leaves a root-cause trail. Stdlib logging only — Langfuse tracing is E12.
        logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
        code, message = _DEFAULT_CODE_MESSAGE
        return error_response(code, message, status_code=500, detail=None)
