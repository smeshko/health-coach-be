# Adversarial Review — Round 2

**Run:** 2026-06-03 07:39 UTC
**Branch:** feature/e1-p1-project-scaffold
**Base:** staging
**Commits reviewed:** b8514ee..2179525
**Prior rounds in scope:** reviews/round-1.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the blank-setting fix closes only the empty-string case; the branch still lets the documented example bearer secret become the runtime auth token.

Findings:
- [high] Published placeholder token still passes startup validation (app/core/settings.py:17-36)
  6508945 changed required settings to RequiredStr, but that type only strips whitespace and enforces min_length=1 before api_token is accepted. The exact .env.example value API_TOKEN=replace-me-with-a-long-random-token therefore boots successfully. I disagree with the deferral rationale: E1-P2's auth plan compares requests directly against get_settings().api_token, so shipping this config contract means a copied example .env can become a known bearer token instead of failing fast.
  Recommendation: Add an api_token-specific validator or constrained type that strips, rejects the documented placeholder and other obvious sentinel/example tokens, and enforces an appropriate minimum secret length. Make .env.example use a commented or invalid placeholder, and add negative tests for the placeholder path.

Next steps:
- Block until placeholder/weak api_token validation is enforced in settings and covered by tests.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | `.env.example` placeholder token (`replace-me-with-a-long-random-token`) still passes startup validation | high | fix | Accepted Codex's push-back on the round-1 deferral: api_token is the E1·P2 auth boundary, so a copied example `.env` becoming a live bearer token is a real fail-fast gap. Added an api_token validator (min length + sentinel-fragment rejection) so the placeholder fails fast; verified a copied `.env.example` no longer boots. | 2179525 |

Note on the earlier pytest blip Codex logged: re-running `uv run pytest` in this environment is green (22 passed); the failure was not reproducible and was not raised as a finding.
