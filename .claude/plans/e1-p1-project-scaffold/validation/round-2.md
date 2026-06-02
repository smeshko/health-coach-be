# Adversarial Validation — Round 2

**Run:** 2026-06-02 21:26 UTC
**Plan:** e1-p1-project-scaffold
**Status at start:** draft
**Prior rounds in scope:** validation/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No ship: most round-1 edits landed, but the plan still leaves the startup fail-fast proof ambiguous and does not actually test the null-vs-absent wire contract.

Findings:
- [medium] [apply] Startup fail-fast still allows a non-factory path (.claude/plans/e1-p1-project-scaffold/tasks/TASK-002-fastapi-app-factory-and-uvicorn-entrypoint.md:13-25)
  Verdict: apply. TASK-002 says `create_app()` may validate settings in a lifespan/startup hook, but its acceptance requires `create_app()` itself to raise when required env is missing. A lifespan-only implementation can leave the factory constructible, and `TestClient` startup/lifespan is easy to bypass unless explicitly context-managed, so the negative smoke may not prove the requested boot-time failure mode.
  Recommendation: Remove the lifespan/startup-hook alternative or require both: construction-time `get_settings()` in `create_app()` and a context-managed startup smoke. Keep the negative assertion specifically on `create_app()` raising.
- [medium] [apply] Optional null-vs-absent behavior is accepted but untested (.claude/plans/e1-p1-project-scaffold/tasks/TASK-004-camelcase-pydantic-base-model.md:24-32)
  Verdict: apply. TASK-004 accepts optional fields being omitted or `null`, but the RED test only asserts casing and wire JSON; TASK-005 also only checks camelCase in/out. Inference from Pydantic behavior: `T | None` without a default accepts `null` but rejects omission, so later wire models can violate MODELS' null-vs-absent contract while all listed checks still pass.
  Recommendation: Add a `CamelModel` sample optional field test that accepts both omitted and explicit `null`, document `Optional` fields as `T | None = None`, and add that check to TASK-005 final validation.

Next steps:
- Patch TASK-002 to make the startup validation location unambiguous.
- Patch TASK-004 and TASK-005 to test optional omitted/null behavior explicitly.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | Startup fail-fast still allows a lifespan-only (non-`create_app`) path | med | apply | Real: removed the lifespan alternative; require construction-time `get_settings()` and assert `create_app()` itself raises | TASK-002 |
| 2 | Optional null-vs-absent accepted but untested (`T \| None` rejects omission) | med | apply | Real: added a `T \| None = None` test (omitted + null), documented the convention, added to final validation | TASK-004, TASK-005 |
