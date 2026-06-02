# Adversarial Validation — Round 1

**Run:** 2026-06-03 (UTC)
**Plan:** e1-p3-workflow-engine
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No ship: the plan bakes in stop semantics and validation guards that will make later daily-brief and E9 work fail or drift from the documented architecture.

Findings:
- [high] Apply: router stop semantics skip the required RestDay terminal (.claude/plans/e1-p3-workflow-engine/tasks/TASK-004-workflowrunner-executor-with-stop-workflow-and-tests.md:44-46)
  Verdict: apply. The task says the router calls `ctx.stop_workflow()` while routing to a RestDay-style terminal, and the runner checks `should_stop` at the top of the next loop. Inference from the specified walk: `SafetyGateRouter -> RestDayNode + stop` will break before `RestDayNode` can code-write the REST/active-recovery brief, despite ARCHITECTURE/E11 requiring that gated path to return a successful code-written brief with no LLM call.
  Recommendation: Change PLAN.md, RESEARCH.md, TASK-002, TASK-004, and TASK-005 so the terminal override node executes before stopping, or specify that the router itself writes the complete gated output; add a test proving `RestDayNode` output is present and `TuneSessionNode` is skipped.
- [high] Apply: import guard misclassifies PydanticAI as dropped stack (.claude/plans/e1-p3-workflow-engine/tasks/TASK-005-final-validation.md:43-45)
  Verdict: apply. The final validation forbids `pydantic_ai` anywhere under `app/core`, but ARCHITECTURE keeps PydanticAI and E9 requires `AgentNode` to wrap a PydanticAI `Agent`. Shipping this plan creates a permanent core test that blocks the next planned LLM integration rather than only enforcing the P3 placeholder boundary.
  Recommendation: Change PLAN.md, TASK-003, TASK-004, and TASK-005: remove `pydantic_ai` from the dropped-stack grep, keep the P3-specific no-provider check scoped to `app/core/nodes.py`, and document that E9 is expected to introduce PydanticAI wiring.
- [medium] Apply: router outputs are not constrained to the validated DAG (.claude/plans/e1-p3-workflow-engine/tasks/TASK-004-workflowrunner-executor-with-stop-workflow-and-tests.md:70-73)
  Verdict: apply. The plan validates static `connections`, then `_handle_router` maps whatever node instance `BaseRouter.route()` returns to the next class. A bad route/fallback can jump to an undeclared node or bypass declared edges after validation, producing a mid-run KeyError or an unreviewed execution path. That violates the plan's own claim that routing edges are declared in `WorkflowSchema`.
  Recommendation: Change TASK-004 and TASK-005 to require `_handle_router` to reject returned classes not listed in the current node's `connections` and add tests for undeclared route and undeclared fallback failures.

Next steps:
- Revise the plan before implementation, especially TASK-004/TASK-005, then re-run the plan review against the updated acceptance mapping.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Router stop semantics skip the required RestDay terminal (stop checked at top of loop → terminal never runs) | high | apply | Real defect: ARCHITECTURE §2/§5 + E11 need the gated path to return a code-written REST brief; the terminal must run *then* stop. | PLAN.md:Decisions/Risks/Acceptance · RESEARCH.md:Architecture-Facts/Constraints/Uncertainty/matrix · TASK-002 · TASK-004 · TASK-005 |
| 2 | Import guard misclassifies PydanticAI as dropped stack (durable `pydantic_ai` ban under `app/core`) | high | apply | Real defect: PydanticAI is kept stack (ARCHITECTURE §1); E9 imports it in `app/core`. A durable ban would block E9. Scope the no-provider check to `nodes.py`. | PLAN.md:Decisions/Risks/Acceptance · RESEARCH.md:Constraints/matrix/commands · TASK-003 · TASK-004 · TASK-005 |
| 3 | Router output not constrained to the validated DAG (`_handle_router` accepts any returned class) | medium | apply | Valid: static validation only checks declared edges; a bad route/fallback can jump off-DAG → mid-run KeyError / unreviewed path. Harden `_handle_router`. | PLAN.md:Decisions/Risks/Acceptance · RESEARCH.md:Constraints/matrix/Uncertainty · TASK-002 · TASK-004 · TASK-005 |
