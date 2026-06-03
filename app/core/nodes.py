"""Workflow node base types (E1·P3 TASK-002 / TASK-003).

The engine is a DAG of three node kinds over a shared `TaskContext`
(ARCHITECTURE §5 node legend):

- `Node` — deterministic processing.
- `RouterNode` / `BaseRouter` — conditional branch / short-circuit.
- `AgentNode` — an LLM call (abstract placeholder here; real PydanticAI wiring is E9).

Ported/trimmed from the GenAI Launchpad `core/nodes/`; no Langfuse spans and no
provider SDK imports in this module (PydanticAI is kept stack but wired in E9).
"""

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel

from app.core.task_context import TaskContext


class Node(ABC):
    """Deterministic processing step over the shared `TaskContext`.

    A concrete node implements `async process(ctx)`, optionally writing its result
    with `save_output()` (keyed by `node_name`) for downstream nodes to read.
    """

    class OutputType(BaseModel):
        """Structured-output placeholder; subclasses override with their own shape."""

    def __init__(self, task_context: TaskContext | None = None):
        self.task_context = task_context

    def save_output(self, output: BaseModel) -> None:
        """Store `output` under this node's name in the shared context."""
        self.task_context.nodes[self.node_name] = output

    def get_output(self, node_class: "type[Node]") -> BaseModel | None:
        """Return a prior node's saved output (by class), or None if absent."""
        return self.task_context.nodes.get(node_class.__name__)

    @property
    def node_name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    async def process(self, task_context: TaskContext) -> TaskContext:
        """Process the context and return it (store results via save_output)."""

    async def cleanup(self) -> None:
        """Release per-instance resources; runs in a `finally` even on error. Default: no-op."""
        return None


class RouterNode(ABC):
    """A single routing **predicate** — NOT a graph `Node`.

    A `RouterNode` only answers "given this context, what node comes next?" via
    `determine_next_node` (returns the next node **instance** or None). It is composed
    inside a `BaseRouter` (below); the names invert intuition — `BaseRouter` is the
    in-graph dispatcher, `RouterNode` is one predicate it evaluates.
    """

    def __init__(self, task_context: TaskContext | None = None):
        self.task_context = task_context

    @abstractmethod
    def determine_next_node(self, task_context: TaskContext) -> "Node | None":
        """Return the next node to run, or None to defer to the next predicate / fallback."""

    @property
    def node_name(self) -> str:
        return self.__class__.__name__

    def save_output(self, output: BaseModel) -> None:
        self.task_context.nodes[self.node_name] = output

    def get_output(self, node_class: "type[Node]") -> BaseModel | None:
        return self.task_context.nodes.get(node_class.__name__)


class BaseRouter(Node):
    """The router **node placed in the DAG** — the runner calls `.route(ctx)` on it.

    It composes one or more `RouterNode` predicates (`routes`) plus an optional
    `fallback` node. `route()` walks the predicates in order, handing each the live
    context, and returns the first non-None next node, else the `fallback`, else None.
    It does **not** itself stop the workflow — the §2 safety-gate short-circuit is this
    router *routing to* a terminal override node whose `process()` writes the brief and
    calls `ctx.stop_workflow()` (so the gated REST brief is still produced; the router
    must not stop before that terminal runs).
    """

    routes: ClassVar[list[RouterNode]] = []
    fallback: ClassVar["Node | None"] = None

    async def process(self, task_context: TaskContext) -> TaskContext:
        # Routers don't process; the runner resolves their edge via route().
        return task_context

    def route(self, task_context: TaskContext) -> "Node | None":
        for route_node in self.routes:
            route_node.task_context = task_context
            next_node = route_node.determine_next_node(task_context)
            if next_node is not None:
                return next_node
        return self.fallback
