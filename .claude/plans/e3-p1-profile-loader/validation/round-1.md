# Adversarial Validation — Round 1

**Run:** 2026-06-02 23:40 UTC
**Plan:** e3-p1-profile-loader
**Status at start:** draft

> Note: an earlier attempt during authoring hit a broken codex runtime (HTTP 400 `gpt-image-2` — the
> runtime injected a non-existent image-generation tool). That was worked around with
> `CODEX_DISABLE_IMAGE_GENERATION=1 OPENAI_IMAGE_MODEL=""`, and this round was then run against the
> committed plan via `--base HEAD~1`. The codex output below is real.

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against HEAD~1
Verdict: needs-attention

No-ship: the plan matches the documented fields on paper, but its final validation can still miss schema drift against DB.md §5.

Findings:
- [medium] Final validation does not prove exact DB.md key fidelity (.claude/plans/e3-p1-profile-loader/tasks/TASK-004-final-validation.md:53-57)
  Verdict: apply. Rationale: PLAN.md promises no invented fields and no live/derived values from profile.yaml, but TASK-004 only checks a small banned-name regex and value assertions. An implementation could add a defaulted field such as sleep_hours, z1_min, body_mass, daily_metrics, or nutrition_intake and still satisfy these checks, violating DB.md §5's static/live split and the user's key-fidelity requirement. Plan files: PLAN.md, TASK-001, TASK-004.
  Recommendation: Add final validation that asserts the exact allowed key set for every Profile section and for profile.yaml equals DB.md §5, plus expand the live/derived forbidden list from the DB.md §5 table or replace it with exact schema-key equality.

Next steps:
- Patch TASK-004 and the earlier task acceptance to require an exact schema/profile.yaml key-diff against DB.md §5.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Final validation doesn't prove exact DB.md §5 key fidelity (banned-name regex only) | med | apply | Real: a defaulted extra model field bypasses the regex; pin the exact allowed key set per section as a positive allowlist | TASK-004 |
