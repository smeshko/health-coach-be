"""Workflow schema, DAG validator, and runner (E1·P3 TASK-004).

A `Workflow` walks a validated DAG of nodes over a single shared `TaskContext`.
Non-router nodes run their `async process()`; router edges resolve via
`BaseRouter.route()`. The runner checks `should_stop` at the **top** of each
iteration, so a routed-to terminal override node runs its `process()` (writing its
brief) and calls `ctx.stop_workflow()` itself — the loop then breaks before the
next node (the §2 safety-gate "terminal-then-stop" short-circuit; ARCHITECTURE §2/§5).

Ported/trimmed from the GenAI Launchpad `core/` — Langfuse spans, streaming, and
`concurrent_nodes` are removed (tracing returns with Langfuse in E12). A hardening
over Launchpad: a router's chosen edge must be a *declared* connection, so routing
can never jump off the validated DAG at runtime.
"""

import asyncio
from abc import ABC
from collections import Counter, deque
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.core.nodes import BaseRouter, Node
from app.core.task_context import TaskContext


class NodeConfig(BaseModel):
    """One node's place in the workflow: the node class, its outgoing edges, and whether it routes."""

    node: type[Node]
    connections: list[type[Node]] = Field(default_factory=list)
    is_router: bool = False
    description: str | None = None


class WorkflowSchema(BaseModel):
    """A full workflow: an event schema, a start node, and the node configs forming the DAG."""

    event_schema: type[BaseModel]
    start: type[Node]
    nodes: list[NodeConfig]
    description: str | None = None


class WorkflowValidator:
    """Validates a `WorkflowSchema`: DAG (cycle-free + all-reachable) and routing config."""

    def __init__(self, workflow_schema: WorkflowSchema):
        self.workflow_schema = workflow_schema

    def validate(self) -> None:
        self._validate_unique_nodes()
        self._validate_dag()
        self._validate_connections()

    def _validate_unique_nodes(self) -> None:
        # A node may appear at most once. Otherwise the validator (first match) and the
        # runtime registry (last write) could see different graphs — e.g. a later
        # duplicate adding a self-loop the cycle check already approved.
        counts = Counter(nc.node for nc in self.workflow_schema.nodes)
        dupes = sorted(node.__name__ for node, n in counts.items() if n > 1)
        if dupes:
            raise ValueError(f"Duplicate node configs for: {dupes}")

    def _validate_dag(self) -> None:
        if self._has_cycle():
            raise ValueError("Workflow schema contains a cycle")
        reachable = self._reachable_nodes()
        all_nodes = {nc.node for nc in self.workflow_schema.nodes}
        unreachable = all_nodes - reachable
        if unreachable:
            names = sorted(n.__name__ for n in unreachable)
            raise ValueError(f"Unreachable nodes: {names}")

    def _config_for(self, node: type[Node]) -> NodeConfig | None:
        return next((nc for nc in self.workflow_schema.nodes if nc.node == node), None)

    def _has_cycle(self) -> bool:
        visited: set[type[Node]] = set()
        rec_stack: set[type[Node]] = set()

        def dfs(node: type[Node]) -> bool:
            visited.add(node)
            rec_stack.add(node)
            config = self._config_for(node)
            if config:
                for neighbor in config.connections:
                    if neighbor not in visited:
                        if dfs(neighbor):
                            return True
                    elif neighbor in rec_stack:
                        return True
            rec_stack.discard(node)
            return False

        return any(
            nc.node not in visited and dfs(nc.node) for nc in self.workflow_schema.nodes
        )

    def _reachable_nodes(self) -> set[type[Node]]:
        reachable: set[type[Node]] = set()
        queue: deque[type[Node]] = deque([self.workflow_schema.start])
        while queue:
            node = queue.popleft()
            if node in reachable:
                continue
            reachable.add(node)
            config = self._config_for(node)
            if config:
                queue.extend(config.connections)
        return reachable

    def _validate_connections(self) -> None:
        for nc in self.workflow_schema.nodes:
            if len(nc.connections) > 1 and not nc.is_router:
                raise ValueError(
                    f"Node {nc.node.__name__} has multiple connections but is not marked as a router."
                )
            # is_router=True must be a BaseRouter subclass — the runner resolves a router
            # edge via node().route(ctx), which only exists on BaseRouter; fail at
            # construction, not with a runtime AttributeError.
            if nc.is_router and not issubclass(nc.node, BaseRouter):
                raise ValueError(
                    f"Node {nc.node.__name__} is marked is_router=True but is not a BaseRouter subclass."
                )


class Workflow(ABC):
    """Abstract base for a concrete workflow; subclasses set `workflow_schema`.

    Construction validates the schema and builds the node registry. `run()` drives the
    graph synchronously (wraps `asyncio.run`) and `run_async()` from an active loop.
    """

    workflow_schema: ClassVar[WorkflowSchema]

    def __init__(self) -> None:
        WorkflowValidator(self.workflow_schema).validate()
        self.nodes: dict[type[Node], NodeConfig] = self._initialize_nodes()

    def _initialize_nodes(self) -> dict[type[Node], NodeConfig]:
        registry: dict[type[Node], NodeConfig] = {}
        for node_config in self.workflow_schema.nodes:
            registry[node_config.node] = node_config
            for connected in node_config.connections:
                registry.setdefault(connected, NodeConfig(node=connected))
        return registry

    def run(self, event: Any = None, *, context: TaskContext | None = None) -> TaskContext:
        """Run the workflow synchronously (new event loop) — for inline endpoint/script callers."""
        if context is None and event is None:
            raise ValueError("Either event or context must be provided")
        return asyncio.run(self._execute(event, context))

    async def run_async(
        self, event: Any = None, *, context: TaskContext | None = None
    ) -> TaskContext:
        """Run the workflow on the active event loop (e.g. from an async route or parent workflow)."""
        if context is None and event is None:
            raise ValueError("Either event or context must be provided")
        return await self._execute(event, context)

    async def _execute(
        self, event: Any = None, existing_context: TaskContext | None = None
    ) -> TaskContext:
        if existing_context is not None:
            task_context = existing_context
            task_context.should_stop = False
        else:
            task_context = TaskContext(event=event)
            task_context.event = self.workflow_schema.event_schema(**event)

        # Preserve a parent's registry across nested (composed) runs; restore on EVERY
        # exit (incl. an exception from a node/router/cleanup) so a parent that catches
        # or retries the child failure isn't left pointing at the child's registry.
        parent_nodes = task_context.metadata.get("nodes")
        task_context.metadata["nodes"] = self.nodes
        try:
            current_node_class: type[Node] | None = self.workflow_schema.start
            while current_node_class is not None:
                if task_context.should_stop:
                    break

                current_node = self.nodes[current_node_class].node
                node_instance: Node | None = None
                try:
                    if not issubclass(current_node, BaseRouter):
                        node_instance = current_node(task_context=task_context)
                        task_context = await node_instance.process(task_context)
                finally:
                    if node_instance is not None:
                        await node_instance.cleanup()

                current_node_class = await self._next_node_class(current_node_class, task_context)
        finally:
            if parent_nodes is not None:
                task_context.metadata["nodes"] = parent_nodes
            else:
                task_context.metadata.pop("nodes", None)
        return task_context

    async def _next_node_class(
        self, current_node_class: type[Node], task_context: TaskContext
    ) -> type[Node] | None:
        node_config = self.nodes.get(current_node_class)
        if not node_config or not node_config.connections:
            return None
        if node_config.is_router:
            router = current_node_class()
            return self._handle_router(node_config, router, task_context)
        return node_config.connections[0]

    def _handle_router(
        self, node_config: NodeConfig, router: BaseRouter, task_context: TaskContext
    ) -> type[Node] | None:
        next_class = router.route(task_context)
        if next_class is None:
            return None
        if next_class not in node_config.connections:
            declared = [c.__name__ for c in node_config.connections]
            raise ValueError(
                f"Router {node_config.node.__name__} routed to {next_class.__name__}, "
                f"which is not a declared connection ({declared})."
            )
        return next_class
