# Adversarial Review — Round 3

**Run:** 2026-06-03 09:58 UTC
**Branch:** feature/e1-p4-local-dev-runner
**Base:** staging
**Commits reviewed:** 8f41407..d24dacf
**Prior rounds in scope:** reviews/round-1.md, reviews/round-2.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the destructive reset still does not resolve .env the way the app does, so the round-1 wrong-database deletion risk is not fully fixed.

Findings:
- [high] db-reset hand-parses .env and can still delete/reset the wrong DB (justfile:55-70)
  The app loads .env through pydantic-settings/python-dotenv, but this recipe only recognizes bare lines matching APP_DB_PATH= with no spaces/export prefix and then strips only surrounding quotes. Valid dotenv forms such as `export APP_DB_PATH=./dev.db` or `APP_DB_PATH = ./dev.db` are accepted by the app but ignored here, causing db-reset to fall back to `app.db`; comment-bearing values are also retained as part of the path. The result is that a developer can run `just db-reset` against a configured runtime DB and silently delete/reset a different local DB or leave the real DB stale. This is the same destructive trust-boundary mismatch prior rounds were trying to close, just moved into the parser.
  Recommendation: Stop parsing .env with grep/sed. Resolve APP_DB_PATH via the same code/parser as runtime, e.g. a small Python helper using python-dotenv/pydantic-settings and the shared DB validation/normalization before any rm. Add regression checks for `export APP_DB_PATH=...`, whitespace around `=`, trailing comments, quoted values, process-env precedence, and forbidden basename variants.

Next steps:
- Replace the shell .env parser with a shared Python resolution path before deletion.
- Add the dotenv-format regression cases to the db-reset validation evidence from rounds 1 and 2.

## Triage

This is the third round on the same `db-reset` `.env` resolution — the signal to stop patching the shell
parser and do what Codex recommended each round: resolve via the **exact runtime parser**.

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Shell `sed` parser misses dotenv forms the app accepts (`export`, spaces around `=`, trailing comments) → wrong DB | high | fix | Definitive fix: resolve through the same parser the app uses — pydantic-settings reads `.env` via python-dotenv's `dotenv_values` — plus the shared `app.core.settings` forbidden-basename guard, so there is no longer any "format the app accepts but db-reset doesn't" gap. Verified `dotenv_values` output equals the real `Settings` parse for export/spaces/comment/quoted, and the recipe deletes the right file across all forms + precedence + forbidden/URI variants. | 243b379 |
