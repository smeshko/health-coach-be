# Adversarial Validation — Round 2

**Run:** 2026-06-03 (UTC)
**Plan:** e1-p3-workflow-engine
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No ship: the pydantic_ai durable-ban fix, terminal-then-stop acceptance, undeclared route/fallback checks, and TASK-005 1:1 PLAN acceptance mapping are largely corrected, but the plan still leaves stop-semantics ambiguity and a router validation hole that can fail at runtime.

Findings:
- [medium] Apply: residual router-set-stop wording can reintroduce the terminal-skip bug (.claude/plans/e1-p3-workflow-engine/tasks/TASK-002-node-and-routernode-base-types.md:45-47)
  Verdict: apply. The task's RED step still says the router branch sets should_stop, and PLAN.md also summarizes the early-stop test as "router sets stop"; that conflicts with the corrected TASK-004/TASK-005 contract where the router only returns the terminal and the terminal process writes output before stopping. If an implementer follows this step, the old failure mode can return: stop is set before the RestDay-style terminal runs, so the gated REST brief is skipped. Plan files: TASK-002, PLAN.md.
  Recommendation: Rewrite the TASK-002 RED step and PLAN.md test summary to say the RouterNode returns a terminal node, and only that terminal node's process() calls ctx.stop_workflow(); do not require or demonstrate stop_workflow() inside determine_next_node().
- [medium] Apply: is_router can validate a non-router and then fail at runtime (.claude/plans/e1-p3-workflow-engine/tasks/TASK-004-workflowrunner-executor-with-stop-workflow-and-tests.md:19-27)
  Verdict: apply. The planned validator only describes the fanout rule in terms of the is_router flag, while the runner later resolves router edges through BaseRouter.route. A plain NodeConfig with node=SomeNode, is_router=True, and multiple connections would satisfy the planned validator but then be treated as a BaseRouter during execution, causing a late AttributeError or equivalent instead of failing at construction. Plan files: TASK-004, TASK-005, PLAN.md.
  Recommendation: Extend WorkflowValidator to reject node_config.is_router=True unless node_config.node is a BaseRouter subclass, and add final-validation coverage for a non-BaseRouter marked is_router=True with multiple connections.

Next steps:
- Fix the lingering stop wording in PLAN.md and TASK-002 so all plan layers describe terminal-then-stop consistently.
- Add router type/flag validation and map it in TASK-005 before implementation.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Residual "router sets stop" wording (TASK-002 RED + acceptance, PLAN.md test summary + node desc) can reintroduce the terminal-skip bug | medium | apply | Real inconsistency vs the corrected terminal-then-stop contract; an implementer following TASK-002 RED could set stop before the terminal runs. | TASK-002 (RED + acceptance) · PLAN.md (Scope node desc + Scope tests bullet) |
| 2 | `is_router=True` validates on a non-`BaseRouter` node, then runner's `node().route()` fails at runtime (`AttributeError`) | medium | apply | Real gap: Launchpad fanout rule checks count only; type mismatch must fail at construction. Add `is_router`↔`BaseRouter` check + test. | PLAN.md (Scope validator + Decisions + Acceptance) · RESEARCH.md (DAG constraint) · TASK-004 (validator + acceptance + RED) · TASK-005 (validator mapping) |
