"""AgentNode tests — the E1·P3 abstract placeholder and the E9·P1 PydanticAI wrapper.

The E1 cases pin the abstract `AgentNode` seam (`nodes.py`, unedited by E9·P1). The
E9·P1 cases (`build_agent` / `PydanticAgentNode`) exercise the wrapper with the model
**mocked** — `TestModel`/`FunctionModel` via `Agent.override(model=…)` — so no live
Anthropic call, no network, and no `ANTHROPIC_API_KEY` is ever made (epic §4/§6).
"""

import asyncio

import pytest
from pydantic import BaseModel

from app.core import AgentConfig, AgentNode, TaskContext


class _StubAgent(AgentNode):
    class OutputType(BaseModel):
        card: str

    def get_agent_config(self) -> AgentConfig:
        return AgentConfig(model_id="claude-opus-4-8", output_type=self.OutputType)

    async def process(self, task_context: TaskContext) -> TaskContext:
        self.save_output(self.OutputType(card="push"))
        return task_context


def test_agent_node_is_abstract():
    with pytest.raises(TypeError):
        AgentNode()


def test_concrete_agent_runs_without_provider():
    ctx = TaskContext(event=None)
    node = _StubAgent(task_context=ctx)
    result = asyncio.run(node.process(ctx))
    assert result is ctx
    assert node.get_output(_StubAgent).card == "push"
    cfg = node.get_agent_config()
    assert isinstance(cfg, AgentConfig)
    assert cfg.model_id == "claude-opus-4-8"


def test_agent_node_exposes_output_and_deps_seams():
    assert issubclass(_StubAgent.OutputType, BaseModel)
    assert issubclass(AgentNode.DepsType, BaseModel)


def test_importable_from_app_core():
    from app.core import AgentConfig as AC
    from app.core import AgentNode as AN

    assert AC is AgentConfig and AN is AgentNode


# --------------------------------------------------------------------------- #
# E9·P1 — build_agent (TASK-001): PydanticAI Agent construction + LLM §2 settings
# --------------------------------------------------------------------------- #


class _ToyOut(BaseModel):
    """A 2-field toy OutputType standing in for E7's concrete `*LLMOutput`."""

    pick: str
    note: str


class _ToyDeps(BaseModel):
    """A toy RunContext deps type (the E9·P2 validator seam)."""


@pytest.fixture
def _no_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no Anthropic key is present, proving construction is key-free."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _build_toy_agent():
    from app.core.agent_node import build_agent

    return build_agent(
        AgentConfig(model_id="claude-opus-4-8", output_type=_ToyOut),
        system_prompt="<rendered constitution>",
        deps_type=_ToyDeps,
    )


def test_build_agent_targets_claude_opus(_no_anthropic_key):
    agent = _build_toy_agent()
    # The deferred string model makes `agent.model` the str "anthropic:claude-opus-4-8".
    assert "claude-opus-4-8" in str(agent.model)


def test_build_agent_model_id_flows_from_config_not_hardcoded(_no_anthropic_key):
    from app.core.agent_node import build_agent

    agent = build_agent(
        AgentConfig(model_id="claude-3-5-sonnet-latest", output_type=_ToyOut),
        system_prompt="sys",
        deps_type=_ToyDeps,
    )
    assert "claude-3-5-sonnet-latest" in str(agent.model)
    assert "claude-opus-4-8" not in str(agent.model)


def test_build_agent_uses_tool_based_structured_output(_no_anthropic_key):
    agent = _build_toy_agent()
    # `ToolOutput(...)` builds a `ToolOutputSchema` (a `final_result` output tool),
    # distinct from `NativeOutputSchema`/`PromptedOutputSchema`. The class lives in
    # the private `pydantic_ai._output`, so the import-free name check is used.
    assert type(agent._output_schema).__name__ == "ToolOutputSchema"


def test_build_agent_temperature_is_low(_no_anthropic_key):
    from app.core.agent_node import LOW_TEMPERATURE

    agent = _build_toy_agent()
    assert agent.model_settings["temperature"] == LOW_TEMPERATURE
    assert LOW_TEMPERATURE <= 0.2


def test_build_agent_sets_request_timeout(_no_anthropic_key):
    from app.core.agent_node import CALL_TIMEOUT_S

    agent = _build_toy_agent()
    assert agent.model_settings["timeout"] == CALL_TIMEOUT_S


def test_build_agent_retries_capped_at_two(_no_anthropic_key):
    from app.core.agent_node import MAX_RETRIES

    assert MAX_RETRIES == 2
    agent = _build_toy_agent()
    # No public `agent.retries`; the budget surfaces as `_max_output_retries`.
    assert agent._max_output_retries == 2


def test_build_agent_constructs_without_api_key(_no_anthropic_key):
    # The deferred string model + defer_model_check=True never instantiates the
    # Anthropic provider, so construction succeeds with no key in the environment.
    import os

    assert "ANTHROPIC_API_KEY" not in os.environ
    agent = _build_toy_agent()
    assert agent is not None


def test_build_agent_passes_system_prompt_as_instructions(_no_anthropic_key):
    from app.core.agent_node import build_agent

    agent = build_agent(
        AgentConfig(model_id="claude-opus-4-8", output_type=_ToyOut),
        system_prompt="THE-FRESH-CONSTITUTION",
        deps_type=_ToyDeps,
    )
    # The rendered constitution is passed fresh as instructions (caching off).
    assert "THE-FRESH-CONSTITUTION" in str(agent._instructions)


# --------------------------------------------------------------------------- #
# E9·P1 — PydanticAgentNode (TASK-002): generic node run + output storage
# --------------------------------------------------------------------------- #


class _OtherOut(BaseModel):
    """A second, differently-shaped toy OutputType for the generic round-trip."""

    label: str
    score: int


def _toy_agent_node_cls(out_type: type[BaseModel], *, run_input_marker: str = "USER-CTX"):
    """Build a concrete `PydanticAgentNode` subclass over `out_type`, model-mocked."""
    from app.core.agent_node import PydanticAgentNode

    class _ToyAgentNode(PydanticAgentNode[_ToyDeps, out_type]):  # type: ignore[valid-type]
        OutputType = out_type
        DepsType = _ToyDeps

        def get_agent_config(self) -> AgentConfig:
            return AgentConfig(model_id="claude-opus-4-8", output_type=out_type)

        def build_system_prompt(self, task_context: TaskContext) -> str:
            return "<rendered constitution>"

        def build_run_input(self, task_context: TaskContext) -> str:
            return run_input_marker

    return _ToyAgentNode


def _patch_build_agent(monkeypatch: pytest.MonkeyPatch, model, *, validator=None) -> None:
    """Drive `process()`'s inner agent with a mock `model` via the official override seam.

    `process()` builds its agent internally, so the test calls the **real** `build_agent`
    (keeping every LLM §2 setting under test) and wraps the agent's `run` so the call
    happens inside `agent.override(model=…)` — PydanticAI's supported in-process test
    seam. Entering the override **inside** the run coroutine keeps its `ContextVar` in the
    run's own event loop. An optional `validator` registers a trivial test-only
    `@agent.output_validator` (standing in for E9·P2's real one) to exercise the
    retry-exhaustion path. No live Anthropic call, no network, no key.
    """
    import app.core.agent_node as agent_node_mod

    real_build = agent_node_mod.build_agent

    def _build_with_mock_model(*args, **kwargs):
        agent = real_build(*args, **kwargs)
        if validator is not None:
            agent.output_validator(validator)
        original_run = agent.run

        async def _run_under_override(*run_args, **run_kwargs):
            with agent.override(model=model):
                return await original_run(*run_args, **run_kwargs)

        agent.run = _run_under_override
        return agent

    monkeypatch.setattr(agent_node_mod, "build_agent", _build_with_mock_model)


def test_pydantic_agent_node_subclasses_e1_agent_node():
    import app.core.nodes as nodes
    from app.core.agent_node import PydanticAgentNode

    assert issubclass(PydanticAgentNode, nodes.AgentNode)


def test_process_runs_agent_and_stores_typed_output(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    from pydantic_ai.models.test import TestModel

    _patch_build_agent(monkeypatch, TestModel())

    node_cls = _toy_agent_node_cls(_ToyOut)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    result = asyncio.run(node.process(ctx))

    assert result is ctx
    stored = node.get_output(node_cls)
    assert isinstance(stored, _ToyOut)
    assert ctx.nodes[node.node_name] is stored


def test_node_is_generic_two_output_types_round_trip(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    from pydantic_ai.models.test import TestModel

    _patch_build_agent(monkeypatch, TestModel())

    # Two different toy OutputTypes each round-trip through the SAME base class.
    node_a_cls = _toy_agent_node_cls(_ToyOut)
    ctx_a = TaskContext(event=None)
    node_a = node_a_cls(task_context=ctx_a)
    asyncio.run(node_a.process(ctx_a))
    assert isinstance(node_a.get_output(node_a_cls), _ToyOut)

    node_b_cls = _toy_agent_node_cls(_OtherOut)
    ctx_b = TaskContext(event=None)
    node_b = node_b_cls(task_context=ctx_b)
    asyncio.run(node_b.process(ctx_b))
    assert isinstance(node_b.get_output(node_b_cls), _OtherOut)


def test_node_runs_under_real_workflow_runner_sync_and_async(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    from pydantic_ai.models.test import TestModel

    from app.core import NodeConfig, Workflow, WorkflowSchema

    _patch_build_agent(monkeypatch, TestModel())

    node_cls = _toy_agent_node_cls(_ToyOut)

    class _Event(BaseModel):
        pass

    class _ToyWorkflow(Workflow):
        workflow_schema = WorkflowSchema(
            event_schema=_Event,
            start=node_cls,
            nodes=[NodeConfig(node=node_cls)],
        )

    # Sync Workflow.run wraps the whole walk in one asyncio.run — no nested loop.
    ctx_sync = _ToyWorkflow().run(event=_Event())
    assert isinstance(ctx_sync.nodes[node_cls.__name__], _ToyOut)

    # run_async on an active loop — no nested-loop RuntimeError.
    async def _drive():
        return await _ToyWorkflow().run_async(event=_Event())

    ctx_async = asyncio.run(_drive())
    assert isinstance(ctx_async.nodes[node_cls.__name__], _ToyOut)


def test_process_reads_build_run_input_seam(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    # The run feeds build_run_input(ctx) as the user message to the agent. Capture it
    # with a FunctionModel that reads the prompt, proving the seam is wired.
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    seen: dict[str, str] = {}

    def _capture(messages, info: AgentInfo) -> ModelResponse:
        for msg in reversed(messages):
            for part in getattr(msg, "parts", []):
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    seen["user"] = content
                    break
            if "user" in seen:
                break
        tool = info.output_tools[0]
        return ModelResponse(
            parts=[ToolCallPart(tool_name=tool.name, args={"pick": "p", "note": "n"})]
        )

    _patch_build_agent(monkeypatch, FunctionModel(_capture))

    node_cls = _toy_agent_node_cls(_ToyOut, run_input_marker="UNIQUE-USER-CONTEXT-123")
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)
    asyncio.run(node.process(ctx))

    assert seen.get("user") == "UNIQUE-USER-CONTEXT-123"


# --------------------------------------------------------------------------- #
# E9·P1 — failure mapping (TASK-003): retry exhaustion / timeout / HTTP → codes
# --------------------------------------------------------------------------- #


def _valid_tool_call_model():
    """A FunctionModel that always calls the output tool with valid args, counting calls."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    calls = {"n": 0}

    def _always_call(messages, info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        tool = info.output_tools[0]
        return ModelResponse(
            parts=[ToolCallPart(tool_name=tool.name, args={"pick": "x", "note": "y"})]
        )

    return FunctionModel(_always_call), calls


def test_exhausted_retries_map_to_brief_generation_failed(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    from pydantic_ai import ModelRetry

    from app.core.agent_node import BriefGenerationError

    model, calls = _valid_tool_call_model()

    # A trivial test-only validator that always rejects, standing in for E9·P2's real
    # @agent.output_validator — it consumes the retries=2 budget then surfaces an error.
    def _always_retry(ctx, output):
        raise ModelRetry("always reject")

    _patch_build_agent(monkeypatch, model, validator=_always_retry)

    node_cls = _toy_agent_node_cls(_ToyOut)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))

    assert excinfo.value.code == "brief_generation_failed"
    # 1 initial + 2 retries = at most 3 model invocations (retries <= 2).
    assert calls["n"] <= 3
    # No synthetic fallback: nothing stored for the node on failure.
    assert node.node_name not in ctx.nodes


def test_timeout_maps_to_upstream_timeout(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from app.core.agent_node import BriefGenerationError

    def _raise_timeout(messages, info: AgentInfo) -> ModelResponse:
        raise TimeoutError("upstream hung")

    _patch_build_agent(monkeypatch, FunctionModel(_raise_timeout))

    node_cls = _toy_agent_node_cls(_ToyOut)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))

    assert excinfo.value.code == "upstream_timeout"
    assert node.node_name not in ctx.nodes


def test_timeout_status_http_error_maps_to_upstream_timeout(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    from pydantic_ai import ModelHTTPError
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from app.core.agent_node import BriefGenerationError

    def _raise_504(messages, info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(status_code=504, model_name="m", body="gateway timeout")

    _patch_build_agent(monkeypatch, FunctionModel(_raise_504))

    node_cls = _toy_agent_node_cls(_ToyOut)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))

    assert excinfo.value.code == "upstream_timeout"


def test_model_http_error_maps_to_brief_generation_failed_with_cause(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    from pydantic_ai import ModelHTTPError
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from app.core.agent_node import BriefGenerationError

    def _raise_500(messages, info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(status_code=500, model_name="m", body="boom")

    _patch_build_agent(monkeypatch, FunctionModel(_raise_500))

    node_cls = _toy_agent_node_cls(_ToyOut)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))

    assert excinfo.value.code == "brief_generation_failed"
    # The original cause is chained for the (E12) trace.
    assert isinstance(excinfo.value.__cause__, ModelHTTPError)
    assert node.node_name not in ctx.nodes


def test_failure_never_fabricates_a_synthetic_output(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from app.core.agent_node import BriefGenerationError

    def _raise_timeout(messages, info: AgentInfo) -> ModelResponse:
        raise TimeoutError("hung")

    _patch_build_agent(monkeypatch, FunctionModel(_raise_timeout))

    node_cls = _toy_agent_node_cls(_ToyOut)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    # Every failing run raises (never returns a fabricated OutputType) and stores nothing.
    with pytest.raises(BriefGenerationError):
        asyncio.run(node.process(ctx))
    assert ctx.nodes == {}
    assert node.get_output(node_cls) is None


def test_brief_generation_error_codes_are_stable_and_http_free():
    from app.core.agent_node import BriefGenerationError

    err = BriefGenerationError(code="brief_generation_failed", message="m", detail="d")
    assert err.code in {"brief_generation_failed", "upstream_timeout"}
    assert err.message == "m"
    assert err.detail == "d"
    # The in-engine error has no FastAPI/HTTP dependency.
    assert issubclass(BriefGenerationError, Exception)


def test_no_synthetic_fallback_return_inside_except():
    """A grep guard: no `return <OutputType>` sits inside an `except` in the module."""
    import re
    from pathlib import Path

    import app.core.agent_node as agent_node_mod

    source = Path(agent_node_mod.__file__).read_text()
    # No `return` statement anywhere inside an except block (every failure path raises).
    in_except = False
    except_indent = 0
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if in_except and indent <= except_indent and not stripped.startswith(("raise", "except")):
            in_except = False
        if re.match(r"except\b", stripped):
            in_except = True
            except_indent = indent
            continue
        if in_except and indent > except_indent:
            assert not stripped.startswith("return "), (
                f"synthetic fallback return inside except: {stripped!r}"
            )


# --- Review #1: the COMMON Anthropic timeout shape maps to upstream_timeout ---


def test_wrapped_anthropic_timeout_maps_to_upstream_timeout(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    # The real provider timeout: the Anthropic SDK raises APITimeoutError (a subclass of
    # APIConnectionError — NOT httpx.TimeoutException, NOT a status error), which PydanticAI
    # re-wraps into a ModelAPIError (an AgentRunError, no status_code). The timeout only
    # survives on the chained __cause__ — _is_timeout must still map it to upstream_timeout
    # (review #1: the bare-TimeoutError FunctionModel stub did not reflect this real path).
    import httpx
    from pydantic_ai import ModelAPIError
    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    import anthropic
    from app.core.agent_node import BriefGenerationError

    def _raise_wrapped_timeout(messages, info: AgentInfo) -> ModelResponse:
        cause = anthropic.APITimeoutError(
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        )
        raise ModelAPIError("m", "request timed out") from cause

    _patch_build_agent(monkeypatch, FunctionModel(_raise_wrapped_timeout))

    node_cls = _toy_agent_node_cls(_ToyOut)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))

    assert excinfo.value.code == "upstream_timeout"
    assert node.node_name not in ctx.nodes


# --- Review #3: lock "Fallback: none" (LLM §2) against a future regression ---


def test_build_agent_has_no_fallback_model(_no_anthropic_key):
    from pydantic_ai.models.fallback import FallbackModel

    agent = _build_toy_agent()
    # The model is a plain deferred string — never wrapped in a FallbackModel (LLM §2
    # "Fallback: none"). A future regression that introduces a fallback wrapper fails here.
    assert not isinstance(agent.model, FallbackModel)


# --------------------------------------------------------------------------- #
# E9·P2 — context payload builder (TASK-001): SYSTEM = rendered constitution +
# USER = computed-context JSON (readiness/budgets/aggregates/flags/constants).
# Model-mocked; a real `Profile` (from `profile.yaml`) + a known `computed` bundle.
# --------------------------------------------------------------------------- #

# A distinctive live weight that is NOT one of the profile's rendered constants, so
# its presence/absence in the system prompt vs the user context is unambiguous.
_LIVE_WEIGHT_KG = 987.654


@pytest.fixture
def _profile():
    """The real, validated `Profile` loaded from the repo-root `profile.yaml`."""
    from app.core.profile import load_profile

    return load_profile()


def _computed_bundle() -> dict:
    """A per-period computed bundle of KNOWN values (standing in for E6/E8).

    Read structurally by `build_user_context` — every value is a plain, JSON-able
    Python primitive so the builder is exercised without importing any concrete
    E6/E8/`*LLMOutput` type.
    """
    return {
        "live_weight_kg": _LIVE_WEIGHT_KG,
        "readiness": 72,
        "band": "amber",
        "safety_gate": False,
        "aggregates": {
            "training": {"7d_load": 310, "28d_load": 1180},
            "nutrition": {"7d_kcal": 16800, "28d_kcal": 67200},
        },
        "flags": {"knee": 1, "gi": 0},
        "constants": {"activity_factor": 1.5},
        # weekly-only
        "budgets": {"hard_days": 2, "strength_sessions": 2, "long_run_km": 18.0, "deload": False},
        "nutrition_adherence": {"last_week_pct": 0.86},
        # daily-only
        "week_plan": {"cards": ["easy_run", "threshold", "strength_lower"]},
        "macro_focus": {"carbs_g": 420, "protein_g": 150},
        "intake_summary": {"yesterday_kcal": 2400},
    }


def _ctx_with(profile, computed: dict) -> TaskContext:
    """A `TaskContext` carrying the live `Profile` + computed bundle on `metadata`."""
    return TaskContext(
        event=None, metadata={"profile": profile, "computed": computed}
    )


_COMMON_USER_FIELDS = (
    "constitution_version",
    "live_weight_kg",
    "readiness",
    "band",
    "safetyGate",
    "aggregates",
    "flags",
    "constants",
)


def test_build_user_context_common_fields_present_both_modes(_profile):
    from app.core.agent_node import build_user_context

    for mode in ("weekly", "daily"):
        ctx = build_user_context(_profile, computed=_computed_bundle(), mode=mode)
        for field in _COMMON_USER_FIELDS:
            assert field in ctx, f"{field!r} missing in mode={mode}"
        # The aggregates carry BOTH training and nutrition intake (LLM §2).
        assert "training" in ctx["aggregates"]
        assert "nutrition" in ctx["aggregates"]


def test_build_user_context_weekly_adds_budgets_not_weekplan(_profile):
    from app.core.agent_node import build_user_context

    ctx = build_user_context(_profile, computed=_computed_bundle(), mode="weekly")
    assert "budgets" in ctx
    assert ctx["budgets"]["hard_days"] == 2
    assert "weekPlan" not in ctx
    assert "macroFocus" not in ctx


def test_build_user_context_daily_adds_weekplan_and_macrofocus_not_budgets(_profile):
    from app.core.agent_node import build_user_context

    ctx = build_user_context(_profile, computed=_computed_bundle(), mode="daily")
    assert "weekPlan" in ctx
    assert "macroFocus" in ctx
    assert "budgets" not in ctx


def test_build_user_context_stamps_constitution_version(_profile):
    from app.core.agent_node import build_user_context
    from app.core.constitution import constitution_version

    ctx = build_user_context(_profile, computed=_computed_bundle(), mode="weekly")
    assert ctx["constitution_version"] == constitution_version(_profile)


def test_build_user_context_carries_live_weight(_profile):
    from app.core.agent_node import build_user_context

    ctx = build_user_context(_profile, computed=_computed_bundle(), mode="daily")
    assert ctx["live_weight_kg"] == _LIVE_WEIGHT_KG


def _e9p2_node_cls(mode: str = "weekly", *, out_type: type[BaseModel] = _ToyOut):
    """A concrete `PydanticAgentNode` that uses the REAL E9·P2 context seams.

    Unlike `_toy_agent_node_cls`, this does NOT override `build_system_prompt`/
    `build_run_input` — it exercises the filled seams (reading `Profile`/`computed`
    off the `TaskContext.metadata`).
    """
    from app.core.agent_node import PydanticAgentNode

    class _E9P2Node(PydanticAgentNode[_ToyDeps, out_type]):  # type: ignore[valid-type]
        OutputType = out_type
        DepsType = _ToyDeps

        def get_agent_config(self) -> AgentConfig:
            return AgentConfig(model_id="claude-opus-4-8", output_type=out_type)

    _E9P2Node.mode = mode  # type: ignore[assignment]
    return _E9P2Node


def test_build_system_prompt_is_rendered_constitution_without_live_weight(_profile):
    from app.core.constitution import render_constitution

    node_cls = _e9p2_node_cls()
    ctx = _ctx_with(_profile, _computed_bundle())
    node = node_cls(task_context=ctx)

    prompt = node.build_system_prompt(ctx)
    # SYSTEM == render_constitution(profile) for the live Profile.
    assert prompt == render_constitution(_profile)
    # Live weight is NOT baked into the system prompt (LLM §2).
    assert str(_LIVE_WEIGHT_KG) not in prompt


def test_build_system_prompt_is_rendered_fresh_each_call(_profile, monkeypatch):
    import app.core.agent_node as agent_node_mod

    calls = {"n": 0}
    real_render = agent_node_mod.render_constitution

    def _counting_render(profile):
        calls["n"] += 1
        return real_render(profile)

    monkeypatch.setattr(agent_node_mod, "render_constitution", _counting_render)

    node_cls = _e9p2_node_cls()
    ctx = _ctx_with(_profile, _computed_bundle())
    node = node_cls(task_context=ctx)

    node.build_system_prompt(ctx)
    node.build_system_prompt(ctx)
    # No memoization: each call re-renders (caching off, LLM §2/§5).
    assert calls["n"] == 2


def test_build_run_input_is_deterministic_json(_profile):
    import json

    node_cls = _e9p2_node_cls(mode="weekly")
    ctx = _ctx_with(_profile, _computed_bundle())
    node = node_cls(task_context=ctx)

    first = node.build_run_input(ctx)
    second = node.build_run_input(ctx)
    # Stable key order so traces/tests are reproducible (sort_keys=True).
    assert first == second
    parsed = json.loads(first)
    assert parsed["live_weight_kg"] == _LIVE_WEIGHT_KG
    assert parsed["budgets"]["hard_days"] == 2


def test_build_run_input_live_weight_in_user_context_not_system_prompt(_profile):
    import json

    node_cls = _e9p2_node_cls(mode="daily")
    ctx = _ctx_with(_profile, _computed_bundle())
    node = node_cls(task_context=ctx)

    user_msg = json.loads(node.build_run_input(ctx))
    assert user_msg["live_weight_kg"] == _LIVE_WEIGHT_KG
    assert str(_LIVE_WEIGHT_KG) not in node.build_system_prompt(ctx)


def test_build_user_context_serialises_pydantic_and_enum_values(_profile):
    """The builder serialises nested BaseModel/Enum computed values JSON-ably."""
    import json

    from app.core.agent_node import _jsonable, build_user_context
    from app.core.enums import ReadinessBand

    class _ComputedModel(BaseModel):
        live_weight_kg: float = _LIVE_WEIGHT_KG
        band: ReadinessBand = ReadinessBand.amber

    ctx = build_user_context(_profile, computed=_ComputedModel(), mode="weekly")
    # Read structurally off an OBJECT (not a dict) too.
    assert ctx["live_weight_kg"] == _LIVE_WEIGHT_KG
    assert ctx["band"] is ReadinessBand.amber
    # And it round-trips through json.dumps via the _jsonable default.
    dumped = json.dumps(ctx, sort_keys=True, default=_jsonable)
    assert json.loads(dumped)["band"] == "amber"


# --------------------------------------------------------------------------- #
# E9·P2 — @agent.output_validator wiring (TASK-002): RunContext deps ->
# validate_fn -> ModelRetry on a hard Violation. Model-mocked + a FAKE validator
# (no real E7·P3 import for the harness-logic cases; a separate importorskip-
# guarded compatibility test binds the adapter to the REAL E7·P3 symbols).
# --------------------------------------------------------------------------- #


class _ValidatorDeps(BaseModel):
    """A deps shape carrying the computed values the adapter maps to ValidationContext."""

    model_config = {"arbitrary_types_allowed": True}

    budgets: object | None = None
    quality_run_pick: object | None = None
    band: object | None = None
    knee_pain: int | None = None
    week_plan_cards: frozenset | None = None
    safety_gate_triggered: bool | None = None


def _known_validator_deps() -> _ValidatorDeps:
    from app.core.enums import ReadinessBand, WorkoutCard

    return _ValidatorDeps(
        budgets={"hard_days": 2, "strength_sessions": 2, "long_run_km": 18.0, "deload": False},
        quality_run_pick=WorkoutCard.threshold,
        band=ReadinessBand.amber,
        knee_pain=4,
        week_plan_cards=frozenset({WorkoutCard.easy_run, WorkoutCard.threshold}),
        safety_gate_triggered=True,
    )


def _fake_validator(violations: list):
    """A fake `validate_fn(out, ctx) -> list[Violation]` returning a fixed set.

    Records the (output, ctx) it was called with so a test can assert the pure
    function was invoked with the adapted ValidationContext.
    """
    seen: dict = {}

    def _fn(output, ctx):
        seen["output"] = output
        seen["ctx"] = ctx
        return list(violations)

    return _fn, seen


def _hard(rule: str, message: str):
    from app.core.constraints import Severity, Violation

    return Violation(rule=rule, message=message, severity=Severity.hard)


def _soft(rule: str, message: str):
    from app.core.constraints import Severity, Violation

    return Violation(rule=rule, message=message, severity=Severity.soft)


def _validating_node_cls(validate_fn, *, deps_factory=_known_validator_deps):
    """A `PydanticAgentNode` that registers `validate_fn` and builds known deps."""
    from app.core.agent_node import PydanticAgentNode

    class _ValNode(PydanticAgentNode[_ValidatorDeps, _ToyOut]):  # type: ignore[valid-type]
        OutputType = _ToyOut
        DepsType = _ValidatorDeps

        def get_agent_config(self) -> AgentConfig:
            return AgentConfig(model_id="claude-opus-4-8", output_type=_ToyOut)

        def build_system_prompt(self, task_context: TaskContext) -> str:
            return "<rendered constitution>"

        def build_run_input(self, task_context: TaskContext) -> str:
            return "USER-CTX"

        def build_deps(self, task_context: TaskContext) -> _ValidatorDeps:
            return deps_factory()

        def get_validate_fn(self):
            return validate_fn

    return _ValNode


def test_deps_to_validation_context_maps_fields_one_to_one():
    from app.core.agent_node import _deps_to_validation_context
    from app.core.constraints import ValidationContext, WeeklyBudgets
    from app.core.enums import ReadinessBand, WorkoutCard

    deps = _known_validator_deps()
    vctx = _deps_to_validation_context(deps)

    assert isinstance(vctx, ValidationContext)
    assert isinstance(vctx.budgets, WeeklyBudgets)
    assert vctx.budgets.hard_days == 2
    assert vctx.budgets.strength_sessions == 2
    assert vctx.budgets.long_run_km == 18.0
    assert vctx.budgets.deload is False
    assert vctx.quality_run_pick is WorkoutCard.threshold
    assert vctx.band is ReadinessBand.amber
    assert vctx.knee_pain == 4
    assert vctx.week_plan_cards == frozenset({WorkoutCard.easy_run, WorkoutCard.threshold})
    assert vctx.safety_gate_triggered is True


def test_deps_adapter_accepts_real_weeklybudgets_instance():
    from app.core.agent_node import _deps_to_validation_context
    from app.core.constraints import WeeklyBudgets

    budgets = WeeklyBudgets(hard_days=3, strength_sessions=1, long_run_km=None, deload=True)
    deps = _ValidatorDeps(budgets=budgets)
    vctx = _deps_to_validation_context(deps)
    assert vctx.budgets is budgets


def test_deps_adapter_real_symbol_compatibility():
    """Round-1 #2: bind the adapter to the REAL E7·P3 ValidationContext/Severity."""
    constraints = pytest.importorskip("app.core.constraints")
    from app.core.agent_node import _deps_to_validation_context

    vctx = _deps_to_validation_context(_known_validator_deps())
    # The adapter returns a genuine app.core.constraints.ValidationContext.
    assert isinstance(vctx, constraints.ValidationContext)
    # The hard/soft filter keys on the real Severity.hard enum member.
    assert constraints.Severity.hard is constraints.Severity("hard")


def test_hard_violation_raises_model_retry_with_rule_and_message(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    model, calls = _valid_tool_call_model()
    fake_fn, _seen = _fake_validator([_hard("hard_day_count", "3 hard days exceed budget of 2")])

    _patch_build_agent(monkeypatch, model)

    node_cls = _validating_node_cls(fake_fn)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    from app.core.agent_node import BriefGenerationError

    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))
    # Exhausting the retries surfaces brief_generation_failed; the model was re-invoked.
    assert excinfo.value.code == "brief_generation_failed"
    assert calls["n"] >= 2  # initial + at least one retry => the ModelRetry fired


def test_model_retry_message_contains_rule_and_message(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    from app.core.agent_node import make_output_validator
    from pydantic_ai import ModelRetry

    fake_fn, _seen = _fake_validator(
        [_hard("hard_day_count", "3 hard days exceed budget of 2")]
    )
    validator = make_output_validator(fake_fn)

    class _Ctx:
        deps = _known_validator_deps()

    with pytest.raises(ModelRetry) as excinfo:
        asyncio.run(validator(_Ctx(), _ToyOut(pick="p", note="n")))
    msg = str(excinfo.value)
    assert "hard_day_count" in msg
    assert "3 hard days exceed budget of 2" in msg


def test_model_retry_message_joins_all_hard_violations():
    from app.core.agent_node import make_output_validator
    from pydantic_ai import ModelRetry

    fake_fn, _seen = _fake_validator(
        [
            _hard("hard_day_count", "too many hard days"),
            _hard("hard_day_spacing", "tue and wed are adjacent"),
        ]
    )
    validator = make_output_validator(fake_fn)

    class _Ctx:
        deps = _known_validator_deps()

    with pytest.raises(ModelRetry) as excinfo:
        asyncio.run(validator(_Ctx(), _ToyOut(pick="p", note="n")))
    msg = str(excinfo.value)
    assert "hard_day_count" in msg
    assert "hard_day_spacing" in msg


def test_validator_invokes_pure_fn_with_adapted_context():
    from app.core.agent_node import make_output_validator
    from app.core.constraints import ValidationContext

    fake_fn, seen = _fake_validator([])  # clean
    validator = make_output_validator(fake_fn)

    out = _ToyOut(pick="p", note="n")

    class _Ctx:
        deps = _known_validator_deps()

    result = asyncio.run(validator(_Ctx(), out))
    # Clean result is returned unchanged (PydanticAI requires the validated value).
    assert result is out
    # The pure fn was invoked with the model output + the adapted ValidationContext.
    assert seen["output"] is out
    assert isinstance(seen["ctx"], ValidationContext)
    assert seen["ctx"].knee_pain == 4


def test_soft_only_result_is_accepted_and_stored(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    from pydantic_ai.models.test import TestModel

    fake_fn, _seen = _fake_validator([_soft("advisory", "just a heads up")])
    _patch_build_agent(monkeypatch, TestModel())

    node_cls = _validating_node_cls(fake_fn)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    result = asyncio.run(node.process(ctx))
    assert result is ctx
    stored = node.get_output(node_cls)
    assert isinstance(stored, _ToyOut)


def test_empty_result_is_accepted_and_stored(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    from pydantic_ai.models.test import TestModel

    fake_fn, _seen = _fake_validator([])
    _patch_build_agent(monkeypatch, TestModel())

    node_cls = _validating_node_cls(fake_fn)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    asyncio.run(node.process(ctx))
    assert isinstance(node.get_output(node_cls), _ToyOut)


def test_make_output_validator_is_brief_agnostic_two_fakes():
    """The SAME factory wraps two different fake validators, each behaving per its fake."""
    from app.core.agent_node import make_output_validator
    from pydantic_ai import ModelRetry

    class _Ctx:
        deps = _known_validator_deps()

    out = _ToyOut(pick="p", note="n")

    # Validator A: a hard violation -> retries.
    fn_a, _ = _fake_validator([_hard("rule_a", "broke a")])
    val_a = make_output_validator(fn_a)
    with pytest.raises(ModelRetry):
        asyncio.run(val_a(_Ctx(), out))

    # Validator B: empty -> accepts.
    fn_b, _ = _fake_validator([])
    val_b = make_output_validator(fn_b)
    assert asyncio.run(val_b(_Ctx(), out)) is out


# --------------------------------------------------------------------------- #
# E9·P2 — exhausted retries -> brief_generation_failed + belt-and-suspenders
# re-check before persist (TASK-003). Model-mocked + fake validators.
# --------------------------------------------------------------------------- #


def _flipping_validator(per_call: list):
    """A fake validator returning `per_call[i]` on its i-th call (last entry sticks).

    Lets a test pass the output-validator DURING the run (early calls clean) but
    report a hard Violation at the pre-persist re-check (a later call), simulating
    an LLM slip / a final adapter mismatch.
    """
    state = {"i": 0}

    def _fn(output, ctx):
        i = min(state["i"], len(per_call) - 1)
        state["i"] += 1
        return list(per_call[i])

    return _fn, state


def test_exhausted_retries_map_to_brief_generation_failed_via_validator(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    """An always-hard validator exhausts retries=2 -> brief_generation_failed, ≤3 calls."""
    from app.core.agent_node import BriefGenerationError

    model, calls = _valid_tool_call_model()
    fake_fn, _seen = _fake_validator([_hard("hard_day_count", "always broken")])
    _patch_build_agent(monkeypatch, model)

    node_cls = _validating_node_cls(fake_fn)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))

    assert excinfo.value.code == "brief_generation_failed"
    # 1 initial + 2 retries = at most 3 model invocations (retries <= 2).
    assert calls["n"] <= 3
    # Nothing persisted on failure.
    assert node.node_name not in ctx.nodes


def test_recheck_catches_a_slip_and_persists_nothing(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    """Clean DURING the run, hard at re-check -> error, nothing stored, model not re-run."""
    from pydantic_ai.models.test import TestModel

    from app.core.agent_node import BriefGenerationError

    # 1st call (output-validator during the run) -> clean; 2nd call (the re-check) -> hard.
    fake_fn, state = _flipping_validator(
        [[], [_hard("knee_impact_blocked", "slipped an impact card past")]]
    )
    _patch_build_agent(monkeypatch, TestModel())

    node_cls = _validating_node_cls(fake_fn)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    with pytest.raises(BriefGenerationError) as excinfo:
        asyncio.run(node.process(ctx))

    assert excinfo.value.code == "brief_generation_failed"
    # The brief never reached the cache (nothing persisted) — LLM §4.
    assert node.node_name not in ctx.nodes
    # The validator ran exactly twice: once in the run, once in the re-check.
    assert state["i"] == 2


def test_recheck_does_not_reinvoke_the_model(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    """The re-check is deterministic + LLM-free: it does not call the model again."""
    from app.core.agent_node import BriefGenerationError

    model, calls = _valid_tool_call_model()
    # Clean during the run, hard at the re-check.
    fake_fn, _state = _flipping_validator(
        [[], [_hard("day_type_below_floor", "under-fuelled")]]
    )
    _patch_build_agent(monkeypatch, model)

    node_cls = _validating_node_cls(fake_fn)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    with pytest.raises(BriefGenerationError):
        asyncio.run(node.process(ctx))

    # The model was invoked exactly ONCE (the clean run); the re-check added no call.
    assert calls["n"] == 1


def test_fully_clean_run_persists_the_output(
    _no_anthropic_key, monkeypatch: pytest.MonkeyPatch
):
    """Clean during the run AND at the re-check -> the output is stored (happy path)."""
    from pydantic_ai.models.test import TestModel

    fake_fn, _seen = _fake_validator([])  # always clean
    _patch_build_agent(monkeypatch, TestModel())

    node_cls = _validating_node_cls(fake_fn)
    ctx = TaskContext(event=None)
    node = node_cls(task_context=ctx)

    result = asyncio.run(node.process(ctx))
    assert result is ctx
    stored = node.get_output(node_cls)
    assert isinstance(stored, _ToyOut)
    assert ctx.nodes[node.node_name] is stored


def test_recheck_output_helper_raises_on_hard_without_model():
    """The re-check helper, called directly: hard -> BriefGenerationError; clean -> None."""
    from app.core.agent_node import (
        BriefGenerationError,
        _deps_to_validation_context,
        recheck_output,
    )

    vctx = _deps_to_validation_context(_known_validator_deps())
    out = _ToyOut(pick="p", note="n")

    clean_fn, _ = _fake_validator([])
    assert recheck_output(out, clean_fn, vctx) is None

    hard_fn, _ = _fake_validator([_hard("hard_day_count", "broken")])
    with pytest.raises(BriefGenerationError) as excinfo:
        recheck_output(out, hard_fn, vctx)
    assert excinfo.value.code == "brief_generation_failed"

    # A soft-only re-check result does NOT error (advisory).
    soft_fn, _ = _fake_validator([_soft("advisory", "fyi")])
    assert recheck_output(out, soft_fn, vctx) is None


def test_module_introduces_no_new_error_code_literal():
    """A grep guard: the only error-code literals are the two reused MODELS codes."""
    import re
    from pathlib import Path

    import app.core.agent_node as agent_node_mod

    source = Path(agent_node_mod.__file__).read_text()
    # Every quoted code literal in the module must be one of the closed ErrorCode set.
    found = set(re.findall(r'"(brief_generation_failed|upstream_timeout)"', source))
    assert found <= {"brief_generation_failed", "upstream_timeout"}
    # And both are members of the closed ErrorCode enum.
    from app.api.errors import ErrorCode

    for code in found:
        assert ErrorCode(code) in ErrorCode
