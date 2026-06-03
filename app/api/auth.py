"""Bearer-token auth dependency (E1·P2 TASK-002).

A reusable FastAPI dependency authenticating the single long-lived bearer token
(MODELS "Conventions → Auth": one token, single user, no tenancy). It only ever
raises `HTTPException(401)` with no detail — TASK-001's handler maps `401 → the
"unauthorized" envelope` and supplies the public message; this module builds no
JSON of its own.
"""

import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.settings import Settings, get_settings

# auto_error=False so a missing/non-Bearer header yields None (→ our 401), rather
# than FastAPI's own 401/403 that would bypass the envelope handler.
_bearer = HTTPBearer(auto_error=False)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    """Gate a route via `Depends(require_auth)`; returns the token on success, 401 otherwise."""
    if credentials is None:
        # Missing Authorization header or a non-Bearer scheme.
        raise HTTPException(status_code=401)
    if not secrets.compare_digest(credentials.credentials, settings.api_token):
        raise HTTPException(status_code=401)
    return credentials.credentials
