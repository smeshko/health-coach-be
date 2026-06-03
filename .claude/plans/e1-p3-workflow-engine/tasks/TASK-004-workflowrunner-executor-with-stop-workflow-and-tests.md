# TASK-004: WorkflowRunner executor with stop_workflow and tests

Depends on: TASK-003
Suggested commit: `feat(core): add Workflow runner with stop_workflow and tests`

## Goal

Add the workflow schema, DAG validator, and the `Workflow` runner that walks the node graph over a shared
`TaskContext`, honoring `stop_workflow()`, and prove it with linear / router-branch / early-stop tests
(ARCHITECTURE §5; epic §3 E1·P3, §4).

## Files

- `app/core/workflow.py` — new:
  - `NodeConfig(BaseModel)` — `node: type[Node]`, `connections: list[type[Node]] = []`,
    `is_router: bool = False`, `description: str | None = None`. **No** `concurrent_nodes` (dropped).
  - `WorkflowSchema(BaseModel)` — `event_schema: type[BaseModel]`, `start: type[Node]`,
    `nodes: list[NodeConfig]`, `description: str | None = None`.
  - `WorkflowValidator` — `validate()` runs `_validate_dag()` (cycle-free via DFS + all-reachable from
    `start` via BFS) and `_validate_connections()` (only `is_router` nodes may have >1 connection, **and**
    `is_router=True` only on a `BaseRouter` subclass — raise `ValueError` otherwise; the runner calls
    `node().route(ctx)`, which only exists on `BaseRouter`, so this must fail at construction not runtime).
    Ported from `../genai-launchpad-main/app/launchpad/core/validate.py` + the type-check (new).
  - `Workflow(ABC)` — `workflow_schema: ClassVar[WorkflowSchema]`; `__init__` validates the schema and
    builds the node registry; `run(event=None, *, context=None) -> TaskContext` (sync, wraps
    `asyncio.run`) and `async run_async(...)`; the graph walk checks `ctx.should_stop` at the **top** of
    each iteration, runs non-router nodes' `process()` (router edges resolved via `BaseRouter.route`),
    and calls each instantiated node's `cleanup()` in a `finally`. Routing via `_get_next_node_class` +
    `_handle_router`. Ported/trimmed from `../genai-launchpad-main/app/launchpad/core/workflow.py` —
    **strip** Langfuse spans/`_observation_context`/`NoOpSpan` (tracing is **deferred to E12**, re-added
    there — not dropped), `run_stream_async` and the `AgentStreamingNode` branch (streaming dropped), and
    `trace_id` handling (returns with Langfuse in E12).
  - **Stop semantics (terminal-then-stop):** because `should_stop` is checked at the **top** of the loop,
    a routed-to terminal override node (e.g. `SafetyRestNode`) runs its `process()` — writing its output —
    and calls `ctx.stop_workflow()` *inside* `process()`; the loop then breaks before the next node. The
    runner must never short-circuit *before* a routed-to node runs (that would skip the §2 gated REST
    brief — ARCHITECTURE §2/§5, E11).
  - **`_handle_router` DAG-constraint (HARDEN vs Launchpad):** after `BaseRouter.route(ctx)` returns a
    node, map it to its class and **reject** (raise `ValueError`) if that class is not among the current
    node's declared `connections`. `None`/fallback-to-`None` ends the walk. This stops a router jumping to
    an undeclared node (Launchpad does no such check) — keeping the runtime path inside the validated DAG.
- `app/core/__init__.py` — re-export `Workflow`, `WorkflowSchema`, `NodeConfig`, `WorkflowValidator`.
- `tests/core/test_workflow.py` — new: linear, router-branch (epic §4 3-node shape), early-stop,
  sync==async parity, and validator accept/reject cases.
- `tests/core/test_core_imports.py` — new: the no-dropped-deps import guard over `app/core/`.

## Acceptance

- [ ] `WorkflowValidator` **accepts** a linear graph and a router-fanout graph; **rejects** a cycle
      (`ValueError`), an unreachable node (`ValueError`), a non-router node with >1 connection
      (`ValueError`), and a node marked `is_router=True` that is **not** a `BaseRouter` subclass
      (`ValueError`).
- [ ] **Linear** workflow `A(Node) → B(Node)` runs end-to-end over one `TaskContext`; both outputs present
      and ordered (B sees A's output).
- [ ] **Router branch** — the epic §4 `Start(Node) → Router(RouterNode) → {Left|Right}(Node)` 3-node shape
      runs end-to-end; the branch the `TaskContext` selects is the one that executes, the other does not.
- [ ] **Gated short-circuit (terminal-then-stop)** — a router routes to a terminal override node that
      writes its output **and** calls `ctx.stop_workflow()` in `process()`; the terminal's output IS
      present, a sentinel `Node` wired downstream of the router does NOT run, and the run returns the
      partial `TaskContext` with `should_stop=True` (the §2 `SafetyGateRouter → SafetyRestNode + stop`
      pattern — REST brief written, AgentNode-stand-in skipped).
- [ ] **Router DAG-constraint** — `_handle_router` raises `ValueError` when a router returns a route whose
      class is not in the current node's `connections`, and likewise for an undeclared `fallback` (two
      tests).
- [ ] `run()` (sync) and `run_async()` (async, via `pytest.mark.asyncio` or `asyncio.run`) drive the same
      workflow to the same `TaskContext` result.
- [ ] `grep -REn "celery|redis|psycopg|pgvector|supabase|vecs|boto3" app/core` returns nothing
      (epic §4; ARCHITECTURE §1 stack note) — asserted by `test_core_imports.py`. `pydantic_ai` (E9) and
      `langfuse` (E12) are **excluded** (both kept stack).
- [ ] `uv run pytest tests/core` and `uv run ruff check .` pass.

## Steps

### RED
- [ ] `tests/core/test_workflow.py`: define tiny concrete `Node`/`RouterNode`/`BaseRouter` test doubles;
      assert validator accept/reject cases (incl. `is_router=True` on a non-`BaseRouter` node raising
      `ValueError`), linear run, router-branch run (both directions), gated short-circuit
      (terminal-then-stop: terminal output present, downstream sentinel NOT run, `should_stop=True`),
      router DAG-constraint (undeclared route and undeclared fallback each raise `ValueError`), and
      sync/async parity.
- [ ] `tests/core/test_core_imports.py`: walk `app/core/*.py` source (or import the package and inspect
      `sys.modules`) and assert none of the dropped-stack names appear — banning
      `celery|redis|psycopg|pgvector|supabase|vecs|boto3` but **not** `pydantic_ai` (E9) or `langfuse`
      (E12) — both kept stack.

### GREEN
- [ ] Implement `app/core/workflow.py` (schema + validator + runner) and the re-exports.

### REFACTOR
- [ ] Remove any vestigial Launchpad tracing/streaming hooks; tighten docstrings to the kept behaviour.

## Notes

The runner checks `should_stop` at the **top** of each loop iteration. The §2 gate pattern is:
`SafetyGateRouter` routes **to** `SafetyRestNode`; `SafetyRestNode.process()` writes the REST brief **and** calls
`ctx.stop_workflow()`; the loop then breaks before the `AgentNode`. So a routed-to terminal always runs —
the runner must not short-circuit before it (else the REST brief is skipped — ARCHITECTURE §2/§5, E11).
`_handle_router` instantiates the router, calls `route(ctx)`, maps the returned instance's class to the next
config, and **rejects (raises `ValueError`) any returned class not in the current node's declared
`connections`** (a hardening over Launchpad, which leaves this unguarded — preventing off-DAG jumps /
mid-run `KeyError`). Nodes' `process()` is `async`; `run()` wraps `asyncio.run` for sync endpoint/script
callers (workflows are invoked synchronously inline — ARCHITECTURE §5). `cleanup()` runs in a `finally` so
resources release even on error. **`pydantic_ai` (E9) and `langfuse` (E12) are kept stack** — the durable
dropped-stack import guard must not ban either (E9 wires the `Agent` in `app/core`; E12 wires Langfuse
tracing in `app/core`). The P3 port just strips the Launchpad spans for now; nothing to trace until E9's
LLM call lands.
