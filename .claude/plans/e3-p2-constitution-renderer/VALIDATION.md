# Validation Summary — e3-p2-constitution-renderer

**Rounds:** 3
**Plan status at validation:** draft
**Run on:** 2026-06-03

## Rounds

| Round | Findings | Applied | Deferred | Rejected |
|-------|----------|---------|----------|----------|
| 1     | 3        | 3       | 0        | 0        |
| 2     | 1        | 1       | 0        | 0        |
| 3     | 0        | 0       | 0        | 0        |

Final Codex verdict: **approve** (round 3, no material findings — stopped on approve, also the 3-round cap).

## Applied

### Round 1
- TASK-004 / TASK-001 / PLAN.md:Risks+AC — fixed a self-contradiction: the live-weight grep banned the
  literal `body_mass`/`current_weight` prose row the verbatim copy must keep; narrowed the ban to weight
  *inside* `{{ }}` placeholders / render args only, allowing the literal §1 prose, and kept the sentinel
  runtime-weight test (round-1 #1).
- PLAN.md:Decisions+Out of Scope, RESEARCH.md — documented that the constitution templates only
  `cadence_target_spm` (the end target) and that `cadence_current_spm` (this month's cue) is deliberately a
  **user-context** input (per-card `cadenceSpm`, computed by code — MODELS.md §427/§617, LLM.md §3), NOT a
  template placeholder. (Codex's first remedy — "add the placeholder" — was the *wrong* fix and would break
  doc fidelity; applied the architecture-correct resolution instead.) (round-1 #2)
- PLAN.md:Decisions+Risks+AC, TASK-001, TASK-004 — strengthened the `.j2`-fork drift-guard from a few
  substring checks to a structural §1–§11 section-presence test plus a `diff`-equivalence check, so a `.j2`
  silently missing whole sections fails (round-1 #3).

### Round 2
- PLAN.md (Decisions/Out of Scope/Risks/AC), RESEARCH.md, TASK-001, TASK-002, TASK-004 — fixed a high-sev
  unsatisfiability the round-1 "byte-identical verbatim copy / diff empty" edit introduced: the root
  `HEALTH-CONSITTUTION.md` has **3 literal explanatory `{{ … }}` prose strings** (lines 11/38/281) that
  Jinja2 cannot parse, so a byte-identical copy raises `TemplateSyntaxError`. Required the `.j2` to wrap
  exactly those 3 in `{% raw %}…{% endraw %}` (they render back to the literal text); made the **parse
  test** the primary structural guard; relaxed the drift-guard to "diff differs only in those 3 escaped
  lines" (stripping the raw tags yields the root `.md` byte-for-byte); and narrowed every "no residual
  placeholder" check to *real* placeholders (`{{ athlete/thresholds/zones/nutrition.* }}`) so the escaped
  literals are allowed (round-2 #1).

## Deferred

- None.

## Rejected

- None. (Round-1 #2's literal first remedy — adding `cadence_current_spm` as a template placeholder — was
  *not* applied because it contradicts the architecture; the finding's underlying gap was nonetheless
  addressed by documenting the intentional target-vs-current split. Recorded as applied-with-corrected-remedy,
  not rejected.)
