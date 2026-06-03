# Adversarial Review — Round 2

**Run:** 2026-06-03 09:51 UTC
**Branch:** feature/e1-p4-local-dev-runner
**Base:** staging
**Commits reviewed:** 8f41407..21a3930
**Prior rounds in scope:** reviews/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the round-1 fix covers the happy-path .env override, but it made all recipes inherit local .env state and the destructive guard is still weaker than the app's Settings validation.

Findings:
- [high] `db-reset` still does not mirror the Settings forbidden-DB guard (justfile:55-58)
  The fix added `health.db`, but the shell guard compares the raw `basename` against lowercase literals. `Settings` lowercases and normalizes the DB target before rejecting `baseline.db`/`health.db`; this recipe does not. On the default macOS case-insensitive filesystem, `APP_DB_PATH=./Baseline.db` or `./HEALTH.DB` skips the case branch and then `rm -f -- "$DB"` can delete the real read-only build DB even though the app would reject that path. The same divergence also leaves URI/query normalization out of the destructive preflight.
  Recommendation: Before any `rm`, normalize the target exactly like `app.core.settings._db_target_basename` or call shared Python code, then reject forbidden basenames case-insensitively including URI/query/fragment variants. Add regression checks for uppercase `baseline.db`/`health.db` and URI forms.
- [medium] Global dotenv loading makes `just test` depend on a developer's local `.env` (justfile:4-6)
  `set dotenv-load := true` is file-wide, so `just test` now starts pytest with every `.env` entry promoted into process env. That defeats the existing test isolation strategy: `tests/test_settings.py` explicitly uses `Settings(_env_file=None)` so local `.env` should be ignored, but `_env_file=None` still reads process env. A local `.env` with `MODEL_ID` changed or `LANGFUSE_PUBLIC_KEY` set can make `test_loads_with_required_env` fail its default/None assertions. The runner's test recipe is no longer deterministic after a normal `just env` + local edits flow.
  Recommendation: Remove global dotenv loading. Resolve `APP_DB_PATH` inside `db-reset` only, preferably via a small Python helper using the same dotenv parser/config normalization, and leave `test`/`lint`/`fmt`/`install` untainted by `.env`.

Next steps:
- Scope dotenv loading to the destructive recipe instead of the whole justfile.
- Make `db-reset` reuse the app's DB target normalization before deletion and test the rejected variants.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | db-reset guard is case-sensitive + not URI-normalized → `Baseline.db`/URI forms bypass it (deletes the build DB on a case-insensitive FS) | high | fix | Real divergence from Settings. Normalize in shell exactly like `_db_target_basename` (drop query/fragment, strip scheme, basename, lowercase) before the forbidden-basename check. Regression checks for uppercase + URI variants. | d24dacf |
| 2 | File-wide `set dotenv-load` taints `just test` with a developer's local `.env` (non-deterministic) | med | fix | Real regression introduced by the round-1 fix. Dropped file-wide dotenv-load; `db-reset` now reads `.env` itself (scoped, process-env-wins precedence) so `test`/`lint`/`fmt`/`install` stay clean. | d24dacf |
