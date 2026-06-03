"""Shared workflow state passed between nodes (E1·P3 TASK-001).

`TaskContext` is internal engine state — every node reads and writes it as the
workflow walks the DAG, and it is never serialized to the client. So it is a plain
snake_case `BaseModel`, **not** the camelCase wire base (MODELS "Conventions →
Casing"); the camelCase brief payloads are separate response models in later epics.

Ported/trimmed from the GenAI Launchpad `core/task.py` — the Langfuse `trace_id`
field is dropped here and returns with Langfuse tracing in E12.
"""

from typing import Any

from pydantic import BaseModel, Field


class TaskContext(BaseModel):
    """Mutable container threaded through a workflow's node graph."""

    event: Any
    nodes: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-node outputs/state, keyed by node class name.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Workflow-level metadata and the runtime node registry.",
    )
    should_stop: bool = Field(
        default=False,
        description="When set (via stop_workflow), the runner halts after the current node.",
    )

    def update_node(self, node_name: str, **kwargs: Any) -> None:
        """Merge keyword data into this node's output bucket (siblings untouched)."""
        self.nodes[node_name] = {**self.nodes.get(node_name, {}), **kwargs}

    def stop_workflow(self) -> None:
        """Signal the runner to halt after the current node (the §2 safety-gate short-circuit)."""
        self.should_stop = True
