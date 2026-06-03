# Adversarial Review — Round 3

**Run:** 2026-06-03 07:50 UTC
**Branch:** feature/e1-p1-project-scaffold
**Base:** staging
**Commits reviewed:** b8514ee..2179525
**Prior rounds in scope:** reviews/round-1.md, reviews/round-2.md

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the prior blank/placeholder token fixes are present, but the scaffold still leaves a DB-path corruption footgun and violates the kept-stack dependency contract.

Findings:
- [high] APP_DB_PATH can target the disposable baseline database (app/core/settings.py:48)
  The only validation on app_db_path is RequiredStr, so values like baseline.db, ./baseline.db, :memory:, or a SQLite memory URI pass startup. This is a load-bearing config value: the architecture says baseline.db is a read-only build input never opened at runtime, and the E2 plan routes Alembic/runtime DB access directly through settings.app_db_path. A bad env value would therefore let migrations or runtime writes hit the regenerable baseline corpus instead of app.db, causing silent data corruption or data loss.
  Recommendation: Add an app_db_path validator that rejects baseline.db/health.db by resolved basename, rejects SQLite in-memory paths/URIs, and keeps tests proving those values fail before create_app() returns.
- [medium] Full PydanticAI package pulls all optional provider and worker-adjacent deps (pyproject.toml:14)
  The direct dependency is pydantic-ai, whose locked package depends on pydantic-ai-slim with every optional extra enabled. The resulting environment contains unused provider and integration packages including boto3/botocore, cohere, fastmcp/mcp, google-genai, groq, huggingface, logfire, mistralai, openai, temporalio, and xai-sdk. That contradicts the scaffold's kept-stack posture of Claude via PydanticAI in one synchronous process, and materially expands supply-chain, deployment, and version-skew risk before any code uses those integrations.
  Recommendation: Replace pydantic-ai with the minimal package/extras needed for Claude, for example pydantic-ai-slim[anthropic] if compatible, regenerate uv.lock, and extend the lockfile guard to fail on unused provider/MCP/Temporal-style packages.

Next steps:
- Block shipping until app_db_path rejects known destructive/non-durable targets.
- Trim the PydanticAI dependency to the minimal Anthropic-capable surface and update the lockfile allowlist test.

## Triage

Both findings are new (not raised in rounds 1–2), grounded in the architecture docs, and have cross-epic
impact (E2 routes DB access through `app_db_path`; E9 imports PydanticAI). Per the review-plan round-3
rule they were surfaced to the maintainer via AskUserQuestion, who chose **fix both**.

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | `app_db_path` accepts `baseline.db`/`health.db` + `:memory:` (read-only build input / non-durable) | high | fix | Confirmed in ARCHITECTURE §1 + DB.md: `baseline.db` is read-only, never opened at runtime; E2 writes through this path. Added a validator rejecting those basenames + in-memory paths/URIs, with tests. Maintainer chose "Fix now". | 8853e66 |
| 2 | Full `pydantic-ai` pulls temporalio/openai/boto3/cohere/groq/mistralai/google-genai/mcp/fastmcp/logfire/xai-sdk into the lock | med | fix | Confirmed present in the lock; contradicts the Claude-only, one-process kept stack (ARCHITECTURE §1). Pinned `pydantic-ai-slim[anthropic]` (keeps `anthropic`, drops the rest), regenerated `uv.lock`, extended the lockfile guard. Maintainer chose "Switch to slim[anthropic]". | fdd9a56 |
