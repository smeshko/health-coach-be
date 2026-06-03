"""Node / RouterNode / BaseRouter unit tests (E1·P3 TASK-002)."""

import asyncio

import pytest
from pydantic import BaseModel

from app.core import BaseRouter, Node, RouterNode, TaskContext


class _Out(BaseModel):
    value: int


class _SaveNode(Node):
    async def process(self, task_context: TaskContext) -> TaskContext:
        self.save_output(_Out(value=42))
        return task_context


class _StopNode(Node):
    async def process(self, task_context: TaskContext) -> TaskContext:
        task_context.stop_workflow()
        return task_context


class _Left(Node):
    async def process(self, task_context: TaskContext) -> TaskContext:
        return task_context


class _Right(Node):
    async def process(self, task_context: TaskContext) -> TaskContext:
        return task_context


class _GoLeftWhenFlagged(RouterNode):
    def determine_next_node(self, task_context: TaskContext) -> Node | None:
        return _Left() if task_context.metadata.get("go") == "left" else None


class _FlagRouter(BaseRouter):
    routes = [_GoLeftWhenFlagged]
    fallback = _Right


class _NoFallbackRouter(BaseRouter):
    routes = [_GoLeftWhenFlagged]
    fallback = None


def test_node_is_abstract():
    with pytest.raises(TypeError):
        Node()


def test_router_node_is_abstract():
    with pytest.raises(TypeError):
        RouterNode()


def test_concrete_node_saves_and_gets_output():
    ctx = TaskContext(event=None)
    node = _SaveNode(task_context=ctx)
    result = asyncio.run(node.process(ctx))
    assert result is ctx
    assert node.get_output(_SaveNode) == _Out(value=42)
    assert node.get_output(_Right) is None  # missing -> None


def test_router_selects_by_context():
    ctx = TaskContext(event=None, metadata={"go": "left"})
    # route() returns the next node CLASS (predicates are instantiated fresh).
    assert _FlagRouter().route(ctx) is _Left


def test_router_falls_back_when_no_route_matches():
    ctx = TaskContext(event=None, metadata={})
    assert _FlagRouter().route(ctx) is _Right


def test_router_returns_none_without_fallback():
    ctx = TaskContext(event=None, metadata={})
    assert _NoFallbackRouter().route(ctx) is None


def test_router_predicates_are_isolated_per_evaluation():
    # Two routings with different contexts must not bleed state through a shared
    # predicate instance (data isolation — review round-1 #1).
    left = _FlagRouter().route(TaskContext(event=None, metadata={"go": "left"}))
    right = _FlagRouter().route(TaskContext(event=None, metadata={"go": "stay"}))
    assert left is _Left
    assert right is _Right


def test_node_process_can_set_stop_flag():
    # A plain Node.process may set the flag (the terminal-then-stop pattern lives
    # at the runner level, TASK-004); the router itself never stops.
    ctx = TaskContext(event=None)
    asyncio.run(_StopNode(task_context=ctx).process(ctx))
    assert ctx.should_stop is True
