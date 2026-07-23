"""Uvicorn entrypoint.

`app = create_app()` is built at import time so `uvicorn app.main:app` boots the
factory-configured application (and fails fast if required env is missing).

Before building the app, the configured `anthropic_api_key` is bridged into
`os.environ` for the running server: pydantic-settings loads it (from `.env` or a
real env var) into `Settings`, but pydantic-ai's `AnthropicProvider` reads
`ANTHROPIC_API_KEY` off the process environment — which pydantic-settings never
populates. `setdefault` so a real env var already set in deployment wins untouched.
This lives here (the composition root), not in `create_app()`, which stays free of
side effects beyond config validation.
"""

import logging
import os

from app.api.app import create_app
from app.core.settings import get_settings

# Timestamp every server log line. Uvicorn configures its handlers (default
# format: no timestamp) before importing this module, so restyle them here at the
# composition root; basicConfig gives app-level loggers (errors.py etc.) a
# matching root handler and is a no-op if logging was already configured.
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    for _handler in logging.getLogger(_name).handlers:
        _handler.setFormatter(logging.Formatter(_LOG_FORMAT))

_settings = get_settings()
if _settings.anthropic_api_key:
    os.environ.setdefault("ANTHROPIC_API_KEY", _settings.anthropic_api_key)

app = create_app()
