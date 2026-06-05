"""Agent-mocked unit tests for `TuneSessionNode` — the daily AgentNode (E11·P1).

Every test mocks the model (`TestModel`/`FunctionModel` via `Agent.override`, the
E9·P1 seam) — **no** live Anthropic call, **no** network, **no** `ANTHROPIC_API_KEY`.
TASK-002 covers the node specialisation + the pure `build_daily_computed` bundle;
TASK-003 adds the wired `validate_daily` validator.
"""

import asyncio
import json

import pytest

from app.api.schemas.daily import DailyBriefLLMOutput
from app.core import TaskContext
from app.core.enums import ReadinessBand, WorkoutCard

# --------------------------------------------------------------------------- #
# Feed fixtures — already-computed E8·P1 readiness+band, E8·P2 (un-triggered)
# safety gate, E10 week-plan cards, the check-in flags. The node serialises
# these into the USER context; it computes none of them.
# --------------------------------------------------------------------------- #


def _readiness(*, band: ReadinessBand = ReadinessBand.green, score: int = 90):
    from app.services.readiness import Readiness

    return Readiness(score=score, band=band, penalties=[])


def _safety_gate(*, triggered: bool = False):
    from app.services.safety_gate import SafetyGate

    return SafetyGate(triggered=triggered)


def _feeds(
    *,
    band: ReadinessBand = ReadinessBand.green,
    knee_pain: int = 0,
    week_plan_cards=(WorkoutCard.vo2, WorkoutCard.easy_run, WorkoutCard.strength_pull),
    triggered: bool = False,
) -> dict:
    return {
        "readiness": _readiness(band=band),
        "safety_gate": _safety_gate(triggered=triggered),
        "week_plan_cards": frozenset(week_plan_cards),
        "flags": {"knee_pain": knee_pain, "gi_symptoms": False},
        "aggregates": {"training7d": {"days": 7}},
        "constants": {"cadence_spm": 165},
        "live_weight_kg": 78.0,
    }


@pytest.fixture
def _profile():
    from app.core.profile import load_profile

    return load_profile()


@pytest.fixture
def _no_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _ctx_with(profile, **feed_kwargs) -> TaskContext:
    """A `TaskContext` carrying the live `Profile` + the computed daily feeds."""
    return TaskContext(
        event=None,
        metadata={"profile": profile, "computed": _feeds(**feed_kwargs)},
    )


def _ctx_feeds_only(**feed_kwargs) -> TaskContext:
    return TaskContext(event=None, metadata={"computed": _feeds(**feed_kwargs)})


def _valid_brief_args() -> dict:
    """A genuinely clean slim daily brief: an in-plan VO2 session with an in-band
    dose, dayType=hard (floored for the hard card), one in-band alternative, and a
    daily-subset narrative."""
    return {
        "session": {"card": "vo2", "durationMinLow": 30, "durationMinHigh": 40},
        "alternatives": [
            {"card": "easy_run", "durationMinLow": 30, "durationMinHigh": 45},
        ],
        "skipOk": False,
        "dayType": "hard",
        "narrative": [
            {"type": "session", "heading": "Today", "body": "VO2 intervals."},
        ],
    }


def _function_model_returning(args: dict):
    """A `FunctionModel` that always calls the output tool with `args` (no live call)."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    calls = {"n": 0}

    def _respond(messages, info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        tool = info.output_tools[0]
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])

    return FunctionModel(_respond), calls


def _patch_build_agent(monkeypatch: pytest.MonkeyPatch, model) -> None:
    """Drive `process()`'s inner agent with a mock `model` via `agent.override`."""
    import app.core.agent_node as agent_node_mod

    real_build = agent_node_mod.build_agent

    def _build_with_mock_model(*args, **kwargs):
        agent = real_build(*args, **kwargs)
        original_run = agent.run

        async def _run_under_override(*run_args, **run_kwargs):
            with agent.override(model=model):
                return await original_run(*run_args, **run_kwargs)

        agent.run = _run_under_override
        return agent

    monkeypatch.setattr(agent_node_mod, "build_agent", _build_with_mock_model)


# --------------------------------------------------------------------------- #
# TASK-002 — node specialisation + pure build_daily_computed
# --------------------------------------------------------------------------- #


def test_tune_session_node_subclasses_pydantic_agent_node():
    import app.core.agent_node as agent_node_mod
    import app.core.nodes as nodes
    from app.core.daily_agent import TuneSessionNode

    assert issubclass(TuneSessionNode, agent_node_mod.PydanticAgentNode)
    assert issubclass(TuneSessionNode, nodes.AgentNode)


def test_tune_session_node_does_not_override_process():
    import app.core.agent_node as agent_node_mod
    from app.core.daily_agent import TuneSessionNode

    assert TuneSessionNode.process is agent_node_mod.PydanticAgentNode.process


def test_get_agent_config_returns_output_type_and_opus_id():
    from app.core.daily_agent import TuneSessionNode
    from app.core.nodes import AgentConfig

    cfg = TuneSessionNode().get_agent_config()
    assert isinstance(cfg, AgentConfig)
    assert cfg.output_type is DailyBriefLLMOutput
    assert cfg.model_id == "claude-opus-4-8"
    assert cfg.instructions is None


def test_get_agent_config_model_id_sourced_from_settings_not_hardcoded():
    from app.core.daily_agent import TuneSessionNode
    from app.core.settings import Settings

    cfg = TuneSessionNode().get_agent_config()
    assert cfg.model_id == Settings.model_fields["model_id"].default


def test_node_mode_is_daily():
    from app.core.daily_agent import TuneSessionNode

    assert TuneSessionNode.mode == "daily"


def test_build_system_prompt_is_rendered_constitution(_profile):
    from app.core.constitution import render_constitution
    from app.core.daily_agent import TuneSessionNode

    ctx = _ctx_with(_profile)
    node = TuneSessionNode(task_context=ctx)
    assert node.build_system_prompt(ctx) == render_constitution(_profile)


def test_build_daily_computed_is_pure_dict_over_feeds():
    from app.core.daily_agent import build_daily_computed

    bundle = build_daily_computed(**_feeds())
    assert isinstance(bundle, dict)
    # The band surfaces from readiness; the week plan cards are a sorted card list.
    assert bundle["band"] == ReadinessBand.green
    assert bundle["week_plan"] == {
        "cards": sorted(c.value for c in (WorkoutCard.vo2, WorkoutCard.easy_run, WorkoutCard.strength_pull))
    }
    assert bundle["safety_gate"]["triggered"] is False
    assert bundle["readiness"]["score"] == 90
    assert bundle["flags"]["knee_pain"] == 0


def test_build_run_input_is_json_of_build_user_context_daily(_profile):
    from app.core.agent_node import build_user_context
    from app.core.daily_agent import TuneSessionNode, build_daily_computed

    ctx = _ctx_with(_profile)
    node = TuneSessionNode(task_context=ctx)
    parsed = json.loads(node.build_run_input(ctx))
    # The USER context carries the readiness/band/gate/week-plan/flags keys.
    for key in ("readiness", "band", "safetyGate", "weekPlan", "flags"):
        assert key in parsed
    # It is exactly build_user_context over the daily bundle (shared builder, mode=daily).
    expected = build_user_context(
        _profile, computed=build_daily_computed(**_feeds()), mode="daily"
    )
    assert parsed == json.loads(json.dumps(expected, sort_keys=True))
    assert parsed["band"] == "green"
    assert parsed["weekPlan"]["cards"] == sorted(
        c.value for c in (WorkoutCard.vo2, WorkoutCard.easy_run, WorkoutCard.strength_pull)
    )


def test_build_deps_carries_validator_subset(_profile):
    from app.core.daily_agent import DailyDeps, TuneSessionNode

    node = TuneSessionNode()
    deps = node.build_deps(_ctx_feeds_only(band=ReadinessBand.amber, knee_pain=5))
    assert isinstance(deps, DailyDeps)
    assert deps.band is ReadinessBand.amber
    assert deps.knee_pain == 5
    assert WorkoutCard.vo2 in deps.week_plan_cards
    assert deps.safety_gate_triggered is False


def test_process_stores_typed_output(_no_anthropic_key, monkeypatch, _profile):
    from app.core.daily_agent import TuneSessionNode

    model, _calls = _function_model_returning(_valid_brief_args())
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile)
    node = TuneSessionNode(task_context=ctx)
    result = asyncio.run(node.process(ctx))

    assert result is ctx
    stored = node.get_output(TuneSessionNode)
    assert isinstance(stored, DailyBriefLLMOutput)
    assert ctx.nodes[node.node_name] is stored
    assert stored.session.card is WorkoutCard.vo2


def test_untriggered_gate_path_fires_the_agent(_no_anthropic_key, monkeypatch, _profile):
    """On the non-gated path (safety_gate_triggered=False) the agent runs — the
    gate-skip is E11·P2's router, not this node (OOS)."""
    from app.core.daily_agent import TuneSessionNode

    model, calls = _function_model_returning(_valid_brief_args())
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile, triggered=False)
    node = TuneSessionNode(task_context=ctx)
    asyncio.run(node.process(ctx))
    assert calls["n"] >= 1
    assert isinstance(node.get_output(TuneSessionNode), DailyBriefLLMOutput)


def test_daily_agent_module_has_no_route_or_db_or_other_node_import():
    import re
    from pathlib import Path

    import app.core.daily_agent as daily_agent_mod

    source = Path(daily_agent_mod.__file__).read_text()
    forbidden = re.compile(
        r"fastapi|APIRouter|Depends|langfuse|observe|DeriveSessionNode|"
        r"compute_macro_focus|compute_readiness|evaluate_safety_gate|"
        r"SafetyGateRouter|Workflow\(|GeneratePlanNode|select\(|Session\("
    )
    assert not forbidden.search(source), "pure-core boundary breached in daily_agent.py"


# --------------------------------------------------------------------------- #
# TASK-003 — wired validate_daily output validator (ModelRetry on hard violation)
# --------------------------------------------------------------------------- #


def _fuel_floor_violating_args() -> dict:
    """A hard/long card (vo2) under-fuelled — dayType=moderate floors at hard."""
    args = _valid_brief_args()
    args["dayType"] = "moderate"
    return args


def _amber_top_intensity_args() -> dict:
    """A clean-but-vo2 brief (dayType=hard) — only AMBER gating flags it."""
    return _valid_brief_args()


def _three_alternatives_args() -> dict:
    """A clean primary with 3 in-plan, in-band alternatives — > the ≤ 2 cap."""
    args = _valid_brief_args()
    args["alternatives"] = [
        {"card": "easy_run", "durationMinLow": 30, "durationMinHigh": 45},
        {"card": "strength_pull", "durationMinLow": 30, "durationMinHigh": 40},
        {"card": "active_recovery", "durationMinLow": 25, "durationMinHigh": 35},
    ]
    return args


def _plan_narrative_args() -> dict:
    """A clean brief whose narrative carries a weekly-only `plan` section."""
    args = _valid_brief_args()
    args["narrative"] = [
        {"type": "session", "heading": "Today", "body": "VO2 intervals."},
        {"type": "plan", "heading": "Week", "body": "plan is a weekly-only kind"},
    ]
    return args


def test_get_validate_fn_returns_a_callable():
    from app.core.daily_agent import TuneSessionNode

    fn = TuneSessionNode().get_validate_fn()
    assert fn is not None
    assert callable(fn)


def test_validate_fn_flags_card_not_in_plan_and_reads_deps():
    """vo2 is not in a plan of {easy_run, strength_pull}, so card_not_in_plan
    fires — proving the validator read the deps' week_plan_cards."""
    from app.core.agent_node import _deps_to_validation_context
    from app.core.constraints import Severity
    from app.core.daily_agent import DailyDeps, validate_daily_output

    out = DailyBriefLLMOutput.model_validate(_valid_brief_args())  # session = vo2
    deps = DailyDeps(
        band=ReadinessBand.green,
        knee_pain=0,
        week_plan_cards=frozenset({WorkoutCard.easy_run, WorkoutCard.strength_pull}),
    )
    vctx = _deps_to_validation_context(deps)
    rules = {v.rule for v in validate_daily_output(out, vctx) if v.severity is Severity.hard}
    assert "card_not_in_plan" in rules


def test_validate_fn_flags_knee_impact_and_reads_deps():
    """An impact card (easy_run) with knee_pain=5 in the deps → knee_impact_blocked."""
    from app.core.agent_node import _deps_to_validation_context
    from app.core.daily_agent import DailyDeps, validate_daily_output

    out = DailyBriefLLMOutput.model_validate(
        {
            "session": {"card": "easy_run", "durationMinLow": 30, "durationMinHigh": 45},
            "alternatives": [],
            "skipOk": False,
            "dayType": "hard",
            "narrative": [{"type": "session", "heading": "T", "body": "easy."}],
        }
    )
    deps = DailyDeps(
        band=ReadinessBand.green,
        knee_pain=5,
        week_plan_cards=frozenset({WorkoutCard.easy_run, WorkoutCard.strength_pull}),
    )
    vctx = _deps_to_validation_context(deps)
    rules = {v.rule for v in validate_daily_output(out, vctx)}
    assert "knee_impact_blocked" in rules
    # With knee_pain=0 the same card is clean — proving the deps value drove it.
    clean_deps = DailyDeps(
        band=ReadinessBand.green,
        knee_pain=0,
        week_plan_cards=frozenset({WorkoutCard.easy_run, WorkoutCard.strength_pull}),
    )
    assert validate_daily_output(out, _deps_to_validation_context(clean_deps)) == []


def test_validate_fn_flags_plan_narrative_subset():
    """A `plan` daily section is a hard violation (LLM §1 daily subset)."""
    from app.core.agent_node import _deps_to_validation_context
    from app.core.constraints import Severity
    from app.core.daily_agent import DailyDeps, validate_daily_output

    out = DailyBriefLLMOutput.model_validate(_plan_narrative_args())
    deps = DailyDeps(
        band=ReadinessBand.green,
        week_plan_cards=frozenset({WorkoutCard.vo2, WorkoutCard.easy_run}),
    )
    vctx = _deps_to_validation_context(deps)
    violations = validate_daily_output(out, vctx)
    assert any(
        v.rule == "daily_narrative_type" and v.severity is Severity.hard for v in violations
    )
    # A summary|session|nutrition|caution-only brief has no narrative-subset hard.
    clean = DailyBriefLLMOutput.model_validate(_valid_brief_args())
    assert validate_daily_output(clean, vctx) == []


def test_fuel_floor_violation_retries_then_brief_generation_failed(
    _no_anthropic_key, monkeypatch, _profile
):
    from app.core.agent_node import BriefGenerationError
    from app.core.daily_agent import TuneSessionNode

    model, calls = _function_model_returning(_fuel_floor_violating_args())
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile)  # band green, plan includes vo2
    node = TuneSessionNode(task_context=ctx)
    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))

    assert excinfo.value.code == "brief_generation_failed"
    assert 2 <= calls["n"] <= 3  # initial + at least one retry, bounded by retries=2
    assert node.node_name not in ctx.nodes  # nothing under-fuelled reached the cache


def test_fuel_floored_hard_card_is_accepted(_no_anthropic_key, monkeypatch, _profile):
    from app.core.daily_agent import TuneSessionNode

    model, _calls = _function_model_returning(_valid_brief_args())  # vo2 + dayType=hard
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile)
    node = TuneSessionNode(task_context=ctx)
    asyncio.run(node.process(ctx))
    assert isinstance(node.get_output(TuneSessionNode), DailyBriefLLMOutput)


def test_amber_full_intensity_retries_then_failed(_no_anthropic_key, monkeypatch, _profile):
    from app.core.agent_node import BriefGenerationError
    from app.core.daily_agent import TuneSessionNode

    model, calls = _function_model_returning(_amber_top_intensity_args())  # vo2/z5
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile, band=ReadinessBand.amber)  # AMBER forbids full vo2/z5
    node = TuneSessionNode(task_context=ctx)
    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))
    assert excinfo.value.code == "brief_generation_failed"
    assert calls["n"] >= 2
    assert node.node_name not in ctx.nodes


def test_clean_brief_passes_validator_and_is_stored(_no_anthropic_key, monkeypatch, _profile):
    from app.core.daily_agent import TuneSessionNode

    model, _calls = _function_model_returning(_valid_brief_args())
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile)  # green, in-plan, in-band, fuel-floored
    node = TuneSessionNode(task_context=ctx)
    asyncio.run(node.process(ctx))
    assert isinstance(node.get_output(TuneSessionNode), DailyBriefLLMOutput)


def test_three_alternatives_retries_not_422(_no_anthropic_key, monkeypatch, _profile):
    from app.core.agent_node import BriefGenerationError
    from app.core.daily_agent import TuneSessionNode

    model, calls = _function_model_returning(_three_alternatives_args())
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile)
    node = TuneSessionNode(task_context=ctx)
    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))
    assert excinfo.value.code == "brief_generation_failed"  # a ModelRetry, not a 422
    assert calls["n"] >= 2
    assert node.node_name not in ctx.nodes


def test_plan_narrative_section_retries(_no_anthropic_key, monkeypatch, _profile):
    from app.core.agent_node import BriefGenerationError
    from app.core.daily_agent import TuneSessionNode

    model, calls = _function_model_returning(_plan_narrative_args())
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile)
    node = TuneSessionNode(task_context=ctx)
    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))
    assert excinfo.value.code == "brief_generation_failed"
    assert calls["n"] >= 2
    assert node.node_name not in ctx.nodes


def _missing_dose_args() -> dict:
    """A brief whose session omits its dose (permissive nullable type allows it)."""
    return {
        "session": {"card": "vo2"},  # no durationMin* → None/None
        "alternatives": [],
        "skipOk": False,
        "dayType": "hard",
        "narrative": [{"type": "session", "heading": "T", "body": "x"}],
    }


def test_validate_fn_flags_missing_dose_instead_of_crashing():
    """A None-dose pick is a hard `dose_out_of_band` Violation, NOT a TypeError —
    the validator guards E7·P3's `validate_daily` (which assumes concrete doses)."""
    from app.core.agent_node import _deps_to_validation_context
    from app.core.constraints import Severity
    from app.core.daily_agent import DailyDeps, validate_daily_output

    out = DailyBriefLLMOutput.model_validate(_missing_dose_args())
    deps = DailyDeps(
        band=ReadinessBand.green, week_plan_cards=frozenset({WorkoutCard.vo2})
    )
    vctx = _deps_to_validation_context(deps)
    violations = validate_daily_output(out, vctx)  # must not raise
    assert any(
        v.rule == "dose_out_of_band" and v.severity is Severity.hard for v in violations
    )


def test_missing_dose_brief_retries_to_failed_not_a_raw_crash(
    _no_anthropic_key, monkeypatch, _profile
):
    """End-to-end: a model that omits the dose triggers a ModelRetry and surfaces
    as a clean `brief_generation_failed`, never a raw TypeError out of process()."""
    from app.core.agent_node import BriefGenerationError
    from app.core.daily_agent import TuneSessionNode

    model, calls = _function_model_returning(_missing_dose_args())
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile)
    node = TuneSessionNode(task_context=ctx)
    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))
    assert excinfo.value.code == "brief_generation_failed"
    assert calls["n"] >= 2
    assert node.node_name not in ctx.nodes
