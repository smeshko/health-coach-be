"""Agent-mocked unit tests for `GeneratePlanNode` — the weekly AgentNode (E10·P1).

Every test mocks the model (`TestModel`/`FunctionModel` via `Agent.override`, the
E9·P1 seam) — **no** live Anthropic call, **no** network, **no** `ANTHROPIC_API_KEY`.
TASK-002 covers the node specialisation + the pure `build_weekly_context` builder;
TASK-003 adds the wired `validate_weekly` validator.
"""

import asyncio
import json

import pytest

from app.api.schemas.weekly import WeeklyPlanLLMOutput
from app.core import TaskContext
from app.core.enums import WorkoutCard

# --------------------------------------------------------------------------- #
# Feed fixtures — already-computed E8·P4 budgets, E6·P3 rollups & adherence,
# E8·P5 recomputed constants (the node serialises these; it computes none).
# --------------------------------------------------------------------------- #


def _budgets(*, hard_days: int = 2):
    from app.core.constraints import WeeklyBudgets

    return WeeklyBudgets(
        hard_days=hard_days, strength_sessions=2, long_run_km=18.0, deload=False
    )


def _training_rollup(days: int):
    from app.services.aggregates import TrainingRollup

    return TrainingRollup(
        days=days,
        z1_min=float(days * 10),
        z2_min=float(days * 20),
        z3_min=5.0,
        z4_min=2.0,
        z5_min=1.0,
        active_energy=float(days * 400),
        hard_days=2,
        n_days=days,
    )


def _nutrition_adherence():
    from app.services.aggregates import NutritionAdherence, NutritionConsumed

    consumed = NutritionConsumed(
        days=7,
        kcal_in=16800.0,
        protein_in_g=1020.0,
        carbs_in_g=1400.0,
        fat_in_g=420.0,
        fiber_in_g=210.0,
        sodium_in_mg=21000.0,
        water_in_l=21.0,
        n_days=7,
        kcal_in_n=7,
        protein_in_g_n=7,
        carbs_in_g_n=7,
        fat_in_g_n=7,
        fiber_in_g_n=7,
        sodium_in_mg_n=7,
        water_in_l_n=7,
    )
    return NutritionAdherence(
        consumed=consumed,
        target=None,
        avg_kcal=2400.0,
        avg_protein_g=146.0,
        kcal_pct=0.96,
        protein_hit_days=6,
        days_over_target=2,
        days_under_target=5,
    )


def _constants():
    # The E8·P5 recomputed-constant outputs (cadence cue, quality focus, zones).
    return {
        "cadence_spm": 165,
        "quality_focus": "vo2",
        "zones": {"z1": [110, 130], "z2": [131, 145]},
        "long_run_km": 18.0,
    }


def _feeds(*, hard_days: int = 2) -> dict:
    return {
        "budgets": _budgets(hard_days=hard_days),
        "training_7d": _training_rollup(7),
        "training_28d": _training_rollup(28),
        "nutrition_adherence": _nutrition_adherence(),
        "constants": _constants(),
    }


@pytest.fixture
def _profile():
    from app.core.profile import load_profile

    return load_profile()


@pytest.fixture
def _no_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _ctx_with(profile, *, hard_days: int = 2) -> TaskContext:
    """A `TaskContext` carrying the live `Profile` + the computed weekly feeds."""
    return TaskContext(
        event=None,
        metadata={"profile": profile, "computed": _feeds(hard_days=hard_days)},
    )


def _valid_plan_args() -> dict:
    """A genuinely clean slim plan: 2 core + 1 extra, 1 hard day (≤ budget 2),
    strength == 2, the quality run is VO2 (matching the deps quality pick), and
    every filled dose sits inside its CARD_META band."""
    return {
        "core": [
            {"card": "vo2", "suggestedDay": "tue", "durationMinLow": 30, "durationMinHigh": 40},
            {"card": "strength_pull", "suggestedDay": "mon", "durationMinLow": 30, "durationMinHigh": 45},
        ],
        "extras": [
            {"card": "strength_lower", "suggestedDay": "thu", "durationMinLow": 30, "durationMinHigh": 35},
        ],
        "narrative": [
            {"type": "plan", "heading": "Week", "body": "One quality day."},
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
    """Drive `process()`'s inner agent with a mock `model` via `agent.override`.

    The node's `process()` (inherited from E9·P1) builds the agent internally, so
    the test wraps the real `build_agent` and runs the call inside
    `agent.override(model=…)` — PydanticAI's supported in-process test seam. No
    live Anthropic call, no network, no key.
    """
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
# TASK-002 — node specialisation + pure build_weekly_context
# --------------------------------------------------------------------------- #


def test_generate_plan_node_subclasses_pydantic_agent_node():
    import app.core.agent_node as agent_node_mod
    import app.core.nodes as nodes
    from app.core.weekly_agent import GeneratePlanNode

    assert issubclass(GeneratePlanNode, agent_node_mod.PydanticAgentNode)
    assert issubclass(GeneratePlanNode, nodes.AgentNode)


def test_generate_plan_node_does_not_override_process():
    import app.core.agent_node as agent_node_mod
    from app.core.weekly_agent import GeneratePlanNode

    # process() is inherited from E9·P1, not reimplemented on the weekly node.
    assert GeneratePlanNode.process is agent_node_mod.PydanticAgentNode.process


def test_get_agent_config_returns_output_type_and_instructions():
    from app.core.nodes import AgentConfig
    from app.core.weekly_agent import GeneratePlanNode

    node = GeneratePlanNode()
    cfg = node.get_agent_config()
    assert isinstance(cfg, AgentConfig)
    assert cfg.output_type is WeeklyPlanLLMOutput
    # instructions left None — the constitution flows through build_system_prompt.
    assert cfg.instructions is None


def test_get_agent_config_model_id_follows_settings(monkeypatch):
    """model_id is read from the live ``get_settings().model_id`` (env ``MODEL_ID``), not a
    hard-coded default — so a Haiku/Sonnet downshift is a ``.env`` change (LLM §5). Env vars
    take precedence over ``.env`` in pydantic-settings, so this is deterministic."""
    from app.core.settings import Settings, get_settings
    from app.core.weekly_agent import GeneratePlanNode

    assert Settings.model_fields["model_id"].default == "claude-opus-4-8"  # documents default
    monkeypatch.setenv("MODEL_ID", "claude-sonnet-4-6")
    get_settings.cache_clear()
    try:
        assert GeneratePlanNode().get_agent_config().model_id == "claude-sonnet-4-6"
    finally:
        get_settings.cache_clear()


def test_build_system_prompt_is_rendered_constitution(_profile):
    from app.core.constitution import render_constitution
    from app.core.weekly_agent import GeneratePlanNode

    ctx = _ctx_with(_profile)
    node = GeneratePlanNode(task_context=ctx)
    assert node.build_system_prompt(ctx) == render_constitution(_profile)


def test_build_weekly_context_is_pure_dict_over_feeds():
    from app.core.weekly_agent import build_weekly_context

    ctx_dict = build_weekly_context(**_feeds())
    assert isinstance(ctx_dict, dict)
    assert set(ctx_dict) == {"budgets", "aggregates", "constants"}
    assert set(ctx_dict["aggregates"]) == {"training7d", "training28d", "nutritionAdherence"}
    # The budgets were serialised from the WeeklyBudgets feed.
    assert ctx_dict["budgets"]["hard_days"] == 2
    assert ctx_dict["budgets"]["strength_sessions"] == 2
    # long_run_km surfaced to the LLM (the ≤10% ramp cap, E8·P4).
    assert ctx_dict["budgets"]["long_run_km"] == 18.0
    # The 7/28d training rollups + nutrition adherence are present.
    assert ctx_dict["aggregates"]["training7d"]["days"] == 7
    assert ctx_dict["aggregates"]["training28d"]["days"] == 28
    assert "avg_protein_g" in ctx_dict["aggregates"]["nutritionAdherence"]
    # constants serialised through.
    assert ctx_dict["constants"]["quality_focus"] == "vo2"


def test_build_weekly_context_is_json_serialisable():
    from app.core.weekly_agent import build_weekly_context

    ctx_dict = build_weekly_context(**_feeds())
    # Round-trips through json without a custom encoder (proves it's pure primitives).
    assert json.loads(json.dumps(ctx_dict)) == ctx_dict


def test_build_run_input_is_json_of_build_weekly_context(_profile):
    from app.core.weekly_agent import GeneratePlanNode, build_weekly_context

    ctx = _ctx_with(_profile)
    node = GeneratePlanNode(task_context=ctx)
    parsed = json.loads(node.build_run_input(ctx))
    assert set(parsed) == {"budgets", "aggregates", "constants"}
    assert parsed == build_weekly_context(**_feeds())
    # The budgets/rollups/adherence/constants keys are all present for the LLM.
    assert parsed["budgets"]["hard_days"] == 2
    assert parsed["aggregates"]["training7d"]["days"] == 7
    assert parsed["aggregates"]["training28d"]["days"] == 28
    assert "nutritionAdherence" in parsed["aggregates"]
    assert parsed["constants"]["cadence_spm"] == 165


def test_process_stores_typed_output(_no_anthropic_key, monkeypatch, _profile):
    from app.core.weekly_agent import GeneratePlanNode

    model, _calls = _function_model_returning(_valid_plan_args())
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile)
    node = GeneratePlanNode(task_context=ctx)
    result = asyncio.run(node.process(ctx))

    assert result is ctx
    stored = node.get_output(GeneratePlanNode)
    assert isinstance(stored, WeeklyPlanLLMOutput)
    assert ctx.nodes[node.node_name] is stored
    # The typed output carries the slim picks the model emitted.
    assert {p.card for p in stored.core} == {WorkoutCard.vo2, WorkoutCard.strength_pull}


def test_weekly_agent_module_has_no_route_or_db_or_other_node_import():
    import re
    from pathlib import Path

    import app.core.weekly_agent as weekly_agent_mod

    source = Path(weekly_agent_mod.__file__).read_text()
    forbidden = re.compile(
        r"fastapi|APIRouter|Depends|langfuse|observe|DeriveSessionsNode|"
        r"ComputeTargetsNode|ComputeNutritionNode|Workflow\(|TuneSessionNode|"
        r"select\(|Session\("
    )
    assert not forbidden.search(source), "pure-core boundary breached in weekly_agent.py"


# --------------------------------------------------------------------------- #
# TASK-003 — wired validate_weekly output validator (ModelRetry on hard violation)
# --------------------------------------------------------------------------- #


def _three_hard_days_args() -> dict:
    """A budget-violating plan: 3 hard cards against budgets.hard_days = 2."""
    return {
        "core": [
            {"card": "vo2", "suggestedDay": "mon", "durationMinLow": 30, "durationMinHigh": 40},
            {"card": "threshold", "suggestedDay": "wed", "durationMinLow": 30, "durationMinHigh": 45},
            {"card": "boxing", "suggestedDay": "fri", "durationMinLow": 60, "durationMinHigh": 90},
        ],
        "extras": [
            {"card": "strength_pull", "suggestedDay": "sun", "durationMinLow": 30, "durationMinHigh": 45},
        ],
        "narrative": [{"type": "plan", "heading": "W", "body": "Three hard days."}],
    }


def _wrong_count_args() -> dict:
    """A wrong-count plan: 1 core (< 2) — a judgment miss, not a 422."""
    return {
        "core": [
            {"card": "vo2", "suggestedDay": "tue", "durationMinLow": 30, "durationMinHigh": 40},
        ],
        "extras": [
            {"card": "strength_pull", "suggestedDay": "mon", "durationMinLow": 30, "durationMinHigh": 45},
            {"card": "strength_lower", "suggestedDay": "thu", "durationMinLow": 30, "durationMinHigh": 35},
        ],
        "narrative": [{"type": "plan", "heading": "W", "body": "Only one core."}],
    }


def _caution_narrative_args() -> dict:
    """A clean plan whose narrative carries an out-of-subset `caution` section."""
    args = _valid_plan_args()
    args["narrative"] = [
        {"type": "plan", "heading": "Week", "body": "One quality day."},
        {"type": "caution", "heading": "Careful", "body": "Knee is amber."},
    ]
    return args


def test_get_validate_fn_returns_a_callable():
    from app.core.weekly_agent import GeneratePlanNode

    fn = GeneratePlanNode().get_validate_fn()
    assert fn is not None
    assert callable(fn)


def test_validate_fn_calls_validate_weekly_and_reads_deps():
    """The wired validator builds a ValidationContext from the deps and runs the
    pure validate_weekly — a 3-hard-day plan against the deps budget is flagged."""
    from app.core.agent_node import _deps_to_validation_context
    from app.core.constraints import Severity
    from app.core.weekly_agent import GeneratePlanNode

    node = GeneratePlanNode()
    fn = node.get_validate_fn()
    out = WeeklyPlanLLMOutput.model_validate(_three_hard_days_args())
    deps = node.build_deps(_ctx_with_feeds_only())
    vctx = _deps_to_validation_context(deps)

    violations = fn(out, vctx)
    rules = {v.rule for v in violations if v.severity is Severity.hard}
    # The hard-day count rule fired against the deps-fixture budget (hard_days=2).
    assert "hard_day_count" in rules


def _ctx_with_feeds_only() -> TaskContext:
    return TaskContext(event=None, metadata={"computed": _feeds()})


def test_validate_fn_flags_out_of_subset_narrative_section():
    """A weekly `caution`/`summary` section is a hard violation (LLM §1 subset)."""
    from app.core.agent_node import _deps_to_validation_context
    from app.core.constraints import Severity
    from app.core.weekly_agent import GeneratePlanNode

    node = GeneratePlanNode()
    fn = node.get_validate_fn()
    out = WeeklyPlanLLMOutput.model_validate(_caution_narrative_args())
    vctx = _deps_to_validation_context(node.build_deps(_ctx_with_feeds_only()))

    violations = fn(out, vctx)
    assert any(v.severity is Severity.hard for v in violations)
    # And the plan|session|nutrition-only valid plan has no narrative-subset hard.
    clean = WeeklyPlanLLMOutput.model_validate(_valid_plan_args())
    assert fn(clean, vctx) == []


def test_clean_plan_passes_validator_and_is_stored(_no_anthropic_key, monkeypatch, _profile):
    from app.core.weekly_agent import GeneratePlanNode

    model, _calls = _function_model_returning(_valid_plan_args())
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile)
    node = GeneratePlanNode(task_context=ctx)
    asyncio.run(node.process(ctx))

    stored = node.get_output(GeneratePlanNode)
    assert isinstance(stored, WeeklyPlanLLMOutput)


def test_budget_violating_plan_retries_then_brief_generation_failed(
    _no_anthropic_key, monkeypatch, _profile
):
    from app.core.agent_node import BriefGenerationError
    from app.core.weekly_agent import GeneratePlanNode

    # A model that PERSISTENTLY emits 3 hard days against budgets.hard_days = 2.
    model, calls = _function_model_returning(_three_hard_days_args())
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile, hard_days=2)
    node = GeneratePlanNode(task_context=ctx)

    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))

    # The wired validator ModelRetry'd; exhausting retries=2 → brief_generation_failed.
    assert excinfo.value.code == "brief_generation_failed"
    assert calls["n"] >= 2  # initial + at least one retry => the ModelRetry fired
    assert calls["n"] <= 3  # retries <= 2
    # No output reached the cache (LLM §4 — a violating plan never persists).
    assert node.node_name not in ctx.nodes


def test_wrong_count_plan_retries_not_422(_no_anthropic_key, monkeypatch, _profile):
    from app.core.agent_node import BriefGenerationError
    from app.core.weekly_agent import GeneratePlanNode

    model, calls = _function_model_returning(_wrong_count_args())
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile)
    node = GeneratePlanNode(task_context=ctx)

    # A wrong count is a ModelRetry (a judgment miss), surfacing as
    # brief_generation_failed on exhaustion — NOT a Pydantic ValidationError/422.
    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))
    assert excinfo.value.code == "brief_generation_failed"
    assert calls["n"] >= 2  # the ModelRetry fired (not parsed-and-failed once)
    assert node.node_name not in ctx.nodes


def test_caution_narrative_section_retries(_no_anthropic_key, monkeypatch, _profile):
    from app.core.agent_node import BriefGenerationError
    from app.core.weekly_agent import GeneratePlanNode

    model, calls = _function_model_returning(_caution_narrative_args())
    _patch_build_agent(monkeypatch, model)

    ctx = _ctx_with(_profile)
    node = GeneratePlanNode(task_context=ctx)

    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))
    assert excinfo.value.code == "brief_generation_failed"
    assert calls["n"] >= 2  # the narrative-subset ModelRetry fired
    assert node.node_name not in ctx.nodes


def test_validator_reads_threaded_deps_budget(_no_anthropic_key, monkeypatch, _profile):
    """The deps-fixture budget is the one the violation references — proving the
    validator read the deps threaded through RunContext (not a default)."""
    from app.core.agent_node import _deps_to_validation_context
    from app.core.weekly_agent import GeneratePlanNode

    # hard_days = 4 in the deps → a 3-hard-day plan is now WITHIN budget (no
    # hard_day_count violation), proving the validator read the fixture's budget.
    node = GeneratePlanNode()
    deps = node.build_deps(_ctx_with_feeds_only_hard_days(4))
    vctx = _deps_to_validation_context(deps)
    out = WeeklyPlanLLMOutput.model_validate(_three_hard_days_args())
    rules = {v.rule for v in node.get_validate_fn()(out, vctx)}
    assert "hard_day_count" not in rules
    # The deps carry the budget as a real WeeklyBudgets and the quality pick as an enum.
    assert vctx.budgets.hard_days == 4
    assert vctx.quality_run_pick is WorkoutCard.vo2


def _ctx_with_feeds_only_hard_days(hard_days: int) -> TaskContext:
    return TaskContext(event=None, metadata={"computed": _feeds(hard_days=hard_days)})


def test_deps_carry_budgets_and_quality_pick_as_enum():
    """The deps contract: budgets is a WeeklyBudgets, quality_run_pick a WorkoutCard."""
    from app.core.constraints import WeeklyBudgets
    from app.core.weekly_agent import GeneratePlanNode

    deps = GeneratePlanNode().build_deps(_ctx_with_feeds_only())
    assert isinstance(deps.budgets, WeeklyBudgets)
    assert deps.budgets.hard_days == 2
    assert deps.quality_run_pick is WorkoutCard.vo2


def test_quality_run_pick_reads_value_across_enum_flavors():
    """`_quality_run_pick` maps the quality_focus cue to a WorkoutCard regardless of
    enum flavour — a plain string, the StrEnum `next_quality_focus` output, AND a
    `str, Enum` member (the latter is the review fix: `str(member)` would yield
    "ClassName.member" and silently skip the threshold↔VO₂ check)."""
    from app.services.recompute import QualityFocus
    from app.core.weekly_agent import GeneratePlanNode

    qp = GeneratePlanNode._quality_run_pick
    assert qp({"quality_focus": "vo2"}) is WorkoutCard.vo2
    assert qp({"quality_focus": "threshold"}) is WorkoutCard.threshold
    assert qp({"quality_focus": QualityFocus.VO2}) is WorkoutCard.vo2  # StrEnum
    assert qp({"quality_focus": WorkoutCard.threshold}) is WorkoutCard.threshold  # str,Enum
    assert qp({"quality_focus": None}) is None
    assert qp({"quality_focus": "easy_run"}) is None  # not a quality card
