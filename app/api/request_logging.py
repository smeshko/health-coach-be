"""Full request/response debug logging (default-off; armed by REQUEST_LOG_PATH).

When `Settings.request_log_path` is set, every HTTP request/response pair is
appended as ONE JSON line to a rotating file so wire-level issues (what did the
client actually send, what did we actually answer) are debuggable after the fact
— the uvicorn access log only records `method path → status`.

Captured per line: timestamp, method/path/query, client addr, status, duration,
request headers, and both bodies (parsed as JSON when they are JSON). Guardrails:

- bodies are captured up to `request_log_max_body` bytes each; longer bodies are
  truncated and the line records the true byte size,
- `Authorization` / `Cookie` header values are redacted, so the bearer secret
  never lands on disk,
- paths in `request_log_exclude` (default `/health`, polled by the uptime
  monitor) are skipped entirely,
- the file rotates (~10 MB × 5) so full-body logging can't grow unbounded.

The request body is observed by wrapping `receive`, so a request whose body the
app never reads (e.g. a 404 on an unknown path) logs without one — we never
drain the stream ourselves. This is a single-user health API: the log holds
personal data in plaintext, so it must stay on this machine and out of any
off-site backup.
"""

import json
import logging
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.core.settings import Settings

# Parent of the per-file loggers (child name = destination path, so two apps
# configured with different files — the test suite does this — never cross-write).
REQUEST_LOGGER_NAME = "coach.requests"

_REDACTED_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization", "cf-access-jwt-assertion"}
)
_ROTATE_MAX_BYTES = 10 * 1024 * 1024
_ROTATE_BACKUPS = 5


def _decode_body(raw: bytes) -> Any:
    """Render a captured body: parsed JSON when it is JSON, else lossy UTF-8 text."""
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return text


def _redacted_headers(scope: dict) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in scope.get("headers", []):
        key = name.decode("latin-1").lower()
        headers[key] = "<redacted>" if key in _REDACTED_HEADERS else value.decode("latin-1")
    return headers


class RequestResponseLogMiddleware:
    """Pure-ASGI middleware: one JSON line per request/response pair.

    Pure ASGI (not `BaseHTTPMiddleware`) so bodies are observed as they stream
    through `receive`/`send` without buffering the response or double-reading
    the request.
    """

    def __init__(self, app, *, logger: logging.Logger, max_body: int, exclude: frozenset[str]):
        self.app = app
        self.logger = logger
        self.max_body = max_body
        self.exclude = exclude

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in self.exclude:
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        req_body = bytearray()
        resp_body = bytearray()
        totals = {"req": 0, "resp": 0}
        status: int | None = None

        def _capture(buffer: bytearray, chunk: bytes, key: str) -> None:
            totals[key] += len(chunk)
            room = self.max_body - len(buffer)
            if room > 0:
                buffer.extend(chunk[:room])

        async def logging_receive():
            message = await receive()
            if message["type"] == "http.request":
                _capture(req_body, message.get("body", b""), "req")
            return message

        async def logging_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                _capture(resp_body, message.get("body", b""), "resp")
            await send(message)

        try:
            await self.app(scope, logging_receive, logging_send)
        except Exception:
            # An exception past the app's handlers is rendered as a 500 by
            # ServerErrorMiddleware *outside* this wrapper — log the pair here
            # (response body unseen), then let the exception continue outward.
            self._log(scope, 500, start, req_body, resp_body, totals, crashed=True)
            raise
        self._log(scope, status, start, req_body, resp_body, totals, crashed=False)

    def _log(
        self,
        scope: dict,
        status: int | None,
        start: float,
        req_body: bytearray,
        resp_body: bytearray,
        totals: dict[str, int],
        *,
        crashed: bool,
    ) -> None:
        client = scope.get("client")
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "method": scope["method"],
            "path": scope["path"],
            "query": scope.get("query_string", b"").decode("latin-1") or None,
            "client": client[0] if client else None,
            "status": status,
            "durationMs": round((time.monotonic() - start) * 1000, 1),
            "requestHeaders": _redacted_headers(scope),
            "requestBody": _decode_body(bytes(req_body)),
            "responseBody": _decode_body(bytes(resp_body)),
        }
        if totals["req"] > self.max_body:
            record["requestBodyBytesTotal"] = totals["req"]  # captured body is truncated
        if totals["resp"] > self.max_body:
            record["responseBodyBytesTotal"] = totals["resp"]
        if crashed:
            record["unhandledException"] = True
        # One self-contained JSON document per line (`default=str` so a stray
        # non-JSON value can never make the log line itself unwritable).
        self.logger.info(json.dumps(record, ensure_ascii=False, default=str))


def install_request_logging(app: FastAPI, settings: Settings) -> None:
    """Attach the rotating JSONL handler + middleware for `settings.request_log_path`."""
    path = Path(settings.request_log_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    # One logger per destination file, handler attached once (create_app() may
    # run many times per process — tests — while logging state is process-global).
    logger = logging.getLogger(f"{REQUEST_LOGGER_NAME}.{path}")
    logger.setLevel(logging.INFO)
    logger.propagate = False  # JSON lines belong in the file only, not the console log
    if not any(
        isinstance(h, RotatingFileHandler) and h.baseFilename == str(path) for h in logger.handlers
    ):
        handler = RotatingFileHandler(
            path, maxBytes=_ROTATE_MAX_BYTES, backupCount=_ROTATE_BACKUPS, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    exclude = frozenset(p.strip() for p in settings.request_log_exclude.split(",") if p.strip())
    app.add_middleware(
        RequestResponseLogMiddleware,
        logger=logger,
        max_body=settings.request_log_max_body,
        exclude=exclude,
    )
