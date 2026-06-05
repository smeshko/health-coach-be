"""DAILY_ADJUSTER workflow tests — the gate-routed graph, agent mocked (E11·P2).

The single ``AgentNode`` (``TuneSessionNode``) is **never** invoked live: per-node tests
seed a hand-built ``DailyBriefLLMOutput`` under ``ctx.nodes["TuneSessionNode"]``, and the
end-to-end tests (TASK-004) substitute a stand-in ``process`` — no PydanticAI, network, or
``ANTHROPIC_API_KEY``. The DB ``Session`` rides in ``ctx.metadata["session"]`` (the endpoint
seam); a temp ``profile.yaml`` (via ``PROFILE_PATH``) controls the constants. Mirrors the
E10·P2 ``test_weekly_planner.py`` pattern.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest
import yaml
from sqlalchemy import select

from app.core.enums import DayType, NarrativeType, WorkoutCard
from app.core.task_context import TaskContext
from app.database.models import Checkins, DailyMetrics, Suggestions

from tests.core.test_profile import valid_profile_dict

TODAY = date(2026, 6, 5)
YESTERDAY = TODAY - timedelta(days=1)


# --------------------------------------------------------------------------- #
# Fixtures: a temp profile.yaml + seeded daily_metrics / checkins rows.
# --------------------------------------------------------------------------- #
def _write_profile_yaml(tmp_path, monkeypatch):
    d = valid_profile_dict()
    d["meta"]["computed_at"] = d["meta"]["computed_at"].isoformat()
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("PROFILE_PATH", str(path))
    return path


@pytest.fixture
def profile_path(tmp_path, monkeypatch):
    return _write_profile_yaml(tmp_path, monkeypatch)


def seed_metrics(session, *, today_kwargs=None, yesterday_kwargs=None) -> None:
    """Seed a recovered today + yesterday ``daily_metrics`` row."""
    base = dict(
        sleep_h=7.5,
        hrv_sdnn=45.0,
        rhr=55.0,
        hrv_30d_mean=44.0,
        hrv_30d_sd=4.0,
        rhr_30d_mean=56.0,
        body_weight=78.0,
        hard_day=0,
    )
    session.add(DailyMetrics(date=TODAY.isoformat(), **{**base, **(today_kwargs or {})}))
    session.add(
        DailyMetrics(date=YESTERDAY.isoformat(), **{**base, **(yesterday_kwargs or {})})
    )
    session.flush()


def seed_checkin(session, **kwargs) -> None:
    session.add(Checkins(date=TODAY.isoformat(), **kwargs))
    session.flush()


def _ctx(session, **nodes) -> TaskContext:
    from app.core.daily_adjuster import DailyAdjusterEvent

    ctx = TaskContext(
        event=DailyAdjusterEvent(date=TODAY), metadata={"session": session}
    )
    ctx.nodes.update(nodes)
    return ctx


def _clean_daily_output(
    *, card="vo2", day_type="hard", alternatives=None, narrative=None
):
    from app.api.schemas.daily import DailyBriefLLMOutput

    return DailyBriefLLMOutput.model_validate(
        {
            "session": {"card": card, "durationMinLow": 30, "durationMinHigh": 40},
            "alternatives": alternatives
            if alternatives is not None
            else [{"card": "easy_run", "durationMinLow": 30, "durationMinHigh": 45}],
            "skipOk": False,
            "dayType": day_type,
            "narrative": narrative
            if narrative is not None
            else [{"type": "session", "heading": "T", "body": "VO2 intervals."}],
        }
    )


# --------------------------------------------------------------------------- #
# ComputeReadinessNode.
# --------------------------------------------------------------------------- #
def test_compute_readiness_node_reads_rows_and_saves_readiness(session, profile_path):
    from app.core.daily_adjuster import ComputeReadinessNode

    seed_metrics(session)
    ctx = _ctx(session)
    out_ctx = asyncio.run(ComputeReadinessNode(task_context=ctx).process(ctx))

    readiness = out_ctx.nodes["ComputeReadinessNode"].readiness
    assert readiness.score == 100  # fully recovered → no penalties
    assert readiness.band.value == "green"


def test_compute_readiness_node_bridges_agent_metadata(session, profile_path):
    from app.core.daily_adjuster import ComputeReadinessNode

    seed_metrics(session)
    seed_checkin(session, knee_pain=2)
    ctx = _ctx(session)
    asyncio.run(ComputeReadinessNode(task_context=ctx).process(ctx))

    from app.core.profile import Profile

    assert isinstance(ctx.metadata["profile"], Profile)
    computed = ctx.metadata["computed"]
    assert {"readiness", "band", "week_plan_cards", "flags", "live_weight_kg", "constants"} <= set(computed)
    assert computed["band"].value == "green"
    assert computed["flags"]["knee_pain"] == 2
    assert computed["live_weight_kg"] == 78.0
    assert WorkoutCard.vo2 in computed["week_plan_cards"]  # all-cards fallback (no plan)


def test_compute_readiness_node_does_not_write_back_daily_metrics(session, profile_path):
    from app.core.daily_adjuster import ComputeReadinessNode

    seed_metrics(session)
    ctx = _ctx(session)
    asyncio.run(ComputeReadinessNode(task_context=ctx).process(ctx))

    row = session.execute(
        select(DailyMetrics).where(DailyMetrics.date == TODAY.isoformat())
    ).scalar_one()
    assert row.readiness_score is None  # the snapshot is PersistSuggestionNode's
    assert row.band is None


# --------------------------------------------------------------------------- #
# GateTrippedRoute + SafetyGateRouter.
# --------------------------------------------------------------------------- #
def test_gate_route_clean_returns_none_and_saves_gate(session, profile_path):
    from app.core.daily_adjuster import GateTrippedRoute

    seed_metrics(session)  # healthy → no flags
    ctx = _ctx(session)
    route = GateTrippedRoute(task_context=ctx)
    assert route.determine_next_node(ctx) is None
    gate = ctx.nodes["GateTrippedRoute"]
    assert gate.triggered is False


def test_gate_route_tripped_returns_safety_rest(session, profile_path):
    from app.core.daily_adjuster import GateTrippedRoute, SafetyRestNode

    seed_metrics(session)
    seed_checkin(session, illness=1)  # §6.2 illness → gate trips
    ctx = _ctx(session)
    route = GateTrippedRoute(task_context=ctx)
    nxt = route.determine_next_node(ctx)
    assert isinstance(nxt, SafetyRestNode)
    gate = ctx.nodes["GateTrippedRoute"]
    assert gate.triggered is True and gate.overrideTo is not None


def test_safety_gate_router_routes_clean_to_tune_session(session, profile_path):
    from app.core.daily_adjuster import SafetyGateRouter
    from app.core.daily_agent import TuneSessionNode

    seed_metrics(session)
    ctx = _ctx(session)
    assert SafetyGateRouter().route(ctx) is TuneSessionNode


def test_safety_gate_router_routes_tripped_to_safety_rest(session, profile_path):
    from app.core.daily_adjuster import SafetyGateRouter, SafetyRestNode

    seed_metrics(session)
    seed_checkin(session, illness=1)
    ctx = _ctx(session)
    assert SafetyGateRouter().route(ctx) is SafetyRestNode


def test_stop_workflow_only_in_safety_rest_node():
    import pathlib

    src = pathlib.Path("app/core/daily_adjuster.py").read_text(encoding="utf-8")
    # The actual call `task_context.stop_workflow()` appears exactly once, inside
    # SafetyRestNode (the router never stops — the BaseRouter contract).
    assert src.count("task_context.stop_workflow()") == 1
    rest_region = src.split("class SafetyRestNode")[1]
    assert "task_context.stop_workflow()" in rest_region


# --------------------------------------------------------------------------- #
# SafetyRestNode — code-written + self-persisting gated terminal.
# --------------------------------------------------------------------------- #
def _tripped_ctx(session):
    """A ctx with the gate tripped + readiness/metadata bridged (the gated path)."""
    from app.core.daily_adjuster import ComputeReadinessNode, GateTrippedRoute

    seed_metrics(session)
    seed_checkin(session, illness=1)
    ctx = _ctx(session)
    asyncio.run(ComputeReadinessNode(task_context=ctx).process(ctx))
    GateTrippedRoute(task_context=ctx).determine_next_node(ctx)  # saves the gate
    return ctx


def test_safety_rest_node_code_writes_and_persists_rest_brief(session, profile_path):
    from app.core.daily_adjuster import SafetyRestNode

    ctx = _tripped_ctx(session)
    gate = ctx.nodes["GateTrippedRoute"]
    asyncio.run(SafetyRestNode(task_context=ctx).process(ctx))

    brief = ctx.nodes["SafetyRestNode"].brief
    data = brief["data"]
    assert data["session"]["card"] == gate.overrideTo.value  # forced override card
    assert data["alternatives"] == []
    assert data["macroFocus"]["dayType"] in {d.value for d in DayType}
    # The narrative is code-written, daily-subset only (no weekly-only `plan` kind).
    narrative_types = {n["type"] for n in brief["narrative"]}
    assert narrative_types and NarrativeType.plan.value not in narrative_types
    assert ctx.should_stop is True


def test_safety_rest_node_persists_one_row_model_none(session, profile_path):
    from app.core.daily_adjuster import SafetyRestNode

    ctx = _tripped_ctx(session)
    asyncio.run(SafetyRestNode(task_context=ctx).process(ctx))

    rows = session.execute(select(Suggestions)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.safety_gate_tripped == 1
    assert row.gate_reason  # the firing reasons
    assert row.model is None  # no model ran on the gated path
    assert row.date == TODAY.isoformat()
    # readiness/band written back onto today's daily_metrics row.
    dm = session.execute(
        select(DailyMetrics).where(DailyMetrics.date == TODAY.isoformat())
    ).scalar_one()
    assert dm.readiness_score is not None and dm.band == "green"


def test_safety_rest_node_constructs_no_agent():
    import pathlib

    src = pathlib.Path("app/core/daily_adjuster.py").read_text(encoding="utf-8")
    rest_region = src.split("class SafetyRestNode")[1].split("# ---")[0]
    # Parened forms so the class docstring's prose mentions don't trip the check.
    for forbidden in ("agent.run(", "Agent(", ".override("):
        assert forbidden not in rest_region


def test_node_bodies_reimplement_no_kernel():
    import pathlib
    import re

    src = pathlib.Path("app/core/daily_adjuster.py").read_text(encoding="utf-8")
    # No readiness/gate/macro arithmetic inlined in the nodes (the math is E8·P1/P2/P3).
    assert not re.search(r"def bmr\(|def tdee\(|knee_pain >\s*3|score\s*=\s*100\s*-", src)
