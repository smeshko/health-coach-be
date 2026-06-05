"""``GET /profile`` (E14·P1) — the authed, read-only profile-constants endpoint.

A pure ``load_profile()`` read: it surfaces the ``profile.yaml`` constants (athlete, HR-zone
``{low, high}`` ranges, thresholds, meta) as camelCase JSON for the iOS Settings screen
(PRD §7.7) and zone-chip rendering (PRD §4.2). It takes **no** database dependency, runs **no**
LLM, and triggers **no** derived-metric rebuild — a fully side-effect-free read. Auth is via
``dependencies=[Depends(require_auth)]`` (the token isn't read in the body — the pure-read style
of ``health.py``'s ``/probe``; DECISIONS Decision 5); a missing/invalid token yields the standard
401 ``unauthorized`` envelope automatically.
"""

from fastapi import APIRouter, Depends

from app.api.auth import require_auth
from app.api.schemas.profile import (
    AthleteOut,
    MetaOut,
    ProfileResponse,
    ThresholdsOut,
    ZoneRange,
    ZonesOut,
)
from app.core.profile import load_profile

router = APIRouter()


@router.get("/profile", response_model=ProfileResponse, dependencies=[Depends(require_auth)])
def get_profile() -> ProfileResponse:
    profile = load_profile()
    zones = ZonesOut(
        **{z: ZoneRange(low=lo, high=hi) for z, (lo, hi) in profile.zone_bounds().items()}
    )
    return ProfileResponse(
        athlete=AthleteOut.model_validate(profile.athlete),
        zones=zones,
        thresholds=ThresholdsOut.model_validate(profile.thresholds),
        meta=MetaOut.model_validate(profile.meta),
    )
