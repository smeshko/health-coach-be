"""Uvicorn entrypoint.

`app = create_app()` is built at import time so `uvicorn app.main:app` boots the
factory-configured application (and fails fast if required env is missing).
"""

from app.api.app import create_app

app = create_app()
