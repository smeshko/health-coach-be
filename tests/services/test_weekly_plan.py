"""E10·P3 TASK-001: the get-or-generate service keyed by ``iso_week`` (over a temp app.db).

The service owns lookup / refresh-delete / commit; the **workflow** (E10·P2's
``PersistPlanNode``) owns the single ``Plans`` row write. So the stub generator here
**mirrors** ``PersistPlanNode``: it counts its calls, ``session.execute(insert(Plans))``s
one row for the week (no commit), and returns a fixed ``GeneratedWeeklyPlan`` — no LLM, no
workflow, but the realistic row-write path the service commits.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.database.models import Plans
from app.services.weekly_plan import (
    GeneratedWeeklyPlan,
    delete_plan,
    get_or_generate_weekly,
    lookup_plan,
)

ISO_WEEK = "2026-W23"


def _data(iso_week: str = ISO_WEEK, *, marker: str = "v1") -> dict:
    """The structured ``data`` payload ``PersistPlanNode`` serialises into ``payload``."""
    return {
        "isoWeek": iso_week,
        "weekStart": "2026-06-01",
        "budgets": {"hardDays": 3, "strengthSessions": 2, "longRunKm": None, "deload": False},
        "core": [{"card": "easy_run", "marker": marker}],
        "extras": [{"card": "mobility"}],
        "targets": {"totalRunKm": 30.0, "easyRunRatio": 0.8},
        "nutrition": {"proteinG": 150},
        "constantsRecomputed": False,
    }


def _narrative() -> list[dict]:
    return [{"type": "plan", "heading": "Week ahead", "body": "Build aerobic base."}]


def _generated(iso_week: str = ISO_WEEK, *, marker: str = "v1") -> GeneratedWeeklyPlan:
    return GeneratedWeeklyPlan(
        data=_data(iso_week, marker=marker),
        narrative=_narrative(),
        rationale=json.dumps(_narrative()),
        inputs_snapshot={"aggregates": {}, "constants": None},
        model="claude-opus",
        constitution_version="2026.1",
        generated_at="2026-06-01T08:00:00+03:00",
    )


class _StubGenerator:
    """Mirrors ``PersistPlanNode``: inserts one ``Plans`` row (no commit), counts calls."""

    def __init__(self, *, marker: str = "v1") -> None:
        self.calls = 0
        self.marker = marker

    def __call__(self, session, iso_week: str) -> GeneratedWeeklyPlan:
        self.calls += 1
        gen = _generated(iso_week, marker=self.marker)
        session.execute(
            insert(Plans).values(
                iso_week=iso_week,
                payload=json.dumps(gen.data),
                rationale=gen.rationale,
                inputs_snapshot=json.dumps(gen.inputs_snapshot),
                model=gen.model,
                constitution_version=gen.constitution_version,
                created_at=gen.generated_at,
            )
        )
        return gen


def _bind(stub: _StubGenerator, session):
    """Adapt the (session, iso_week) stub to the ``WeeklyPlanGenerator`` ``(iso_week)`` seam."""

    def generate(iso_week: str) -> GeneratedWeeklyPlan:
        return stub(session, iso_week)

    return generate


def _row_count(session) -> int:
    return len(session.scalars(select(Plans).where(Plans.iso_week == ISO_WEEK)).all())


# --------------------------------------------------------------------------- #
# Miss → generate + commit + cached=False
# --------------------------------------------------------------------------- #
def test_miss_generates_commits_and_returns_cached_false(session) -> None:
    stub = _StubGenerator()
    plan, cached = get_or_generate_weekly(
        session, ISO_WEEK, refresh=False, generate=_bind(stub, session)
    )
    assert stub.calls == 1
    assert cached is False
    assert plan.data["isoWeek"] == ISO_WEEK
    # The single committed row survives a fresh session bound to the same engine.
    session.expunge_all()
    assert _row_count(session) == 1
    row = lookup_plan(session, ISO_WEEK)
    assert row is not None and row.payload is not None


# --------------------------------------------------------------------------- #
# Hit → stored plan, cached=True, no generate
# --------------------------------------------------------------------------- #
def test_hit_serves_stored_plan_without_generate(session) -> None:
    stub = _StubGenerator()
    get_or_generate_weekly(session, ISO_WEEK, refresh=False, generate=_bind(stub, session))
    plan, cached = get_or_generate_weekly(
        session, ISO_WEEK, refresh=False, generate=_bind(stub, session)
    )
    assert stub.calls == 1  # not re-invoked on the hit
    assert cached is True
    assert plan.data["isoWeek"] == ISO_WEEK
    assert plan.narrative == _narrative()
    assert _row_count(session) == 1


# --------------------------------------------------------------------------- #
# refresh=True → delete then regenerate (one row, new values)
# --------------------------------------------------------------------------- #
def test_refresh_deletes_then_regenerates(session) -> None:
    first = _StubGenerator(marker="v1")
    get_or_generate_weekly(session, ISO_WEEK, refresh=False, generate=_bind(first, session))
    second = _StubGenerator(marker="v2")
    plan, cached = get_or_generate_weekly(
        session, ISO_WEEK, refresh=True, generate=_bind(second, session)
    )
    assert second.calls == 1
    assert cached is False
    assert plan.data["core"][0]["marker"] == "v2"
    assert _row_count(session) == 1
    stored = json.loads(lookup_plan(session, ISO_WEEK).payload)
    assert stored["core"][0]["marker"] == "v2"


# --------------------------------------------------------------------------- #
# No second writer — a duplicate generate without a delete trips UNIQUE(iso_week)
# --------------------------------------------------------------------------- #
def test_duplicate_generate_without_refresh_trips_unique(session) -> None:
    # Cache an existing row for the week (committed).
    stub = _StubGenerator()
    get_or_generate_weekly(session, ISO_WEEK, refresh=False, generate=_bind(stub, session))

    # A generate that inserts a SECOND row for the already-cached week WITHOUT a
    # refresh-delete (the service adds no writer of its own; if a second writer existed
    # alongside the workflow's PersistPlanNode this is what would happen) → the
    # UNIQUE(iso_week) constraint rejects the duplicate, guaranteeing one plan per week.
    def double_insert(iso_week: str) -> GeneratedWeeklyPlan:
        return stub(session, iso_week)

    # Force the insert path past the cache-hit short-circuit via refresh, then re-insert
    # within the same uncommitted transaction so the second insert collides on commit.
    with pytest.raises(IntegrityError):
        delete_existing = lookup_plan(session, ISO_WEEK)
        assert delete_existing is not None  # the cached row is present
        double_insert(ISO_WEEK)  # mirrors PersistPlanNode inserting again (no delete)
        session.commit()
    session.rollback()
    assert _row_count(session) == 1


# --------------------------------------------------------------------------- #
# lookup_plan / delete_plan semantics
# --------------------------------------------------------------------------- #
def test_lookup_and_delete_semantics(session) -> None:
    assert lookup_plan(session, ISO_WEEK) is None
    assert delete_plan(session, ISO_WEEK) is False

    stub = _StubGenerator()
    get_or_generate_weekly(session, ISO_WEEK, refresh=False, generate=_bind(stub, session))
    assert lookup_plan(session, ISO_WEEK) is not None
    assert delete_plan(session, ISO_WEEK) is True
    session.commit()
    assert lookup_plan(session, ISO_WEEK) is None


# --------------------------------------------------------------------------- #
# Round-trip fidelity — a hit deserialises to the same GeneratedWeeklyPlan a miss returned
# --------------------------------------------------------------------------- #
def test_round_trip_fidelity(session) -> None:
    stub = _StubGenerator()
    miss_plan, _ = get_or_generate_weekly(
        session, ISO_WEEK, refresh=False, generate=_bind(stub, session)
    )
    hit_plan, cached = get_or_generate_weekly(
        session, ISO_WEEK, refresh=False, generate=_bind(stub, session)
    )
    assert cached is True
    assert hit_plan.data == miss_plan.data
    assert hit_plan.narrative == miss_plan.narrative
    assert hit_plan.model == miss_plan.model
    assert hit_plan.constitution_version == miss_plan.constitution_version
    assert hit_plan.generated_at == miss_plan.generated_at
