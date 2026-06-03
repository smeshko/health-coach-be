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
        self._validate_unique_node_names()
        self._validate_connections_declared()
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

    def _validate_unique_node_names(self) -> None:
        # Outputs are keyed by node_name (the class __name__), so two distinct classes
        # sharing a name (e.g. from different modules) would overwrite each other's slot
        # in TaskContext.nodes. Reject the collision at construction.
        counts = Counter(nc.node.__name__ for nc in self.workflow_schema.nodes)
        dupes = sorted(name for name, n in counts.items() if n > 1)
        if dupes:
            raise ValueError(f"Multiple nodes share a class name (output keys would collide): {dupes}")

    def _validate_connections_declared(self) -> None:
        # Every connection target must have its own NodeConfig. Synthesizing one for an
        # omitted target would bypass these checks — e.g. an omitted BaseRouter would be
        # registered is_router=False with no edges and silently skipped, never routing.
        declared = {nc.node for nc in self.workflow_schema.nodes}
        for nc in self.workflow_schema.nodes:
            for target in nc.connections:
                if target not in declared:
                    raise ValueError(
                        f"Connection target {target.__name__} (from {nc.node.__name__}) "
                        f"has no NodeConfig."
                    )

    def _validate_dag(self) -> None:
        all_nodes = {nc.node for nc in self.workflow_schema.nodes}
        # The start node must have its own config, else run() KeyErrors on the first
        # registry lookup — a validator/runtime mismatch caught here at construction.
        if self.workflow_schema.start not in all_nodes:
            raise ValueError(
                f"Start node {self.workflow_schema.start.__name__} has no NodeConfig."
            )
        if self._has_cycle():
            raise ValueError("Workflow schema contains a cycle")
        unreachable = all_nodes - self._reachable_nodes()
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
            # is_router and BaseRouter-ness must agree in BOTH directions, so the runner's
            # is_router dispatch always matches the node kind:
            #  - is_router=True on a non-BaseRouter would call node().route(), which only
            #    exists on BaseRouter (runtime AttributeError);
            #  - a BaseRouter with is_router omitted would be skipped *and* never routed —
            #    it would silently take connections[0] without evaluating its predicates.
            if nc.is_router and not issubclass(nc.node, BaseRouter):
                raise ValueError(
                    f"Node {nc.node.__name__} is marked is_router=True but is not a BaseRouter subclass."
                )
            if issubclass(nc.node, BaseRouter) and not nc.is_router:
                raise ValueError(
                    f"Node {nc.node.__name__} is a BaseRouter but is_router is not set to True."
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
        # Validation guarantees every node (start + every connection target) has an
        # explicit config, so the registry is just the declared configs — no implicit
        # synthesis that could mask an omitted (and unchecked) node.
        return {nc.node: nc for nc in self.workflow_schema.nodes}

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
            # Output keys are node_name (class __name__); within one schema uniqueness is
            # validated, but a composed child sharing a context could overwrite a parent
            # node of the same name. Reject that overlap before running.
            self._check_no_output_key_collision(task_context)
            # Let the child run its own walk, but remember the parent's stop decision so
            # composing a child can't silently erase a parent's stop_workflow() (the
            # incoming flag is OR-restored on exit).
            incoming_stop = task_context.should_stop
            task_context.should_stop = False
        else:
            task_context = TaskContext(event=event)
            # model_validate accepts both a raw mapping and an already-parsed event model
            # (an endpoint may hand the runner its request model directly).
            task_context.event = self.workflow_schema.event_schema.model_validate(event)
            incoming_stop = False

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
            # The parent's stop decision survives the child run.
            task_context.should_stop = task_context.should_stop or incoming_stop
        return task_context

    def _check_no_output_key_collision(self, task_context: TaskContext) -> None:
        # When composing onto a parent context, a child node sharing a name with a
        # *different* parent node would overwrite its output slot (node_name keying).
        # Same name + same class is fine (re-entrant composition).
        parent_registry = task_context.metadata.get("nodes")
        if not isinstance(parent_registry, dict):
            return
        parent_by_name = {node.__name__: node for node in parent_registry}
        for child_node in self.nodes:
            clash = parent_by_name.get(child_node.__name__)
            if clash is not None and clash is not child_node:
                raise ValueError(
                    f"Composed workflow node {child_node.__name__} collides with a different "
                    f"parent node of the same name (shared output key)."
                )

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
