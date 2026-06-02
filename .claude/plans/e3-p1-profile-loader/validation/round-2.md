# Adversarial Validation — Round 2

**Run:** 2026-06-02 23:45 UTC
**Plan:** e3-p1-profile-loader
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

reject: TASK-004 still leaves the root Profile key set unpinned, so a defaulted top-level field can bypass the DB.md §5 fidelity check.

Findings:
- [medium] Root Profile keys are not covered by the positive allowlist (.claude/plans/e3-p1-profile-loader/tasks/TASK-004-final-validation.md:49-57)
  The new check enumerates exact key sets for Athlete/Thresholds/Zones/Nutrition/CarbsPerKg/Meta, but it never requires `set(Profile.model_fields) == {"athlete", "thresholds", "zones", "nutrition", "meta"}`. A defaulted top-level field such as `daily_metrics` or `body_mass` on `Profile` would not appear in input YAML, would not be rejected by section-level `extra="forbid"`, and would not be caught by these nested section key checks. Impact: DB.md §5's exact static-vs-live contract can still drift at the root model.
  Recommendation: Extend the keyset test to assert the root `Profile.model_fields` exactly equals the five DB.md §5 top-level sections, and optionally assert the shipped `profile.yaml` top-level keys match the same set.

Next steps:
- Patch TASK-004 to include the root Profile keyset equality alongside the nested section keyset checks.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Root `Profile.model_fields` not pinned (only nested sections) | med | apply | Real: a defaulted top-level field bypasses nested keyset + section `extra=forbid`; added a root keyset equality + top-level yaml key assertion | TASK-004 |
