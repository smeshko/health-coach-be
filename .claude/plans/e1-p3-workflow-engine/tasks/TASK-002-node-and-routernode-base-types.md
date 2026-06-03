# TASK-002: Node and RouterNode base types

Depends on: TASK-001
Suggested commit: `feat(core): add Node and RouterNode base types`

## Goal

Add the deterministic `Node` base and the conditional-branch/short-circuit `RouterNode`/`BaseRouter`
primitives that operate over `TaskContext` (ARCHITECTURE §5 node legend).

## Files

- `app/core/nodes.py` — new (this task adds `Node` + routing; `AgentNode` lands in TASK-003):
  - `Node(ABC)` — deterministic processing. Inner `class OutputType(BaseModel)`; `__init__(task_context=None)`;
    `save_output(output: BaseModel)` (stores under `node_name` in `ctx.nodes`); `get_output(node_class)`
    (reads `ctx.nodes.get(node_class.__name__)`); `node_name` property (`self.__class__.__name__`);
    `@abstractmethod async def process(ctx: TaskContext) -> TaskContext`; `async def cleanup() -> None`
    (default no-op). Ported from `../genai-launchpad-main/app/launchpad/core/nodes/base.py`.
  - `RouterNode(ABC)` — the **single routing predicate** (NOT a graph `Node`): `__init__(task_context=None)`;
    `@abstractmethod determine_next_node(ctx) -> Node | None`; `node_name`, `save_output`, `get_output`
    (as in base). Ported from `../genai-launchpad-main/app/launchpad/core/nodes/router.py`.
  - `BaseRouter(Node)` — the **router node placed in the DAG** (the runner calls `.route(ctx)` on it):
    holds `routes: list[RouterNode]` + `fallback: Node | None`; `route(ctx)` walks `routes`, assigning
    `ctx` to each before calling `determine_next_node`, returns the first non-`None` next node else
    `fallback` else `None`. `process()` is a no-op (routers don't process).
  - **Docstrings must make the two roles explicit** (`BaseRouter` = in-graph dispatcher; `RouterNode` =
    one predicate it composes), since the names invert intuition and we keep both for port fidelity even
    though our single router needs only one predicate + fallback.
- `app/core/__init__.py` — re-export `Node`, `RouterNode`, `BaseRouter`.
- `tests/core/test_nodes.py` — new: Node abstractness + run + output round-trip; router selection +
  fallback; and a `Node.process()` calling `ctx.stop_workflow()` to show the flag is observable (the
  router does **not** stop — the terminal-then-stop short-circuit is exercised at runtime in TASK-004).

## Acceptance

- [ ] `Node` cannot be instantiated without implementing `process` (abstract); a concrete `Node` runs via
      `await node.process(ctx)` and returns the `TaskContext`.
- [ ] `save_output(model)` on a concrete node stores under `node_name`; `get_output(NodeClass)` returns it;
      a missing node returns `None`.
- [ ] `BaseRouter.route(ctx)` returns the first matching sub-router's node, assigns `ctx` to each
      sub-router before evaluating, and returns `fallback` when none match (and `None` when no fallback).
- [ ] A `RouterNode.determine_next_node` **only returns** the next node (the terminal override, e.g.
      `SafetyRestNode`); it does **not** call `ctx.stop_workflow()`. The stop is the terminal node's
      `process()` job — the gate writes its brief *then* stops (see Notes). A plain `Node.process()` that
      calls `ctx.stop_workflow()` is enough to show the flag is observable here; the runner-level
      "terminal runs, downstream skipped" assertion is TASK-004.
- [ ] No `boto3`/`google` provider imports, and no `pydantic_ai` or Langfuse spans in `nodes.py` this
      phase (PydanticAI is E9, Langfuse tracing is E12 — both kept stack, just not wired here yet).

## Steps

### RED
- [ ] `tests/core/test_nodes.py`: assert `Node`/`RouterNode` abstractness; a concrete `Node` saves/gets
      output; a `BaseRouter` with two `RouterNode`s selects by context state and falls back. **The stop
      short-circuit is NOT demonstrated inside `determine_next_node`** — at this layer a router only
      *returns* a terminal node; calling `ctx.stop_workflow()` belongs to that terminal node's `process()`
      (the runner-level terminal-then-stop test lives in TASK-004). A `Node.process()` may set
      `ctx.stop_workflow()` here to show the flag is observable, but no router branch sets stop.

### GREEN
- [ ] Implement `Node`, `RouterNode`, `BaseRouter` in `app/core/nodes.py`; wire re-exports.

### REFACTOR
- [ ] Trim docstrings to the kept behaviour; ensure no dropped-stack imports.

## Notes

`BaseRouter.route` assigns the live `ctx` onto each sub-router before `determine_next_node` so routers can
read prior node outputs — this is the §2 safety-gate pattern (`SafetyGateRouter` → `SafetyRestNode` + stop).
**The router routes *to* the terminal; the terminal node's `process()` writes its output and calls
`ctx.stop_workflow()`** (so the gated REST brief is still produced — ARCHITECTURE §2/§5, E11). The router
must not stop *before* the terminal runs. Routing edges are declared in the `WorkflowSchema` (TASK-004), so
`determine_next_node` returns a node **instance** whose class the runner maps to the next config — and
TASK-004 additionally constrains that returned class to the declared `connections`.
