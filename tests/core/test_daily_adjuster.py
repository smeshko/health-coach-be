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
import json
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


# --------------------------------------------------------------------------- #
# TASK-002: resolve_day_type + derive_intake_summary + DeriveSessionNode.
# --------------------------------------------------------------------------- #
def test_resolve_day_type_default_floor_and_passthrough():
    from app.core.daily_adjuster import resolve_day_type

    # hard/long card → floored at hard regardless of the LLM's pick (or absence).
    assert resolve_day_type(DayType.moderate, WorkoutCard.vo2) is DayType.hard
    assert resolve_day_type(None, WorkoutCard.vo2) is DayType.hard
    assert resolve_day_type(DayType.rest, WorkoutCard.long_run) is DayType.hard
    # easy card → the LLM's pick passes through; absent → the card default.
    assert resolve_day_type(DayType.moderate, WorkoutCard.easy_run) is DayType.moderate
    assert resolve_day_type(None, WorkoutCard.easy_run) is DayType.moderate


def test_derive_intake_summary_matches_models_worked_example():
    from app.core.daily_adjuster import derive_intake_summary
    from app.services.macros import MacroFocus

    target = MacroFocus(
        day_type=DayType.moderate,
        calories_kcal=2510,
        protein_g=140,
        carbs_g=250,
        fat_g_low=70,
        fat_g_high=90,
        hydration_l_low=2.5,
        hydration_l_high=3.5,
    )
    row = DailyMetrics(
        date=YESTERDAY.isoformat(),
        kcal_in=2610.0,
        protein_in_g=138.0,
        carbs_in_g=250.0,
        fat_in_g=82.0,
        fiber_in_g=21.0,
        water_in_l=2.4,
    )
    summary = derive_intake_summary(row, target)
    assert summary is not None
    assert summary.vs_target.calories_pct == 1.04  # 2610 / 2510
    assert summary.vs_target.protein_hit is False  # 138 < 140
    assert summary.calories_kcal == 2610
    assert summary.date == YESTERDAY


def test_derive_intake_summary_none_when_nothing_logged():
    from app.core.daily_adjuster import derive_intake_summary
    from app.services.macros import MacroFocus

    target = MacroFocus(
        day_type=DayType.rest,
        calories_kcal=2000,
        protein_g=140,
        carbs_g=150,
        fat_g_low=70,
        fat_g_high=90,
        hydration_l_low=2.5,
        hydration_l_high=3.5,
    )
    assert derive_intake_summary(None, target) is None
    empty = DailyMetrics(date=YESTERDAY.isoformat())  # all nutrition columns null
    assert derive_intake_summary(empty, target) is None


def test_derive_session_node_expands_and_resolves(session, profile_path):
    from app.core.daily_adjuster import DeriveSessionNode

    seed_metrics(
        session,
        yesterday_kwargs=dict(kcal_in=2400.0, protein_in_g=150.0, carbs_in_g=240.0),
    )
    ctx = _ctx(session, TuneSessionNode=_clean_daily_output(card="vo2", day_type="hard"))
    asyncio.run(DeriveSessionNode(task_context=ctx).process(ctx))

    out = ctx.nodes["DeriveSessionNode"]
    # The session is a code-expanded SessionBlock (card-derived fields from CARD_META).
    assert out.session.card is WorkoutCard.vo2
    assert out.session.zone_target.value == "z5"
    assert out.session.intensity.value == "quality"
    assert out.session.duration_min_low == 30  # dose copied verbatim
    assert len(out.alternatives) == 1 and out.alternatives[0].card is WorkoutCard.easy_run
    # MacroFocus grams come from the resolved dayType (hard).
    assert out.macro_focus.day_type is DayType.hard
    assert out.macro_focus.calories_kcal > 0
    # Yesterday's intake is derived.
    assert out.intake_yesterday is not None
    assert out.intake_yesterday.calories_kcal == 2400


def test_derive_session_node_floors_day_type_for_hard_card(session, profile_path):
    from app.core.daily_adjuster import DeriveSessionNode

    seed_metrics(session)
    # The LLM emitted dayType=moderate on a hard vo2 card → floored to hard for macros.
    ctx = _ctx(
        session, TuneSessionNode=_clean_daily_output(card="vo2", day_type="moderate")
    )
    asyncio.run(DeriveSessionNode(task_context=ctx).process(ctx))
    assert ctx.nodes["DeriveSessionNode"].macro_focus.day_type is DayType.hard


# --------------------------------------------------------------------------- #
# TASK-003: ValidateSessionNode + PersistSuggestionNode.
# --------------------------------------------------------------------------- #
def _readiness_output(band="green", score=100):
    from app.core.daily_adjuster import ComputeReadinessNode
    from app.core.enums import ReadinessBand
    from app.services.readiness import Readiness

    return ComputeReadinessNode.OutputType(
        readiness=Readiness(score=score, band=ReadinessBand(band), penalties=[])
    )


def test_validate_session_node_raises_on_hard_violation(session, profile_path):
    from app.core.agent_node import BriefGenerationError
    from app.core.daily_adjuster import ValidateSessionNode

    seed_metrics(session)
    # AMBER band + a full vo2 (z5) card → amber_full_intensity (a hard violation).
    ctx = _ctx(
        session,
        ComputeReadinessNode=_readiness_output(band="amber", score=60),
        TuneSessionNode=_clean_daily_output(card="vo2", day_type="hard"),
    )
    with pytest.raises(BriefGenerationError) as exc:
        asyncio.run(ValidateSessionNode(task_context=ctx).process(ctx))
    assert exc.value.code == "brief_generation_failed"


def test_validate_session_node_passes_clean_session(session, profile_path):
    from app.core.daily_adjuster import ValidateSessionNode

    seed_metrics(session)
    ctx = _ctx(
        session,
        ComputeReadinessNode=_readiness_output(band="green"),
        TuneSessionNode=_clean_daily_output(card="vo2", day_type="hard"),
    )
    out_ctx = asyncio.run(ValidateSessionNode(task_context=ctx).process(ctx))
    assert out_ctx is ctx  # no raise


def _clean_persist_ctx(session):
    """A ctx with readiness bridged + a clean gate + DeriveSessionNode run."""
    from app.core.daily_adjuster import (
        ComputeReadinessNode,
        DeriveSessionNode,
    )
    from app.services.safety_gate import SafetyGate

    seed_metrics(
        session, yesterday_kwargs=dict(kcal_in=2400.0, protein_in_g=150.0)
    )
    ctx = _ctx(session, TuneSessionNode=_clean_daily_output(card="vo2", day_type="hard"))
    asyncio.run(ComputeReadinessNode(task_context=ctx).process(ctx))  # bridges metadata
    ctx.nodes["GateTrippedRoute"] = SafetyGate(triggered=False)
    asyncio.run(DeriveSessionNode(task_context=ctx).process(ctx))
    return ctx


def test_persist_suggestion_node_writes_one_row_with_columns(session, profile_path):
    from app.core.daily_adjuster import PersistSuggestionNode

    ctx = _clean_persist_ctx(session)
    asyncio.run(PersistSuggestionNode(task_context=ctx).process(ctx))

    rows = session.execute(select(Suggestions)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.date == TODAY.isoformat()
    assert row.readiness_score == 100 and row.band == "green"
    assert row.safety_gate_tripped == 0 and row.gate_reason is None
    assert row.model and row.constitution_version and row.created_at
    # payload is the { data, narrative } wire brief.
    brief = json.loads(row.payload)
    assert set(brief) == {"data", "narrative"}
    data = brief["data"]
    assert data["session"]["card"] == "vo2"
    assert "macroFocus" in data and "intakeYesterday" in data and data["skipOk"] is False


def test_persist_suggestion_node_writes_back_readiness_band(session, profile_path):
    from app.core.daily_adjuster import PersistSuggestionNode

    ctx = _clean_persist_ctx(session)
    asyncio.run(PersistSuggestionNode(task_context=ctx).process(ctx))

    dm = session.execute(
        select(DailyMetrics).where(DailyMetrics.date == TODAY.isoformat())
    ).scalar_one()
    assert dm.readiness_score == 100 and dm.band == "green"


def test_persist_inputs_snapshot_carries_readiness_gate_band_constants(session, profile_path):
    from app.core.daily_adjuster import PersistSuggestionNode

    ctx = _clean_persist_ctx(session)
    asyncio.run(PersistSuggestionNode(task_context=ctx).process(ctx))

    row = session.execute(select(Suggestions)).scalars().one()
    snapshot = json.loads(row.inputs_snapshot)
    assert set(snapshot) == {"readiness", "safety_gate", "band", "constants"}


def test_persist_suggestion_node_does_not_commit_or_lookup(session, profile_path, monkeypatch):
    from app.core.daily_adjuster import PersistSuggestionNode

    monkeypatch.setattr(
        session, "commit", lambda *a, **k: pytest.fail("PersistSuggestionNode committed")
    )
    ctx = _clean_persist_ctx(session)
    asyncio.run(PersistSuggestionNode(task_context=ctx).process(ctx))
    assert session.execute(select(Suggestions)).scalars().all()  # row staged, uncommitted


# --------------------------------------------------------------------------- #
# TASK-004: the assembled DailyAdjuster workflow (node order + end-to-end).
# --------------------------------------------------------------------------- #
def test_node_order_and_router_branch_is_architecture_section_5():
    from app.core.daily_adjuster import (
        ComputeReadinessNode,
        DailyAdjuster,
        DeriveSessionNode,
        PersistSuggestionNode,
        SafetyGateRouter,
        SafetyRestNode,
        ValidateSessionNode,
    )
    from app.core.daily_agent import TuneSessionNode

    schema = DailyAdjuster.workflow_schema
    assert schema.start is ComputeReadinessNode
    edges = {nc.node: list(nc.connections) for nc in schema.nodes}
    assert edges[ComputeReadinessNode] == [SafetyGateRouter]
    assert edges[SafetyGateRouter] == [SafetyRestNode, TuneSessionNode]
    assert edges[SafetyRestNode] == []  # gated terminal — persists itself
    assert edges[TuneSessionNode] == [DeriveSessionNode]
    assert edges[DeriveSessionNode] == [ValidateSessionNode]
    assert edges[ValidateSessionNode] == [PersistSuggestionNode]
    assert edges[PersistSuggestionNode] == []  # clean terminal
    # SafetyGateRouter is the ONLY router.
    routers = [nc.node for nc in schema.nodes if nc.is_router]
    assert routers == [SafetyGateRouter]


def test_daily_adjuster_constructs_without_error():
    from app.core.daily_adjuster import DailyAdjuster

    assert DailyAdjuster() is not None  # the E1·P3 WorkflowValidator accepts the branch


def _mock_tune_session(monkeypatch, llm_output):
    """Substitute the AgentNode's process with a stand-in (no LLM/network/key)."""
    from app.core.daily_agent import TuneSessionNode

    async def _stand_in(self, task_context):
        self.save_output(llm_output)
        return task_context

    monkeypatch.setattr(TuneSessionNode, "process", _stand_in, raising=True)


def _run_event_ctx(session):
    from app.core.daily_adjuster import DailyAdjusterEvent

    return TaskContext(
        event=DailyAdjusterEvent(date=TODAY), metadata={"session": session}
    )


def test_end_to_end_happy_path_clean_gate(session, profile_path, monkeypatch):
    from app.core.daily_adjuster import DailyAdjuster

    seed_metrics(session, yesterday_kwargs=dict(kcal_in=2400.0, protein_in_g=150.0))
    _mock_tune_session(monkeypatch, _clean_daily_output(card="vo2", day_type="hard"))

    ctx = _run_event_ctx(session)
    out_ctx = asyncio.run(DailyAdjuster().run_async(context=ctx))

    for name in (
        "ComputeReadinessNode",
        "GateTrippedRoute",
        "TuneSessionNode",
        "DeriveSessionNode",
        "ValidateSessionNode",
        "PersistSuggestionNode",
    ):
        assert name in out_ctx.nodes, f"{name} output missing"
    # Code-expanded session, macros from the resolved dayType, intake derived.
    derived = out_ctx.nodes["DeriveSessionNode"]
    assert derived.session.zone_target.value == "z5"  # from CARD_META
    assert derived.macro_focus.day_type is DayType.hard
    assert derived.intake_yesterday is not None
    # Exactly one Suggestions row (safety_gate_tripped=0) + the daily_metrics write-back.
    rows = session.execute(select(Suggestions)).scalars().all()
    assert len(rows) == 1 and rows[0].safety_gate_tripped == 0 and rows[0].model
    dm = session.execute(
        select(DailyMetrics).where(DailyMetrics.date == TODAY.isoformat())
    ).scalar_one()
    assert dm.readiness_score is not None and dm.band == "green"


def test_end_to_end_gate_short_circuit_skips_llm(session, profile_path, monkeypatch):
    from app.core.daily_adjuster import DailyAdjuster
    from app.core.daily_agent import TuneSessionNode

    seed_metrics(session)
    seed_checkin(session, illness=1)  # gate trips

    called = {"n": 0}

    async def _must_not_run(self, task_context):
        called["n"] += 1
        raise AssertionError("the LLM must not run on the gated path")

    monkeypatch.setattr(TuneSessionNode, "process", _must_not_run, raising=True)

    ctx = _run_event_ctx(session)
    out_ctx = asyncio.run(DailyAdjuster().run_async(context=ctx))  # returns normally

    assert called["n"] == 0  # the agent was never invoked (no LLM)
    assert "SafetyRestNode" in out_ctx.nodes
    assert "DeriveSessionNode" not in out_ctx.nodes  # clean-path nodes never ran
    rows = session.execute(select(Suggestions)).scalars().all()
    assert len(rows) == 1
    assert rows[0].safety_gate_tripped == 1 and rows[0].gate_reason and rows[0].model is None
    dm = session.execute(
        select(DailyMetrics).where(DailyMetrics.date == TODAY.isoformat())
    ).scalar_one()
    assert dm.readiness_score is not None  # still written back on the gated path


def test_end_to_end_constraint_breaking_never_persists(session, profile_path, monkeypatch):
    from app.core.agent_node import BriefGenerationError
    from app.core.daily_adjuster import DailyAdjuster

    seed_metrics(session)
    # A vo2 (hard/long) card with dayType=moderate under-fuels → ValidateSessionNode
    # rejects the LLM's raw under-fuelling dayType (the fuel-floor safety guard).
    _mock_tune_session(monkeypatch, _clean_daily_output(card="vo2", day_type="moderate"))

    ctx = _run_event_ctx(session)
    with pytest.raises(BriefGenerationError) as exc:
        asyncio.run(DailyAdjuster().run_async(context=ctx))
    assert exc.value.code == "brief_generation_failed"
    assert not session.execute(select(Suggestions)).scalars().all()  # no row
    dm = session.execute(
        select(DailyMetrics).where(DailyMetrics.date == TODAY.isoformat())
    ).scalar_one()
    assert dm.readiness_score is None  # write-back never ran (persist skipped)


def test_end_to_end_persisted_macro_day_type_is_hard_for_hard_card(session, profile_path, monkeypatch):
    from app.core.daily_adjuster import DailyAdjuster

    seed_metrics(session)
    _mock_tune_session(monkeypatch, _clean_daily_output(card="vo2", day_type="hard"))

    ctx = _run_event_ctx(session)
    asyncio.run(DailyAdjuster().run_async(context=ctx))

    row = session.execute(select(Suggestions)).scalars().one()
    data = json.loads(row.payload)["data"]
    assert data["macroFocus"]["dayType"] == "hard"  # hard card fuels hard
