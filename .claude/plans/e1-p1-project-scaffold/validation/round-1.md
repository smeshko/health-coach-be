# Adversarial Validation — Round 1

**Run:** 2026-06-02 21:21 UTC
**Plan:** e1-p1-project-scaffold
**Status at start:** draft

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: working tree diff
Verdict: needs-attention

No ship: the plan has executable-contract gaps that can make the scaffold fail or drift from the documented architecture before any source code exists.

Findings:
- [medium] [apply] TestClient validation is not supported by the dependency allowlist (.claude/plans/e1-p1-project-scaffold/tasks/TASK-002-fastapi-app-factory-and-uvicorn-entrypoint.md:19-21)
  Verdict: apply. TASK-002 requires constructing FastAPI's TestClient, but the dependency allowlist in TASK-001 excludes httpx, which Starlette/FastAPI TestClient requires in a clean environment. The plan can fail at the first app-factory test despite following its own kept-stack dependency list.
  Recommendation: Change TASK-001 and TASK-002: either add httpx as a dev-only test dependency and update the allowlist, or remove TestClient from acceptance and validate OpenAPI directly from the FastAPI app.
- [medium] [apply] Settings are not guaranteed to fail fast at startup (.claude/plans/e1-p1-project-scaffold/tasks/TASK-003-typed-settings-module-loaded-from-environment.md:17-23)
  Verdict: apply. The plan says settings are validated at startup, but TASK-003 acceptance only proves Settings/get_settings behavior in isolation. Nothing requires create_app or the uvicorn entrypoint to load settings, so missing api_token/app_db_path can remain hidden until later auth or DB code touches config, violating E01 R2's startup-validation contract.
  Recommendation: Change PLAN.md, TASK-002, TASK-003, and TASK-005 to require startup/lifespan config validation, plus a negative uvicorn/create_app smoke that fails clearly when required env vars are absent.
- [medium] [apply] Python 3.13 is described as pinned but pyproject allows newer runtimes (.claude/plans/e1-p1-project-scaffold/tasks/TASK-001-initialize-uv-project-pin-python-3-13-declare-deps-create-package-layout.md:11-14)
  Verdict: apply. TASK-001 tells implementers to write requires-python = ">=3.13", which is a floor, not a pin. CI or deployment can resolve under 3.14+ while still satisfying the task, undermining ARCHITECTURE section 1's Python 3.13 runtime and the plan's own version-drift mitigation.
  Recommendation: Change PLAN.md, TASK-001, and TASK-005 to require `requires-python = ">=3.13,<3.14"` or `==3.13.*`, and add a final validation command that records `python --version` from `uv run`.
- [medium] [apply] CamelCase JSON serialization criterion is internally inconsistent (.claude/plans/e1-p1-project-scaffold/tasks/TASK-004-camelcase-pydantic-base-model.md:13-22)
  Verdict: apply. TASK-004 specifies only alias_generator/populate_by_name/from_attributes, but its acceptance expects model_dump_json to emit camelCase. In Pydantic, aliases are not guaranteed for raw JSON dumps unless serialization is explicitly configured or by_alias=True is passed, so the wire casing contract can silently regress to snake_case outside FastAPI's response handling.
  Recommendation: Change TASK-004 and TASK-005 to make JSON aliasing explicit: require alias serialization configuration or `model_dump_json(by_alias=True)`, and add a FastAPI route/response assertion proving actual wire JSON is camelCase.
- [medium] [apply] Final validation does not explicitly cover every PLAN acceptance criterion (.claude/plans/e1-p1-project-scaffold/tasks/TASK-005-final-validation.md:12-19)
  Verdict: apply. TASK-005 has concrete checks for sync, deps, uvicorn, and package imports, but settings failure and camelCase behavior are only covered indirectly by `uv run pytest` and the circular `PLAN.md acceptance criteria all met` checkbox. That is not an observable final-validation contract; weak or missing tests could still let the plan be marked complete.
  Recommendation: Change TASK-005 to enumerate the missing acceptance checks by command/test name: required-env failure, successful env load, snake_case and camelCase model input, camelCase JSON output, and importability.

Next steps:
- Patch the plan files named in the apply recommendations before implementing the scaffold.
- Re-run this review after TASK-005 has concrete, non-circular validation steps for each PLAN.md acceptance criterion.

## Triage

| # | Finding | Severity | Verdict | Rationale | Applied to |
|---|---------|----------|---------|-----------|------------|
| 1 | TestClient needs `httpx`, excluded by the dep allowlist | med | apply | Real: FastAPI `TestClient` requires `httpx`; add it as a dev dep so TASK-002 tests run | TASK-001, TASK-002 |
| 2 | Settings not guaranteed to fail fast at startup (E01 R2) | med | apply | Real: isolation-only test lets missing env hide; wire config load into app startup + negative smoke | PLAN.md:Acceptance, TASK-002, TASK-003, TASK-005 |
| 3 | `>=3.13` is a floor, not a pin (version drift) | med | apply | Real: bound to `>=3.13,<3.14` to honour the runtime + the plan's own mitigation | PLAN.md:Scope, TASK-001, TASK-005 |
| 4 | camelCase JSON not guaranteed without explicit aliasing | med | apply | Real: assert real wire JSON (FastAPI route or `by_alias=True`) so casing can't silently regress | TASK-004, TASK-005 |
| 5 | Final validation doesn't cover every acceptance criterion | med | apply | Real: enumerate concrete checks (env-fail, env-load, both-casing in, camelCase out, importability) | TASK-005 |
