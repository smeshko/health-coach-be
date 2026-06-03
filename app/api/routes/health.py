"""Health + auth-probe routes (E1·P2 TASK-003).

`GET /health` is an **unauthenticated** liveness ping (so the E12 Docker
HEALTHCHECK / litestream / uptime monitors can probe it without the API token).
`serverTime` is an instant-preserving conversion of the current UTC instant to
Europe/Sofia — the offset always comes from the tz database (DST-aware: +02:00
winter / +03:00 summer), never a hard-coded fixed offset and never a tzinfo
relabel (MODELS "Conventions → Timestamps").

`GET /probe` is a throwaway route guarded by `require_auth` that demonstrates the
401-vs-200 gate; the real endpoints arrive in E5/E10/E11.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from app.api.auth import require_auth
from app.api.schemas.base import CamelModel


def utc_now() -> datetime:
    """Default clock: the current aware UTC instant (the seam tests override)."""
    return datetime.now(timezone.utc)


def now_sofia(clock: Callable[[], datetime] = utc_now) -> datetime:
    """Convert the injected aware-UTC instant to Europe/Sofia, preserving the instant."""
    # ZoneInfo is internally cached by key, so constructing it here is free and keeps
    # the tz-database (DST-aware) conversion explicit at the call site.
    return clock().astimezone(ZoneInfo("Europe/Sofia"))


def get_clock() -> Callable[[], datetime]:
    """FastAPI seam for the UTC clock source (overridden in tests via dependency_overrides)."""
    return utc_now


class HealthResponse(CamelModel):
    status: str
    server_time: datetime


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(clock: Callable[[], datetime] = Depends(get_clock)) -> HealthResponse:
    return HealthResponse(status="ok", server_time=now_sofia(clock))


@router.get("/probe", dependencies=[Depends(require_auth)])
def probe() -> dict[str, bool]:
    # Temporary: demonstrates the auth gate (401 without / 200 with the token).
    # Superseded by the real endpoints in E5/E10/E11.
    return {"ok": True}
