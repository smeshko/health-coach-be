# Adversarial Review — Round 2

**Run:** 2026-06-03 09:16 UTC
**Branch:** feature/e1-p3-workflow-engine
**Base:** staging
**Commits reviewed:** f07a5a7..171b4b6
**Prior rounds in scope:** reviews/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the round-1 fixes close the exact reports, but the engine can still erase a stop_workflow decision during nested composition, silently bypass router predicates when a BaseRouter is misflagged, and accept schemas that only fail at runtime.

Findings:
- [high] Nested workflow calls can clear a parent stop signal (app/core/workflow.py:166-169)
  When run_async/run is called with an existing TaskContext, _execute reuses that object and unconditionally sets should_stop to False. A parent node that calls stop_workflow() and then composes a child workflow with the same context loses the stop signal; after the child returns, the parent loop continues to its downstream connection. This violates the safety-gate contract that stop_workflow halts after the current node and can let an AgentNode run after a terminal stop decision.
  Recommendation: Do not clear should_stop on an existing context. Preserve the incoming flag across nested runs, or restore it with logical OR after the child completes. Add a regression where a node stops, awaits a child workflow on the same context, and verifies downstream nodes stay skipped.
- [high] Misflagged BaseRouter nodes silently take the first edge (app/core/workflow.py:187-211)
  The runner skips process for every BaseRouter subclass, but _next_node_class only calls route() when NodeConfig.is_router is true; otherwise it returns connections[0]. The validator checks only the is_router=True to BaseRouter direction, so a BaseRouter with one connection and is_router omitted passes validation, never evaluates its predicates, and unconditionally executes that edge. I verified a predicate returning None still ran the connected terminal. For conditional or safety routers, this is a silent wrong-branch failure instead of a construction-time error.
  Recommendation: Either derive router dispatch from issubclass(node, BaseRouter) and remove the flag as a behavioral switch, or validate that every BaseRouter node config has is_router=True regardless of connection count. Add a one-edge BaseRouter regression whose predicate returns None.
- [medium] Schemas can validate without a runnable start node (app/core/workflow.py:68-73)
  _validate_dag builds all_nodes only from explicit NodeConfig entries and never asserts that workflow_schema.start is present in that set. A schema with start=A and nodes=[] validates and constructs, then run() raises KeyError on the first registry lookup. This leaves another validator/runtime mismatch after the duplicate-node fix and makes malformed workflow definitions fail on the first user request instead of at startup.
  Recommendation: Require workflow_schema.start to appear exactly once in workflow_schema.nodes, and add a validator regression for an omitted start node. Consider also requiring every connection target to be explicitly declared rather than implicitly setdefaulting runtime configs.

Next steps:
- Fix the existing-context stop flag handling before shipping the composition path.
- Make BaseRouter configuration impossible to misflag or make the runner ignore the flag for router subclasses.
- Tighten schema declaration validation, then rerun tests/core plus the new adversarial regressions.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Composition clears `should_stop` unconditionally, erasing a parent's stop | high | fix | Real safety-gate violation in the composition path. Remember the incoming flag, let the child run its own walk, OR-restore on exit so the parent's stop survives. Regression added. | 4f06ca8 |
| 2 | A `BaseRouter` with `is_router` omitted is skipped *and* never routed → silent connections[0] | high | fix | Took Codex's option (b): enforce is_router ⟺ BaseRouter in both directions at validation (the runner always validates before walking, so the flag is guaranteed correct at runtime). Regression added. | bc1b613 |
| 3 | `start` node with no NodeConfig validates, then KeyErrors at runtime | med | fix | Validator/runtime mismatch. Assert `start` is in the node configs during DAG validation. The "require every connection target declared" sub-suggestion is left as-is — auto-adding terminal configs (no connections) is an intentional convenience and ends the walk cleanly. | ac4a6de |
