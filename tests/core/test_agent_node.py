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
