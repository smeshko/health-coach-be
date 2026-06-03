"""Workflow runner + validator tests (E1·P3 TASK-004)."""

import asyncio

import pytest
from pydantic import BaseModel

from app.core import (
    BaseRouter,
    Node,
    NodeConfig,
    RouterNode,
    TaskContext,
    Workflow,
    WorkflowSchema,
    WorkflowValidator,
)


class _Event(BaseModel):
    direction: str = "left"


class _Out(BaseModel):
    name: str


# --- Node test doubles -------------------------------------------------------


class _A(Node):
    async def process(self, task_context):
        self.save_output(_Out(name="A"))
        return task_context


class _B(Node):
    async def process(self, task_context):
        task_context.metadata["b_saw_a"] = self.get_output(_A) is not None
        self.save_output(_Out(name="B"))
        return task_context


class _Start(Node):
    async def process(self, task_context):
        self.save_output(_Out(name="Start"))
        return task_context


class _LeftTerm(Node):
    async def process(self, task_context):
        self.save_output(_Out(name="Left"))
        return task_context


class _RightTerm(Node):
    async def process(self, task_context):
        self.save_output(_Out(name="Right"))
        return task_context


class _DirPredicate(RouterNode):
    def determine_next_node(self, task_context):
        return _LeftTerm() if task_context.event.direction == "left" else _RightTerm()


class _DirRouter(BaseRouter):
    routes = [_DirPredicate]
    fallback = None


# --- Workflows ---------------------------------------------------------------


class _LinearWF(Workflow):
    workflow_schema = WorkflowSchema(
        event_schema=_Event,
        start=_A,
        nodes=[NodeConfig(node=_A, connections=[_B]), NodeConfig(node=_B)],
    )


class _BranchWF(Workflow):
    workflow_schema = WorkflowSchema(
        event_schema=_Event,
        start=_Start,
        nodes=[
            NodeConfig(node=_Start, connections=[_DirRouter]),
            NodeConfig(node=_DirRouter, connections=[_LeftTerm, _RightTerm], is_router=True),
            NodeConfig(node=_LeftTerm),
            NodeConfig(node=_RightTerm),
        ],
    )


def test_linear_runs_end_to_end():
    ctx = _LinearWF().run(event={"direction": "left"})
    assert ctx.nodes["_A"].name == "A"
    assert ctx.nodes["_B"].name == "B"
    assert ctx.metadata["b_saw_a"] is True  # B saw A's output over one shared context


def test_router_branch_left():
    ctx = _BranchWF().run(event={"direction": "left"})
    assert "_LeftTerm" in ctx.nodes
    assert "_RightTerm" not in ctx.nodes


def test_router_branch_right():
    ctx = _BranchWF().run(event={"direction": "right"})
    assert "_RightTerm" in ctx.nodes
    assert "_LeftTerm" not in ctx.nodes


def test_sync_and_async_parity():
    sync_ctx = _BranchWF().run(event={"direction": "left"})
    async_ctx = asyncio.run(_BranchWF().run_async(event={"direction": "left"}))
    assert set(sync_ctx.nodes) == set(async_ctx.nodes)
    assert "_LeftTerm" in async_ctx.nodes


# --- Gated short-circuit (terminal-then-stop) --------------------------------


class _GateRest(Node):
    async def process(self, task_context):
        self.save_output(_Out(name="REST"))  # write the gated brief...
        task_context.stop_workflow()  # ...then stop
        return task_context


class _Downstream(Node):  # AgentNode stand-in that must be skipped
    async def process(self, task_context):
        self.save_output(_Out(name="DOWNSTREAM"))
        return task_context


class _GatePredicate(RouterNode):
    def determine_next_node(self, task_context):
        return _GateRest()


class _GateRouter(BaseRouter):
    routes = [_GatePredicate]
    fallback = None


class _GatedWF(Workflow):
    workflow_schema = WorkflowSchema(
        event_schema=_Event,
        start=_GateRouter,
        nodes=[
            NodeConfig(node=_GateRouter, connections=[_GateRest], is_router=True),
            NodeConfig(node=_GateRest, connections=[_Downstream]),
            NodeConfig(node=_Downstream),
        ],
    )


def test_gated_short_circuit_runs_terminal_then_stops():
    ctx = _GatedWF().run(event={"direction": "left"})
    assert ctx.nodes["_GateRest"].name == "REST"  # terminal ran, brief written
    assert "_Downstream" not in ctx.nodes  # downstream sentinel skipped
    assert ctx.should_stop is True


# --- Router DAG-constraint ---------------------------------------------------


class _OffDagPredicate(RouterNode):
    def determine_next_node(self, task_context):
        return _RightTerm()  # not a declared connection


class _OffDagRouter(BaseRouter):
    routes = [_OffDagPredicate]
    fallback = None


class _OffDagWF(Workflow):
    workflow_schema = WorkflowSchema(
        event_schema=_Event,
        start=_OffDagRouter,
        nodes=[
            NodeConfig(node=_OffDagRouter, connections=[_LeftTerm], is_router=True),
            NodeConfig(node=_LeftTerm),
        ],
    )


class _NeverMatch(RouterNode):
    def determine_next_node(self, task_context):
        return None


class _BadFallbackRouter(BaseRouter):
    routes = [_NeverMatch]
    fallback = _RightTerm  # fallback class is not a declared connection


class _BadFallbackWF(Workflow):
    workflow_schema = WorkflowSchema(
        event_schema=_Event,
        start=_BadFallbackRouter,
        nodes=[
            NodeConfig(node=_BadFallbackRouter, connections=[_LeftTerm], is_router=True),
            NodeConfig(node=_LeftTerm),
        ],
    )


def test_router_undeclared_route_raises():
    with pytest.raises(ValueError, match="not a declared connection"):
        _OffDagWF().run(event={"direction": "left"})


def test_router_undeclared_fallback_raises():
    with pytest.raises(ValueError, match="not a declared connection"):
        _BadFallbackWF().run(event={"direction": "left"})


# --- Nested-context restoration on failure -----------------------------------


class _Boom(Node):
    async def process(self, task_context):
        raise RuntimeError("boom")


class _BoomWF(Workflow):
    workflow_schema = WorkflowSchema(
        event_schema=_Event, start=_Boom, nodes=[NodeConfig(node=_Boom)]
    )


def test_parent_registry_restored_when_a_node_raises():
    # A child run that raises must restore the parent's metadata["nodes"], not leave it
    # pointing at the child's registry (review round-1 #3).
    sentinel = object()
    parent = TaskContext(event=None, metadata={"nodes": sentinel})
    with pytest.raises(RuntimeError, match="boom"):
        _BoomWF().run(context=parent)
    assert parent.metadata["nodes"] is sentinel


# --- Validator accept / reject ----------------------------------------------


def test_validator_accepts_linear_and_router_fanout():
    WorkflowValidator(_LinearWF.workflow_schema).validate()
    WorkflowValidator(_BranchWF.workflow_schema).validate()


def test_validator_rejects_cycle():
    schema = WorkflowSchema(
        event_schema=_Event,
        start=_A,
        nodes=[NodeConfig(node=_A, connections=[_B]), NodeConfig(node=_B, connections=[_A])],
    )
    with pytest.raises(ValueError, match="cycle"):
        WorkflowValidator(schema).validate()


def test_validator_rejects_unreachable():
    schema = WorkflowSchema(
        event_schema=_Event,
        start=_A,
        nodes=[NodeConfig(node=_A), NodeConfig(node=_B)],
    )
    with pytest.raises(ValueError, match="Unreachable"):
        WorkflowValidator(schema).validate()


def test_validator_rejects_nonrouter_fanout():
    schema = WorkflowSchema(
        event_schema=_Event,
        start=_A,
        nodes=[
            NodeConfig(node=_A, connections=[_LeftTerm, _RightTerm]),
            NodeConfig(node=_LeftTerm),
            NodeConfig(node=_RightTerm),
        ],
    )
    with pytest.raises(ValueError, match="not marked as a router"):
        WorkflowValidator(schema).validate()


def test_validator_rejects_duplicate_node_configs():
    # A duplicate could make validation and execution see different graphs
    # (validator first-match vs runtime last-write) — review round-1 #2.
    schema = WorkflowSchema(
        event_schema=_Event,
        start=_A,
        nodes=[
            NodeConfig(node=_A, connections=[_B]),
            NodeConfig(node=_B),
            NodeConfig(node=_A, connections=[_A]),  # duplicate, sneaks in a self-loop
        ],
    )
    with pytest.raises(ValueError, match="Duplicate node configs"):
        WorkflowValidator(schema).validate()


def test_validator_rejects_is_router_on_non_baserouter():
    schema = WorkflowSchema(
        event_schema=_Event,
        start=_A,
        nodes=[NodeConfig(node=_A, connections=[_B], is_router=True), NodeConfig(node=_B)],
    )
    with pytest.raises(ValueError, match="not a BaseRouter"):
        WorkflowValidator(schema).validate()
