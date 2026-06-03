"""AgentNode abstract-placeholder tests (E1·P3 TASK-003)."""

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
