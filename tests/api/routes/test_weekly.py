"""E10·P3 TASK-002: POST /brief/weekly endpoint tests (over a migrated temp app.db).

The route is the thin HTTP shell over the TASK-001 get-or-generate service. The
``WEEKLY_PLANNER`` workflow is **mocked**: ``get_weekly_generator`` is overridden with a
counting stub that mirrors ``PersistPlanNode`` (inserts one ``Plans`` row on the request
session, no commit) — so no LLM/network runs, but the realistic row-write + commit path
the service owns is exercised end-to-end. ``get_clock`` is pinned so the default-week
resolution is deterministic.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import insert

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.app import create_app
from app.api.routes.weekly import get_weekly_generator
from app.core.agent_node import BriefGenerationError
from app.core.settings import get_settings
from app.core.time import get_clock
from app.database.engine import get_engine, get_session
from app.database.models import Plans
from app.services.weekly_plan import GeneratedWeeklyPlan

VALID_TOKEN = "test-api-token-0123456789"
AUTH = {"Authorization": f"Bearer {VALID_TOKEN}"}

# A fixed clock instant → a deterministic "current" ISO week. 2026-06-04 (Thu) is
# Europe/Sofia ISO week 2026-W23.
FIXED_UTC = datetime(2026, 6, 4, 9, 0, 0, tzinfo=timezone.utc)
CURRENT_WEEK = "2026-W23"


def _migrate(db_path) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.attributes["test_db_url"] = f"sqlite:///{db_path}"
    command.upgrade(cfg, "head")


def _plan_data(iso_week: str, *, low: int = 40) -> dict:
    return {
        "isoWeek": iso_week,
        "weekStart": "1970-01-01",  # overwritten by the route from the resolved key
        "budgets": {
            "hard_days": 3,
            "strength_sessions": 2,
            "long_run_km": None,
            "deload": False,
        },
        "core": [
            {
                "card": "easy_run",
                "tier": "core",
                "intensity": "easy",
                "isHardDay": False,
                "suggestedDay": None,
                "zoneTarget": "z2",
                "durationMinLow": low,
                "durationMinHigh": 50,
                "flags": [],
            }
        ],
        "extras": [],
        "targets": {
            "totalRunKm": 30.0,
            "easyRunRatio": 0.8,
            "strengthSessions": 2,
            "hardDays": 3,
            "cadenceSpm": 180,
        },
        "nutrition": {
            "proteinG": 150,
            "fatGLow": 60,
            "fatGHigh": 80,
            "hydrationLLow": 2.5,
            "hydrationLHigh": 3.5,
            "avgCaloriesKcal": 2600,
            "dayTypePattern": [],
            "lastWeek": None,
        },
        "constantsRecomputed": False,
    }


def _narrative() -> list[dict]:
    return [{"type": "plan", "heading": "Week ahead", "body": "Build aerobic base."}]


class _StubGenerator:
    """Mirrors ``PersistPlanNode``: inserts one ``Plans`` row on the **request** session
    (no commit — the service commits), counts calls. Bound to the request session via
    ``get_session`` in the override (the real provider closes over the same session)."""

    def __init__(self, *, low: int = 40) -> None:
        self.calls = 0
        self.low = low

    def __call__(self, session: Session, iso_week: str) -> GeneratedWeeklyPlan:
        self.calls += 1
        data = _plan_data(iso_week, low=self.low)
        narrative = _narrative()
        session.execute(
            insert(Plans).values(
                iso_week=iso_week,
                payload=json.dumps(data),
                rationale=json.dumps(narrative),
                inputs_snapshot=json.dumps({"aggregates": {}, "constants": None}),
                model="claude-opus",
                constitution_version="2026.1",
                created_at="2026-06-04T12:00:00+03:00",
            )
        )
        return GeneratedWeeklyPlan(
            data=data,
            narrative=narrative,
            rationale=json.dumps(narrative),
            inputs_snapshot={"aggregates": {}, "constants": None},
            model="claude-opus",
            constitution_version="2026.1",
            generated_at="2026-06-04T12:00:00+03:00",
        )


class _RaisingGenerator:
    def __init__(self, code: str) -> None:
        self.code = code
        self.calls = 0

    def __call__(self, session: Session, iso_week: str) -> GeneratedWeeklyPlan:
        self.calls += 1
        raise BriefGenerationError(code=self.code)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    _migrate(db_path)
    monkeypatch.setenv("API_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("APP_DB_PATH", str(db_path))
    get_settings.cache_clear()
    get_engine.cache_clear()
    app = create_app()
    app.dependency_overrides[get_clock] = lambda: (lambda: FIXED_UTC)
    client = TestClient(app, raise_server_exceptions=False)
    yield client, app, db_path
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()


class _BoundGenerator:
    """A request-session-bound generator the route sees as ``(iso_week) -> plan``.

    Mirrors the real ``_WeeklyPlannerGenerator``: callable as ``(iso_week)`` and exposing
    ``pending_profile`` (the staged ``profile.yaml`` rewrite the route applies post-commit)
    — so ``getattr(generate, "pending_profile", None)`` in the route works for staging
    stubs too.
    """

    def __init__(self, stub, session) -> None:
        self._stub = stub
        self._session = session

    @property
    def pending_profile(self):
        return getattr(self._stub, "pending_profile", None)

    def __call__(self, iso_week: str) -> GeneratedWeeklyPlan:
        return self._stub(self._session, iso_week)


def _use_generator(app, stub) -> None:
    """Override the generator provider with one bound to the request session.

    FastAPI caches ``Depends(get_session)`` per request, so the session this provider
    receives is the **same** one the route hands the service — exactly as the real
    provider (which runs the workflow through ``ctx.metadata['session']``) behaves.
    """

    def _provider(session: Session = Depends(get_session)):
        return _BoundGenerator(stub, session)

    app.dependency_overrides[get_weekly_generator] = _provider


def _count(db_path) -> int:
    with sqlite3.connect(db_path) as raw:
        return raw.execute("SELECT COUNT(*) FROM plans").fetchone()[0]


# --------------------------------------------------------------------------- #
# Miss → 200, cached=false, one row, stub called once
# --------------------------------------------------------------------------- #
def test_miss_returns_cached_false_and_persists_one_row(ctx) -> None:
    client, app, db_path = ctx
    stub = _StubGenerator()
    _use_generator(app, stub)
    resp = client.post("/brief/weekly", json={}, headers=AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["cached"] is False
    assert body["data"]["isoWeek"] == CURRENT_WEEK
    assert stub.calls == 1
    assert _count(db_path) == 1


# --------------------------------------------------------------------------- #
# Hit → cached=true, stub not re-invoked, body equals first except cached
# --------------------------------------------------------------------------- #
def test_hit_returns_cached_true_without_regenerate(ctx) -> None:
    client, app, db_path = ctx
    stub = _StubGenerator()
    _use_generator(app, stub)
    first = client.post("/brief/weekly", json={}, headers=AUTH).json()
    second = client.post("/brief/weekly", json={}, headers=AUTH)
    assert second.status_code == 200
    body = second.json()
    assert body["data"]["cached"] is True
    assert stub.calls == 1  # not re-invoked
    assert _count(db_path) == 1
    # Round-trip: the hit body equals the miss body except data.cached.
    first["data"]["cached"] = True
    assert body == first


# --------------------------------------------------------------------------- #
# ?refresh=true → regenerate, cached=false, one row (new values)
# --------------------------------------------------------------------------- #
def test_refresh_regenerates_one_row(ctx) -> None:
    client, app, db_path = ctx
    first = _StubGenerator(low=40)
    _use_generator(app, first)
    client.post("/brief/weekly", json={}, headers=AUTH)
    second = _StubGenerator(low=55)
    _use_generator(app, second)
    resp = client.post("/brief/weekly?refresh=true", json={}, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["cached"] is False
    assert second.calls == 1
    assert _count(db_path) == 1
    assert body["data"]["core"][0]["durationMinLow"] == 55


# --------------------------------------------------------------------------- #
# Explicit isoWeek honored (year-boundary)
# --------------------------------------------------------------------------- #
def test_explicit_iso_week_honored(ctx) -> None:
    client, app, _db = ctx
    stub = _StubGenerator()
    _use_generator(app, stub)
    resp = client.post("/brief/weekly", json={"isoWeek": "2025-W01"}, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["isoWeek"] == "2025-W01"
    # weekStart is the Monday of 2025-W01 (year-boundary): 2024-12-30.
    assert body["data"]["weekStart"] == "2024-12-30"


# --------------------------------------------------------------------------- #
# Out-of-range / malformed isoWeek → 422 validation_error (never a 500)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", ["garbage", "2026-W00", "2026-W54", "2025-W53"])
def test_invalid_iso_week_returns_422(ctx, bad) -> None:
    client, app, _db = ctx
    _use_generator(app, _StubGenerator())
    resp = client.post("/brief/weekly", json={"isoWeek": bad}, headers=AUTH)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "validation_error"


# --------------------------------------------------------------------------- #
# Default period = current Europe/Sofia ISO week (pinned clock)
# --------------------------------------------------------------------------- #
def test_default_week_resolves_to_current_sofia_week(ctx) -> None:
    client, app, _db = ctx
    _use_generator(app, _StubGenerator())
    resp = client.post("/brief/weekly", json={}, headers=AUTH)
    assert resp.json()["data"]["isoWeek"] == CURRENT_WEEK


# --------------------------------------------------------------------------- #
# weekStart = Monday of the ISO week (Europe/Sofia)
# --------------------------------------------------------------------------- #
def test_week_start_is_monday(ctx) -> None:
    client, app, _db = ctx
    _use_generator(app, _StubGenerator())
    body = client.post("/brief/weekly", json={}, headers=AUTH).json()
    assert body["data"]["weekStart"] == "2026-06-01"  # Monday of 2026-W23


# --------------------------------------------------------------------------- #
# Auth-gated
# --------------------------------------------------------------------------- #
def test_requires_auth(ctx) -> None:
    client, app, _db = ctx
    _use_generator(app, _StubGenerator())
    no_token = client.post("/brief/weekly", json={})
    assert no_token.status_code == 401
    assert no_token.json()["error"]["code"] == "unauthorized"
    assert no_token.headers.get("WWW-Authenticate") == "Bearer"
    wrong = client.post("/brief/weekly", json={}, headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"
    ok = client.post("/brief/weekly", json={}, headers=AUTH)
    assert ok.status_code == 200


# --------------------------------------------------------------------------- #
# Workflow failure → correct envelope (not internal_error), nothing cached
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code", ["brief_generation_failed", "upstream_timeout"])
def test_workflow_failure_maps_to_envelope_and_caches_nothing(ctx, code) -> None:
    client, app, db_path = ctx
    gen = _RaisingGenerator(code)
    _use_generator(app, gen)
    resp = client.post("/brief/weekly", json={}, headers=AUTH)
    assert gen.calls == 1
    assert resp.json()["error"]["code"] == code
    assert resp.status_code >= 500
    assert _count(db_path) == 0  # nothing cached on failure


# --------------------------------------------------------------------------- #
# Router mounted on create_app()'s app
# --------------------------------------------------------------------------- #
def test_route_is_mounted(ctx) -> None:
    _client, app, _db = ctx
    paths = {route.path for route in app.routes}
    assert "/brief/weekly" in paths


# --------------------------------------------------------------------------- #
# Staged profile.yaml write: applied AFTER commit on a due-recompute miss.
# --------------------------------------------------------------------------- #
class _StagingGenerator(_StubGenerator):
    """A stub whose run also parks a proposed Profile on ``pending_profile`` (mirroring
    the workflow's ``PersistPlanNode`` staging under ``PENDING_PROFILE_WRITE_KEY``)."""

    def __init__(self, pending_profile, **kw) -> None:
        super().__init__(**kw)
        self.pending_profile = pending_profile


def test_due_recompute_miss_advances_profile_after_commit(ctx, tmp_path, monkeypatch) -> None:
    client, app, db_path = ctx
    from app.core.profile import load_profile, write_profile

    # Seed a temp profile.yaml from the repo profile, THEN point PROFILE_PATH at it so the
    # route's write_profile/load_profile target the temp file (not the repo one).
    base = load_profile()  # repo profile (default path, before the env override)
    target = tmp_path / "profile.yaml"
    write_profile(base, path=target)
    monkeypatch.setenv("PROFILE_PATH", str(target))

    proposed = base.model_copy(deep=True)
    object.__setattr__(proposed.meta, "constants_recomputed_week", "2026-W23")

    gen = _StagingGenerator(proposed)
    _use_generator(app, gen)
    resp = client.post("/brief/weekly", json={}, headers=AUTH)
    assert resp.status_code == 200
    assert _count(db_path) == 1  # the plan row committed
    # The staged profile write was applied AFTER the commit: the file now carries the
    # proposed recompute week.
    written = load_profile(path=target)
    assert written.meta.constants_recomputed_week == "2026-W23"


def test_commit_failure_leaves_profile_untouched_and_no_row(ctx, tmp_path, monkeypatch) -> None:
    client, app, db_path = ctx
    from app.core.profile import load_profile, write_profile

    base = load_profile()  # repo profile (default path, before the env override)
    target = tmp_path / "profile.yaml"
    write_profile(base, path=target)
    monkeypatch.setenv("PROFILE_PATH", str(target))
    before = target.read_bytes()

    proposed = base.model_copy(deep=True)
    object.__setattr__(proposed.meta, "constants_recomputed_week", "2026-W23")

    # A session whose commit() raises: the service must propagate BEFORE the route applies
    # the staged write, so profile.yaml stays byte-identical and no plan row persists.
    def failing_session():
        sess = next(get_session())
        original_commit = sess.commit

        def boom():
            original_commit  # noqa: B018 — keep a handle; we never call it
            raise RuntimeError("commit failed")

        sess.commit = boom  # type: ignore[method-assign]
        try:
            yield sess
        finally:
            sess.rollback()
            sess.close()

    app.dependency_overrides[get_session] = failing_session
    gen = _StagingGenerator(proposed)
    _use_generator(app, gen)
    resp = client.post("/brief/weekly", json={}, headers=AUTH)
    assert resp.status_code >= 500  # the commit failure surfaces (catch-all internal_error)
    # profile.yaml never advanced (staged write not applied) ...
    assert target.read_bytes() == before
    assert load_profile(path=target).meta.constants_recomputed_week == base.meta.constants_recomputed_week
    # ... and no plan row persisted (the commit failed / rolled back).
    assert _count(db_path) == 0


def test_real_generator_bridges_staged_profile_write(monkeypatch) -> None:
    """The REAL _WeeklyPlannerGenerator captures the E10·P2 staged profile write —
    out_ctx.metadata[PENDING_PROFILE_WRITE_KEY] -> self.pending_profile — so the route
    applies it post-commit. The other route tests mock the generator seam, so this is the
    only regression coverage of the load-bearing bridge (review). WeeklyPlanner.run is
    stubbed to return a controlled context (no DB/LLM)."""
    from datetime import date
    from types import SimpleNamespace

    from app.api.routes.weekly import _WeeklyPlannerGenerator
    from app.core.profile import load_profile
    from app.core.task_context import TaskContext
    from app.core.weekly_planner import (
        PENDING_PROFILE_WRITE_KEY,
        WeeklyPlanner,
        WeeklyPlannerEvent,
    )

    sentinel = load_profile()  # any valid Profile stands in for the staged rewrite
    out = TaskContext(
        event=WeeklyPlannerEvent(anchor=date(2026, 6, 1), iso_week="2026-W23", week_start=date(2026, 6, 1)),
        metadata={PENDING_PROFILE_WRITE_KEY: sentinel},
    )
    out.nodes["PersistPlanNode"] = SimpleNamespace(data={"isoWeek": "2026-W23"})
    monkeypatch.setattr(WeeklyPlanner, "run", lambda self, context: out)

    gen = _WeeklyPlannerGenerator(session=None)
    result = gen("2026-W23")

    # The bridge: the staged Profile from metadata is surfaced on pending_profile.
    assert gen.pending_profile is sentinel
    assert result.data["isoWeek"] == "2026-W23"


def test_real_generator_no_staged_write_when_metadata_absent(monkeypatch) -> None:
    """When the workflow stages nothing (not-due week), pending_profile stays None so the
    route writes no file (review)."""
    from datetime import date
    from types import SimpleNamespace

    from app.api.routes.weekly import _WeeklyPlannerGenerator
    from app.core.task_context import TaskContext
    from app.core.weekly_planner import WeeklyPlanner, WeeklyPlannerEvent

    out = TaskContext(
        event=WeeklyPlannerEvent(anchor=date(2026, 6, 1), iso_week="2026-W23", week_start=date(2026, 6, 1)),
        metadata={},  # nothing staged
    )
    out.nodes["PersistPlanNode"] = SimpleNamespace(data={"isoWeek": "2026-W23"})
    monkeypatch.setattr(WeeklyPlanner, "run", lambda self, context: out)

    gen = _WeeklyPlannerGenerator(session=None)
    gen("2026-W23")
    assert gen.pending_profile is None


# --------------------------------------------------------------------------- #
# E13·P1 regression: a legacy `plans.payload` (snake_case asdict `lastWeek` with a
# FRACTIONAL `avg_protein_g`) survives the cache-hit re-validation path without a 500.
# --------------------------------------------------------------------------- #
def test_cache_hit_legacy_last_week_payload_does_not_500(ctx) -> None:
    """A stored `nutrition.lastWeek` that is a faithful `dataclasses.asdict(NutritionAdherence)`
    dump — including a fractional `avg_protein_g` (the exact Pydantic v2 float→int rejection,
    round-2 #1) — is served on cache hit with HTTP 200, not 500. The TASK-002 `mode="before"`
    validator rounds it (138.5 → 139); the unmatched legacy keys (`avg_kcal`/`kcal_pct`/
    `consumed`/`target`) are ignored by CamelModel."""
    client, app, db_path = ctx
    gen = _RaisingGenerator("E_MUST_NOT_REGENERATE")
    _use_generator(app, gen)  # a cache hit must never invoke it

    legacy_last_week = {
        "consumed": {
            "days": 7, "kcal_in": 18270.0, "protein_in_g": 969.5, "carbs_in_g": 0.0,
            "fat_in_g": 0.0, "fiber_in_g": 0.0, "sodium_in_mg": 0.0, "water_in_l": 0.0,
            "n_days": 7, "kcal_in_n": 7, "protein_in_g_n": 7, "carbs_in_g_n": 0,
            "fat_in_g_n": 0, "fiber_in_g_n": 0, "sodium_in_mg_n": 0, "water_in_l_n": 0,
        },
        "target": None,
        "avg_kcal": 2610.0,
        "avg_protein_g": 138.5,  # fractional → would 500 a bare `int` field without the validator
        "kcal_pct": None,
        "protein_hit_days": 4,
        "days_over_target": 3,
        "days_under_target": 1,
    }
    data = _plan_data(CURRENT_WEEK)
    data["nutrition"]["lastWeek"] = legacy_last_week
    with sqlite3.connect(db_path) as raw:
        raw.execute(
            "INSERT INTO plans (iso_week, payload, rationale, inputs_snapshot, model, "
            "constitution_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                CURRENT_WEEK,
                json.dumps(data),
                json.dumps(_narrative()),
                json.dumps({"aggregates": {}, "constants": None}),
                "claude-opus",
                "2026.1",
                "2026-06-04T12:00:00+03:00",
            ),
        )
        raw.commit()

    resp = client.post("/brief/weekly", json={}, headers=AUTH)  # cache hit on CURRENT_WEEK
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["cached"] is True
    assert gen.calls == 0  # served from cache, never regenerated
    last_week = body["data"]["nutrition"]["lastWeek"]
    assert last_week["avgProteinG"] == 139  # 138.5 rounded half-up by the TASK-002 validator
    assert last_week["avgCaloriesKcal"] is None  # legacy `avg_kcal` key unmatched → ignored
    assert last_week["proteinHitDays"] == 4  # matched snake key passes through (populate_by_name)
