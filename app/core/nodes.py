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
from dataclasses import dataclass
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

    It composes one or more `RouterNode` predicate **classes** (`routes`) plus an
    optional `fallback` **node class**. `route()` walks the predicates in order,
    instantiating each **fresh** with the live context, and returns the **class** of
    the first non-None next node, else the `fallback` class, else None. It does **not**
    itself stop the workflow — the §2 safety-gate short-circuit is this router *routing
    to* a terminal override node whose `process()` writes the brief and calls
    `ctx.stop_workflow()` (so the gated REST brief is still produced; the router must
    not stop before that terminal runs).

    `routes`/`fallback` are **classes**, not instances: a predicate is constructed per
    evaluation so no mutable `RouterNode` state is shared across runs, and the fallback
    is returned by class (never constructed here — so an `AgentNode` fallback isn't
    instantiated, and its E9 LLM `Agent`, just to read its type).
    """

    routes: ClassVar[list[type[RouterNode]]] = []
    fallback: ClassVar["type[Node] | None"] = None

    async def process(self, task_context: TaskContext) -> TaskContext:
        # Routers don't process; the runner resolves their edge via route().
        return task_context

    def route(self, task_context: TaskContext) -> "type[Node] | None":
        for route_cls in self.routes:
            predicate = route_cls(task_context=task_context)
            next_node = predicate.determine_next_node(task_context)
            if next_node is not None:
                return type(next_node)
        return self.fallback


@dataclass
class AgentConfig:
    """Minimal, stack-neutral declaration of an LLM call's intent.

    Only the fields needed to *declare* intent now — no provider enum, no SDK types.
    E9 (LLM.md §0) extends this and constructs the PydanticAI `Agent`/model from it;
    nothing here imports the PydanticAI or provider SDKs.
    """

    model_id: str
    output_type: type = str
    instructions: str | None = None


class AgentNode(Node, ABC):
    """Abstract LLM-call placeholder — the seam an E9 PydanticAI `Agent` fills.

    Keeps the `OutputType` / `DepsType` structured-output + deps seam and an abstract
    `get_agent_config()`, but constructs **no** `Agent` and imports **no** provider SDK
    (real wiring is E9 — LLM.md §0). Per derive-don't-emit (ARCHITECTURE §5) the eventual
    model emits only picks; downstream `Node`s fill every derived field. PydanticAI is
    kept stack but is intentionally not imported in this phase's `nodes.py`.
    """

    class DepsType(BaseModel):
        """Run-context deps placeholder; subclasses override."""

    class OutputType(BaseModel):
        """Structured-output placeholder; subclasses override."""

    @abstractmethod
    def get_agent_config(self) -> AgentConfig:
        """Return the agent's configuration (E9 builds the PydanticAI Agent from it)."""

    @abstractmethod
    async def process(self, task_context: TaskContext) -> TaskContext:
        """Run the LLM call and store its OutputType; abstract so AgentNode can't be instantiated."""
