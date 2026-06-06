"""Offline brief fixtures — serve canned briefs instead of calling the LLM.

When ``BRIEF_FIXTURES=1`` (Settings.brief_fixtures), ``create_app()`` calls
``install_brief_fixtures(app, settings)``, which overrides the two generator
provider dependencies (``get_weekly_generator`` / ``get_daily_generator``) with
ones that return a static ``GeneratedWeeklyPlan`` / ``GeneratedDailyBrief`` loaded
from ``fixtures/briefs/{weekly,daily}.json`` — **no workflow run, no Anthropic
call**. This is the same `dependency_overrides` seam the pytest suite uses, exposed
to a running server so the iOS app / curl / Postman can exercise ``POST
/brief/weekly`` and ``POST /brief/daily`` for any period at zero LLM cost.

The fixture is period-agnostic: the route stamps the requested ``isoWeek``/``date``
plus ``weekStart``/``generatedAt``/``cached`` onto the response, so one canned brief
serves every key. Because the fixture generator writes **no** ``plans``/
``suggestions`` row, ``data.cached`` is always ``false`` (every call re-serves the
fixture). A period that already has a real cached row still serves that row as a
hit — fixtures only fill the miss path.

Edit the JSON files to change what the briefs say; the shapes are validated against
the wire models at startup, so a malformed fixture fails the boot loudly rather than
500-ing at request time. This mode is **default-off** and must never be enabled in a
real deployment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from fastapi import FastAPI
from pydantic import BaseModel, ValidationError

from app.api.routes.daily import get_daily_generator
from app.api.routes.weekly import get_weekly_generator
from app.core.settings import Settings
from app.services.daily_brief import GeneratedDailyBrief
from app.services.weekly_plan import GeneratedWeeklyPlan

# Repo-root-relative default location of the editable fixture files (overridable via
# Settings.brief_fixtures_dir / env BRIEF_FIXTURES_DIR for a deployed container).
_DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "briefs"

_M = TypeVar("_M", bound=BaseModel)


def _load(path: Path, model: type[_M]) -> _M:
    """Read + validate one fixture file into its bundle model, failing loudly on error."""
    if not path.exists():
        raise FileNotFoundError(
            f"BRIEF_FIXTURES is on but the fixture file is missing: {path}. "
            "Create it or set BRIEF_FIXTURES_DIR to the directory that holds "
            "weekly.json / daily.json."
        )
    try:
        return model.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValidationError) as exc:  # pragma: no cover - message only
        raise ValueError(f"Invalid brief fixture {path}: {exc}") from exc


class _FixtureWeeklyGenerator:
    """A ``WeeklyPlanGenerator`` that returns the canned plan for any ISO week.

    Mirrors the real ``_WeeklyPlannerGenerator`` contract the route relies on: callable
    as ``(iso_week) -> GeneratedWeeklyPlan`` and exposing ``pending_profile`` (always
    ``None`` here — fixtures never stage a ``profile.yaml`` rewrite). Returns a deep copy
    so a handler can never mutate the shared fixture.
    """

    pending_profile = None

    def __init__(self, plan: GeneratedWeeklyPlan) -> None:
        self._plan = plan

    def __call__(self, iso_week: str) -> GeneratedWeeklyPlan:
        return self._plan.model_copy(deep=True)


class _FixtureDailyGenerator:
    """A ``DailyBriefGenerator`` that returns the canned brief for any date."""

    def __init__(self, brief: GeneratedDailyBrief) -> None:
        self._brief = brief

    def __call__(self, date: str) -> GeneratedDailyBrief:
        return self._brief.model_copy(deep=True)


def install_brief_fixtures(app: FastAPI, settings: Settings) -> None:
    """Override the LLM-backed brief generators with static-fixture ones (no LLM)."""
    fixtures_dir = (
        Path(settings.brief_fixtures_dir) if settings.brief_fixtures_dir else _DEFAULT_FIXTURES_DIR
    )
    weekly = _load(fixtures_dir / "weekly.json", GeneratedWeeklyPlan)
    daily = _load(fixtures_dir / "daily.json", GeneratedDailyBrief)

    app.dependency_overrides[get_weekly_generator] = lambda: _FixtureWeeklyGenerator(weekly)
    app.dependency_overrides[get_daily_generator] = lambda: _FixtureDailyGenerator(daily)
