# Adversarial Review — Round 1

**Run:** 2026-06-03 07:30 UTC
**Branch:** feature/e1-p1-project-scaffold
**Base:** staging
**Commits reviewed:** b8514ee..832c974

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the scaffold accepts unsafe required configuration and the documented run path does not actually boot a clean checkout.

Findings:
- [high] Required settings accept empty or placeholder secrets (app/core/settings.py:27-30)
  The settings model only requires API_TOKEN and APP_DB_PATH to be present; it does not validate that either value is usable. I verified that API_TOKEN='' and APP_DB_PATH='' construct Settings successfully, and .env.example also supplies a predictable API_TOKEN placeholder. Because this config becomes the auth trust boundary and runtime SQLite path for later routes, a bad deployment can pass startup validation with a known/blank token or blank DB path instead of failing fast.
  Recommendation: Use constrained/validated fields: strip whitespace, require non-empty APP_DB_PATH, require a sufficiently long non-placeholder API_TOKEN, explicitly reject the .env.example value, and add negative tests for blank/placeholder values.
- [medium] README run instructions crash on a clean checkout (README.md:19-26)
  The README's Run section tells users to execute uvicorn directly, but the app is constructed at import time and create_app() requires API_TOKEN and APP_DB_PATH. With no .env or exported vars, the documented command fails with a Settings validation error; the text also points to app/core/config.py, which does not exist. This makes the claimed runnable scaffold fail under the first-run path operators and reviewers will follow.
  Recommendation: Document the required env setup before uvicorn, for example copy .env.example to .env and replace API_TOKEN/APP_DB_PATH or export them inline, and correct the settings path to app/core/settings.py. Add a smoke test or checked command that mirrors the README path.

Next steps:
- Tighten Settings validation for required auth/database configuration.
- Fix README first-run instructions and verify the documented command boots from a clean checkout.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Required settings accept empty/whitespace values (`API_TOKEN=''`, `APP_DB_PATH=''` construct successfully) | high | fix | Real fail-fast gap: the api_token is the E1·P2 auth boundary, so an empty/blank secret passing startup is a security edge case. Strip whitespace + require non-empty on both required fields, with negative tests. | 6508945 |
| 1a | Sub-rec: enforce a long token + reject the exact `.env.example` placeholder string | high | reject/defer | Hardcoding a reject of the documented placeholder is brittle; a token-strength policy belongs with E1·P2 where the token is actually consumed (`secrets.compare_digest`). Non-empty validation here is the in-scope part. | — |
| 2 | README Run section crashes on clean checkout + references non-existent `app/core/config.py` | med | fix | Doc correctness bug: wrong file path and missing env-setup step before `uvicorn`. In scope (README is a TASK-001/002 deliverable). | dc39e3d |
