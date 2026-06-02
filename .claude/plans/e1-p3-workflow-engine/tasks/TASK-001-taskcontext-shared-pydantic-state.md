# TASK-001: TaskContext shared Pydantic state

Depends on: None
Suggested commit: `feat(core): add TaskContext shared workflow state`

## Goal

Add the shared, mutable Pydantic `TaskContext` that every workflow node reads from and writes to, with
`update_node()` and the `stop_workflow()` short-circuit (ARCHITECTURE §1 Orchestration, §5).

## Files

- `app/core/task_context.py` — new: `TaskContext(BaseModel)` with fields `event: Any`,
  `nodes: dict[str, Any]` (default `{}` — per-node outputs keyed by node class name),
  `metadata: dict[str, Any]` (default `{}`), `should_stop: bool = False`. Methods:
  `update_node(node_name, **kwargs)` (merges into `nodes[node_name]`) and `stop_workflow()` (sets
  `should_stop = True`). Plain snake_case `BaseModel` — **not** the camelCase wire base (see Notes).
  Ported/trimmed from `../genai-launchpad-main/app/launchpad/core/task.py` (drop `trace_id`).
- `app/core/__init__.py` — re-export `TaskContext`.
- `tests/core/__init__.py` — new (package marker, if not present).
- `tests/core/test_task_context.py` — new: unit tests for fields, `update_node` merge, `stop_workflow`.

## Acceptance

- [ ] `TaskContext(event=...)` constructs with `nodes={}`, `metadata={}`, `should_stop=False` by default.
- [ ] `update_node("NodeA", score=1)` then `update_node("NodeA", label="x")` leaves
      `nodes["NodeA"] == {"score": 1, "label": "x"}` (merge, not overwrite).
- [ ] `stop_workflow()` sets `should_stop` to `True`.
- [ ] `from app.core import TaskContext` resolves.
- [ ] No `trace_id`/Langfuse field; no `pydantic_ai`/Langfuse import.

## Steps

### RED
- [ ] `tests/core/test_task_context.py`: assert defaults, `update_node` merge across two calls,
      `stop_workflow()` flips the flag, and `from app.core import TaskContext` imports.

### GREEN
- [ ] Implement `app/core/task_context.py` and the `app/core/__init__.py` re-export.

### REFACTOR
- [ ] Short module docstring stating `TaskContext` is internal engine state (not a wire model).

## Notes

`TaskContext` is internal engine state passed between nodes, never serialized to the client, so it stays a
plain snake_case `BaseModel` and does **not** inherit the camelCase wire base from E1·P1 (MODELS
"Conventions → Casing"). `nodes` is keyed by node class name (`node_name`), matching how `Node.save_output`
/ `get_output` address it in TASK-002.
