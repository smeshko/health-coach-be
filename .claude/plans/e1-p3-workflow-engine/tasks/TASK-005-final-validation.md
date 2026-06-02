# TASK-005: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for e1-p3-workflow-engine`

## Goal

Confirm every PLAN.md acceptance criterion is met with a concrete, non-circular check (named command or
test), and the engine ships clean.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked.
- [ ] **Lint:** `uv run ruff check .` passes with no issues.
- [ ] **Tests:** `uv run pytest tests/core` passes (all engine tests green).

### Acceptance-criteria mapping (1:1, concrete)

- [ ] **TaskContext state** — `uv run pytest tests/core/test_task_context.py` proves defaults
      (`nodes={}`, `metadata={}`, `should_stop=False`), `update_node` two-call **merge**, `stop_workflow()`
      flips the flag, and `from app.core import TaskContext`.
- [ ] **Node abstract + output round-trip** — `uv run pytest tests/core/test_nodes.py -k "node and
      (abstract or output)"` proves `Node` can't instantiate without `process` and
      `save_output`/`get_output` round-trip via `TaskContext.nodes`.
- [ ] **Router selection + fallback** — `uv run pytest tests/core/test_nodes.py -k router` proves
      `BaseRouter.route` selects by context state and falls back to `fallback` (and `None` when no
      fallback).
- [ ] **AgentNode abstract + no provider (phase-scoped)** — `uv run pytest tests/core/test_agent_node.py`
      proves `AgentNode()` raises `TypeError` and a trivial concrete subclass runs with no network/
      provider; **and** `! grep -nE "pydantic_ai|boto3|google\.|langfuse" app/core/nodes.py` (no match).
      (This check is scoped to `nodes.py`; `pydantic_ai` stays allowed elsewhere — it is kept stack.)
- [ ] **Validator accept/reject** — `uv run pytest tests/core/test_workflow.py -k validat` proves a linear
      graph and a router-fanout graph are accepted, and cycle / unreachable / non-router-multi-connection /
      **`is_router=True` on a non-`BaseRouter` node** are each rejected with `ValueError`.
- [ ] **Router DAG-constraint** — `uv run pytest tests/core/test_workflow.py -k "dag or undeclared"`
      proves `_handle_router` raises `ValueError` for a route, and for a fallback, whose class is not in
      the current node's declared `connections`.
- [ ] **Linear flow** — `uv run pytest tests/core/test_workflow.py -k linear` proves Node → Node runs
      end-to-end over one `TaskContext` with both outputs present.
- [ ] **Router-branch (epic §4 3-node shape)** — `uv run pytest tests/core/test_workflow.py -k branch`
      proves `Node → RouterNode → Node` runs end-to-end and only the context-selected branch executes.
- [ ] **Gated short-circuit (terminal-then-stop)** — `uv run pytest tests/core/test_workflow.py -k stop`
      proves a router routing to a terminal that calls `ctx.stop_workflow()` in `process()` leaves the
      terminal's output **present**, a sentinel node wired downstream **not** executed, and the run returns
      the partial `TaskContext` with `should_stop=True`.
- [ ] **Sync == async parity** — `uv run pytest tests/core/test_workflow.py -k "parity or async"` proves
      `run()` and `run_async()` produce the same result.
- [ ] **No dropped-stack imports** — `uv run pytest tests/core/test_core_imports.py` passes **and**
      `! grep -REn "langfuse|celery|redis|psycopg|pgvector|supabase|vecs|boto3" app/core` (no match;
      `pydantic_ai` excluded — kept stack) — epic §4; ARCHITECTURE §1 stack note.
- [ ] **Public API** — `uv run python -c "from app.core import TaskContext, Node, RouterNode, BaseRouter,
      AgentNode, AgentConfig, Workflow, WorkflowSchema, NodeConfig, WorkflowValidator"` succeeds.

- [ ] `PLAN.md` acceptance criteria all met (each mapped above).
