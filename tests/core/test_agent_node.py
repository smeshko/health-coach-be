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
