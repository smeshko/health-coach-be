# Adversarial Review — Round 4 (verification)

**Run:** 2026-06-03 08:00 UTC
**Branch:** feature/e1-p1-project-scaffold
**Base:** staging
**Commits reviewed:** b8514ee..fdd9a56
**Prior rounds in scope:** reviews/round-1.md, reviews/round-2.md, reviews/round-3.md

> Verification pass to confirm the round-3 fixes held and introduced no regressions (notably the
> dependency-tree change). It confirmed the dep trim and surfaced one incompleteness in the round-3
> `app_db_path` guard — a hole in our own fix, which the verification round exists to catch. Fixed and
> deterministically verified; no further codex round run (the fix is exhaustively checked by enumerated
> tests, not a fishing expedition for new issues).

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

No-ship: the dependency trim appears to remove the named provider/worker packages, but the round-3 DB-path guard is still bypassable via SQLite URI query/fragment forms.

Findings:
- [high] SQLite URI query strings bypass the build-database guard (app/core/settings.py:91-92)
  The validator checks `PurePath(value).name.lower()` on the raw `APP_DB_PATH` string. That catches `sqlite:///baseline.db`, but values such as `sqlite:///baseline.db?timeout=30`, `sqlite:///health.db#frag`, or `file:baseline.db?mode=rwc` leave the query/fragment attached to the basename and pass startup validation. I verified the first and `file:` examples construct `Settings(_env_file=None)` successfully. Because the architecture says Alembic/runtime writes route through this setting and `baseline.db`/`health.db` must never be opened at runtime, a common SQLite URL variant can still target the regenerable corpus.
  Recommendation: Parse/normalize SQLite URL and file-URI forms before checking the target basename, or strip query/fragment components before `PurePath`; add negative tests for `sqlite:///baseline.db?timeout=30`, `sqlite:///health.db#frag`, and `file:baseline.db?mode=rwc`.

Next steps:
- Fix the URI normalization hole in `app_db_path` validation before shipping.
- Rerun targeted settings and lockfile tests after the fix; pytest could not run in this read-only sandbox because no usable temp directory was available.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | SQLite URI query/fragment/scheme forms bypass the round-3 `app_db_path` build-db guard | high | fix | Real hole in our own round-3 fix (a regression the verification round is meant to catch). Normalize scheme + strip query/fragment before resolving the basename; added negative tests for the URI variants. Verified all enumerated bypass forms now reject and valid paths (incl. `sqlite:///app.db`) still pass. | b3e08a4 |

The dep-trim fix (round-3 #2) was confirmed sufficient: `anthropic` present, full `pydantic-ai` meta and
all flagged provider/worker packages absent from `uv.lock`, lockfile guard extended. No regression.
