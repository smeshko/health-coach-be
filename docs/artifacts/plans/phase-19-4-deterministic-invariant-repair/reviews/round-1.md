# Adversarial Review — Round 1 (post-implementation)

**Run:** 2026-07-13 19:20 UTC
**Branch:** fix/phase-19-4-deterministic-invariant-repair
**Base:** staging
**Commits reviewed:** 9bac074..0c2e584
**Reviewer:** Codex

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship yet: canonicalization strands valid legacy cache rows, and the supposedly correct-when-reachable zone merge still fails for downward max-HR changes.

Findings:
- [medium] Canonicalization makes previously accepted cache rows unreachable (app/api/schemas/weekly.py:113-117)
  The staging validator accepted and preserved keys such as `2026-W1`, so production may already contain them. This change rewrites every request to `2026-W01`, but cache lookup, refresh deletion, and prior-focus lookup still use exact textual equality and no migration or alias fallback exists. A post-deploy request therefore misses the existing plan and creates a second row for the same logical week; refresh leaves the legacy row behind. Generating W02 after a legacy W1 row also misses W1's focus and cold-starts to threshold, potentially repeating threshold in consecutive in-order plans.
  Recommendation: Migrate existing `plans.iso_week` values transactionally to canonical keys, resolving collisions, or temporarily make cache/delete/prior-week reads recognize legacy aliases. Add a deployment-compatibility test seeded with an unpadded pre-change row.
- [medium] Downward max-HR changes can still abort the zone merge (app/core/weekly_planner.py:341-350)
  The branch updates `max_hr`, `rhr_baseline`, and zones but retains other dependent thresholds. `Thresholds` requires `easy_hr_cap < max_hr`; with the current profile's cap of 146, an injected or future measured max HR of 145 produces valid computed zones but fails `Profile.model_validate`, aborting weekly generation. Similar invalid anchor pairs fail when the new RHR is not below max HR. Thus the branch is only valid for the upward test case, not generally correct when reached.
  Recommendation: Define and enforce an anchor-admission policy before merging. Either reject/ignore invalid measured anchors without failing plan generation or atomically rederive every dependent threshold, including `easy_hr_cap`. Add downward-max and max-at/below-RHR regression tests.

Next steps:
- Add legacy ISO-week key migration or compatibility reads before deployment.
- Harden the zone merge against dependent-threshold violations and test downward anchor movement.

## Triage

Both verified against current code (`Thresholds._hr_cadence_consistent` enforces
`easy_hr_cap < max_hr`; the request validator accepted unpadded keys pre-change).

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Canonicalization strands pre-existing unpadded `plans.iso_week` rows → duplicate plan / cold-started focus | med | fix | Real deploy-compat gap; data migration `0004` canonicalizes existing rows (collision-safe, keeps newest) + migration tests | 2c43095 |
| 2 | Inadmissible rederived anchor (downward max_hr < easy_hr_cap, or rhr ≥ max_hr) aborts weekly generation via `model_validate` | med | fix | Real: "correct-when-reachable" held only for upward moves; the merge now falls back to current zones on `ValidationError` (still re-validates cadence), `zones_changed=False`, verified RED | 1e102aa |
