# Adversarial Validation — Round 1

**Run:** 2026-06-03 (UTC)
**Plan:** e3-p2-constitution-renderer
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the plan has a blocking validation contradiction and misses an architecture-level cadence contract.

Findings:
- [high] Final validation bans prose the template must keep (.claude/plans/e3-p2-constitution-renderer/tasks/TASK-004-final-validation.md:44-50)
  Verdict: apply. Rationale: TASK-004 greps for `body_mass` anywhere in the template, but PLAN/TASK-001 require copying `HEALTH-CONSITTUTION.md` verbatim and keeping the current-weight prose row, whose source is HealthKit `body_mass`. A correct implementation fails validation; a passing one has to delete required architecture prose. Plan files to change: TASK-004, TASK-001, PLAN.
  Recommendation: Replace the grep with a Jinja-aware check that bans weight variables only inside `{{ ... }}` and render args; allow literal `body_mass` prose, plus keep the sentinel runtime-weight-not-in-system-prompt test.
- [medium] Cadence current cue is absent from the contract (.claude/plans/e3-p2-constitution-renderer/PLAN.md:174-177)
  Verdict: apply. Rationale: DB.md §5 and the downstream model contracts include `thresholds.cadence_current_spm` as this month's cue, while this plan only templates and validates `cadence_target_spm` (`172`). That can ship a prompt that pushes the end target instead of the current ramp cue, and TASK-004 would not catch it. Plan files to change: PLAN, RESEARCH, TASK-001, TASK-002, TASK-004.
  Recommendation: Resolve the target-vs-current mismatch explicitly: add `thresholds.cadence_current_spm` to the placeholder inventory and output assertions, or document that current cadence is only E8/E9 user context and update the architecture/template accordingly.
- [medium] Template fork is not drift-proofed (.claude/plans/e3-p2-constitution-renderer/PLAN.md:72-74)
  Verdict: apply. Rationale: the architecture names `HEALTH-CONSITTUTION.md` as the Jinja2 template rendered each call, but PLAN makes a copied `.j2` the runtime source and declares sync tooling out of scope. The final checks only assert a few substrings, so a package template missing safety/progression sections could still pass. Plan files to change: PLAN, TASK-001, TASK-004.
  Recommendation: Either load/generate from the canonical root `HEALTH-CONSITTUTION.md`, or make final validation run an exact `diff`/equivalence check between the root file and `app/core/templates/constitution.md.j2` with any allowed differences listed.

Next steps:
- Patch the plan before implementation.
- Re-run this review against the revised plan, especially TASK-004.

## Triage

<!--
Verdict values:
  apply   — real plan defect; edit PLAN.md / tasks / DECISIONS.md now
  defer   — has merit but out of scope for this plan; capture as a known limitation or follow-up
  reject  — contradicts an explicit Decision in PLAN.md/DECISIONS.md, or is taste/speculation/incorrect
-->

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Final-validation grep bans `body_mass`/`current_weight` literals the verbatim prose must keep — a correct impl fails validation | high | apply | Real self-contradiction: TASK-001 keeps the §1 "Weight (current) → … HealthKit `body_mass`" prose verbatim, so the TASK-004 grep would fail a correct build. Fix: ban weight only inside `{{ }}` placeholders / render args, allow literal prose; keep the sentinel runtime-weight test. | TASK-004, TASK-001, PLAN.md:Risks |
| 2 | `cadence_current_spm` (this month's cue) not in the template/contract — risks pushing the end target not the current ramp cue | med | apply (corrected resolution) | Valid gap in *documentation*, but Codex's first remedy (add the placeholder) is **wrong** and would break fidelity: the constitution prose (lines 123/365) references **only** `cadence_target_spm`; `cadence_current_spm` is the per-card `cadenceSpm` cue fed via the **user context** at call time (MODELS.md §427/§617; LLM.md §207 "code · deterministic progression via `profile.yaml cadence_current_spm`"). Apply the *second* remedy: document the target-vs-current split explicitly so it reads as intentional. | PLAN.md:Decisions+Out of Scope, RESEARCH.md, TASK-001 |
| 3 | The `.j2` fork is not drift-proofed — substring checks would pass a `.j2` missing whole §8/§9 sections | med | apply | Real: the §2-substring assertions don't catch a template missing the safety/progression sections. Make the drift-guard a structural section-header presence check over all major §1–§11 headers in both TASK-001 and TASK-004. (An exact `diff` against the root `.md` is impractical because the `.j2` legitimately omits the doc-only HTML-companion footer; section-presence is the right invariant.) | PLAN.md:Risks+AC, TASK-001, TASK-004 |
