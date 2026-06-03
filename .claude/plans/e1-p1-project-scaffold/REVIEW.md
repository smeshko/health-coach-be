# Review Summary — e1-p1-project-scaffold

**Rounds:** 4 (3 review + 1 verification)
**Fix commits:** 6508945..b3e08a4

## Rounds

| Round | Findings | Fixed | Deferred | Rejected |
|-------|----------|-------|----------|----------|
| 1     | 2        | 2     | 0        | 1 (sub-rec) |
| 2     | 1        | 1     | 0        | 0        |
| 3     | 2        | 2     | 0        | 0        |
| 4 (verify) | 1   | 1     | 0        | 0        |

## Fixes

### Round 1
- `6508945` — reject blank/whitespace required settings at startup (round-1 #1)
- `dc39e3d` — fix README run instructions + correct `app/core/config.py` → `settings.py` (round-1 #2)

### Round 2
- `2179525` — reject placeholder/weak `api_token` so a copied `.env.example` can't boot (round-2 #1)

### Round 3 (maintainer-approved via AskUserQuestion)
- `8853e66` — reject build (`baseline.db`/`health.db`) and in-memory `app_db_path` targets (round-3 #1)
- `fdd9a56` — pin `pydantic-ai-slim[anthropic]`, drop the full meta-package's provider/worker deps,
  extend the lockfile guard (round-3 #2)

### Round 4 (verification)
- `b3e08a4` — close the SQLite URI query/fragment/scheme bypass in the `app_db_path` guard (round-4 #1)

## Deferred

- None.

## Rejected

- (round-1 #1a) Hard-reject the *exact* `.env.example` placeholder string and impose a token-strength
  policy — rejected the brittle exact-string match; instead round-2 added a sentinel-fragment +
  minimum-length validator (`replace-me`/`changeme`/`example`/… → reject), which catches the placeholder
  without hardcoding it. Token-strength policy beyond a minimum length stays with E1·P2 (where the token
  is actually consumed via `secrets.compare_digest`).

## Notes

- Codex logged a transient `pytest` failure in round 2; not reproducible under `uv run pytest`
  (36 passed) in this environment and not raised as a finding — treated as a sandbox artifact.
- Final state: `uv run pytest` → 36 passed; `uv run ruff check .` clean; `anthropic` present in the lock,
  full `pydantic-ai` meta + all flagged provider/worker packages absent.
