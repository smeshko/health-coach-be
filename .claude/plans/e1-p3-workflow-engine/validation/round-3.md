# Adversarial Validation — Round 3 (final, cap reached)

**Run:** 2026-06-03 (UTC)
**Plan:** e1-p3-workflow-engine
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md, validation/round-2.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No ship: the round-2 stop-semantics fix is still incomplete. The BaseRouter validator edit and TASK-005 acceptance mapping look covered, but one residual TASK-002 instruction can reintroduce the terminal-skip bug.

Findings:
- [medium] Apply: residual router-branch stop wording can reintroduce terminal skip (.claude/plans/e1-p3-workflow-engine/tasks/TASK-002-node-and-routernode-base-types.md:26-27)
  Verdict: apply. TASK-002 still summarizes test_nodes.py as including "a router branch that calls ctx.stop_workflow()", and RESEARCH.md also says SafetyGateRouter can call stop_workflow from within a branch. That conflicts with the corrected contract where RouterNode only returns the terminal and the terminal process() writes the REST brief before stopping. An implementer following this line can set should_stop during routing, causing the runner to break before the RestDay-style terminal writes the code-generated brief. Plan files: TASK-002, RESEARCH.md.
  Recommendation: Rewrite the TASK-002 test-file summary to remove router-branch stop behavior, and clean the matching RESEARCH.md wording so stop_workflow is only called by the routed-to terminal node's process().

Next steps:
- Fix the residual stop wording, then rerun the final adversarial review.

## Triage

> Cap note: this is round 3, the final round. Per the runbook the single applied finding below was
> applied and validation stops here (3-round cap). It is the same class as round-2 #1 — two remaining
> echoes of the old "router calls stop" wording in the `## Files` test summary (TASK-002) and a
> RESEARCH.md "Uncertainty" bullet — now corrected to the terminal-then-stop contract, so it is a
> documentation-consistency cleanup, not a new behavioural defect. No new issues were raised.

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Residual "router branch calls stop" wording in TASK-002 `## Files` test summary + RESEARCH.md Uncertainty bullet | medium | apply | Last echoes of the pre-fix framing; an implementer could set stop during routing and skip the terminal REST brief. Now stop is only the routed-to terminal's `process()` job. | TASK-002 (`## Files` test bullet) · RESEARCH.md (Uncertainty: router-context bullet) |
