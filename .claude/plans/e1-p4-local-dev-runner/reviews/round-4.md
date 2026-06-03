# Adversarial Review — Round 4

**Run:** 2026-06-03 10:11 UTC
**Branch:** feature/e1-p4-local-dev-runner
**Base:** staging
**Commits reviewed:** 8f41407..243b379
**Prior rounds in scope:** reviews/round-1.md, round-2.md, round-3.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the round-3 resolver is still not Settings-equivalent, so `db-reset` can delete a different database than the app/Alembic target.

Findings:
- [high] db-reset ignores case-insensitive APP_DB_PATH names that Settings accepts (justfile:56)
  `Settings` uses pydantic-settings with default case-insensitive env matching, but this resolver only checks exact uppercase `APP_DB_PATH` in `os.environ` and raw `dotenv_values`. I verified `Settings(_env_file=None)` accepts `app_db_path=./lower.db` and `App_Db_Path=./mixed.db`, while this resolver falls back to `app.db`. With such an override, `db-reset` deletes `app.db`, then `just migrate` runs against the app's real configured DB, leaving stale state and potentially deleting an unrelated local DB.
  Recommendation: Resolve through `Settings()` itself, or through the same pydantic-settings Env/DotEnv sources with case folding, and remove the manual exact-key lookup. Add regression checks for lower/mixed-case process env and `.env` keys.

Next steps:
- Replace the one-line resolver with a Settings-equivalent helper before any `rm`.
- Add destructive-path regression coverage for case-insensitive env and dotenv key names.

## Triage

This is the fourth round on `db-reset` resolution — each round Codex (correctly) said "resolve through
Settings itself." Done definitively now.

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Resolver missed case-insensitive env keys (`app_db_path`/`App_Db_Path`) that Settings accepts | high | fix | Stopped reimplementing pydantic-settings. Resolve via a tiny `BaseSettings` that **reuses `Settings.model_config`** (heredoc-delivered; `just` dedents shebang bodies), so .env parsing, case-folding, and process-env>.env precedence are byte-identical to runtime — no reimplementation gap can remain. Shared forbidden-DB guard runs before any rm. Verified 8/8: upper/lower/mixed env + .env keys, all dotenv forms, precedence, forbidden/URI variants, empty, unset. | 8eeff7a |
