# Adversarial Validation — Round 2

**Run:** 2026-06-03 (UTC)
**Plan:** e3-p2-constitution-renderer
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No-ship: the revised plan is internally unsatisfiable because the mandated verbatim template copy is not valid Jinja2.

Findings:
- [high] Verbatim copy cannot parse as Jinja2 (.claude/plans/e3-p2-constitution-renderer/tasks/TASK-001-jinja2-constitution-template-from-health-consittution-md.md:62-69)
  Verdict: apply. Rationale: TASK-001 requires copying HEALTH-CONSITTUTION.md verbatim and keeping diff empty, but the current root file contains literal explanatory `{{ … }}` text; compiling it with Jinja2 raises `TemplateSyntaxError unexpected char '…'`, so the `.j2` cannot both be byte-identical and pass the planned parse/render tests. Plan files to change: PLAN.md, RESEARCH.md, TASK-001, TASK-004.
  Recommendation: Add an explicit source-template cleanup step before the copy: escape or reword the literal delimiter examples in HEALTH-CONSITTUTION.md, then require the `.j2` diff to stay empty against that Jinja-valid source. Keep the parse test as a required guard.

Next steps:
- Patch the plan to make the root rulebook Jinja-valid before implementation.
- Re-run validation after confirming `Environment(undefined=StrictUndefined).from_string(Path('HEALTH-CONSITTUTION.md').read_text())` parses.

## Triage

<!--
Verdict values:
  apply   — real plan defect; edit PLAN.md / tasks / DECISIONS.md now
  defer   — has merit but out of scope for this plan; capture as a known limitation or follow-up
  reject  — contradicts an explicit Decision in PLAN.md/DECISIONS.md, or is taste/speculation/incorrect
-->

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | A byte-identical verbatim copy of `HEALTH-CONSITTUTION.md` cannot parse as Jinja2 — the root file has 3 literal explanatory `{{ … }}` strings (prose *about* the template, lines 11/38/281) that Jinja2 tries to evaluate and chokes on (`…` is not a valid expression) | high | apply | Confirmed by inspection: `grep -nF '{{ … }}'` returns lines 11, 38, 281 (the "every constant is written as `{{ … }}`" prose); the 21 *real* placeholders are all valid (`{{ thresholds.max_hr }}` etc.). A round-1 edit ("diff must be empty / byte-identical") introduced this unsatisfiability — the `.j2` must escape those 3 literal delimiter examples (`{% raw %}{{ … }}{% endraw %}`) so it parses, which makes it **not** byte-identical. Fix: relax the drift-guard from "diff empty" to "diff differs ONLY in the 3 escaped literal-delimiter prose lines"; make the **parse test** (`get_template()` compiles, no `TemplateSyntaxError`) + the structural §1–§11 section-presence the real guards; the real placeholders + prose stay identical. | PLAN.md (Decisions, Out of Scope, Risks, AC), RESEARCH.md, TASK-001, TASK-004 |
