# Adversarial Review — Round 1

**Run:** 2026-06-03 09:43 UTC
**Branch:** feature/e1-p4-local-dev-runner
**Base:** staging
**Commits reviewed:** 8f41407..b9c6c40

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship: the destructive reset recipe can target a different database than the app actually uses.

Findings:
- [high] db-reset ignores the .env-backed database path before deleting files (justfile:48-53)
  `db-reset` derives `DB` from the recipe process environment only, with `APP_DB_PATH` falling back to `app.db`. The app config loads `APP_DB_PATH` from `.env`, and this justfile does not enable dotenv loading, so the normal local flow can have `.env` point at `./dev.db` while `just db-reset` still deletes `app.db` and then runs migrations against the real settings path. That leaves the configured DB unreset and can delete an unrelated local DB. This ad hoc shell guard also diverges from settings validation by only refusing `baseline.db`, not the other forbidden build DB basename.
  Recommendation: Resolve the DB path through the same settings code Alembic/app use, or explicitly enable/export dotenv loading before computing `DB`; mirror the settings forbidden-basename checks and add a regression test/dry-run proving a `.env` APP_DB_PATH override is the file deleted.

Next steps:
- Fix `db-reset` to use the same configuration source as runtime/Alembic before any `rm`.
- Add validation for `.env` override behavior and forbidden DB basenames before marking the local runner done.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | `db-reset` reads `APP_DB_PATH` from process env only — ignores `.env` (the app's source), can delete the wrong DB; guard misses `health.db` | high | fix | Real destructive-mismatch bug. Took Codex's option (b): `set dotenv-load := true` so every recipe resolves `APP_DB_PATH` from the same source the app/Alembic use (process env still wins, matching pydantic-settings precedence), and refuse `health.db` as well as `baseline.db`. Verified `.env` override is the deleted file, process env wins, both forbidden basenames refused. | 21a3930 |
