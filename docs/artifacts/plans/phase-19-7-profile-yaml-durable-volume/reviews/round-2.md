# Adversarial Review — Round 2

**Run:** 2026-07-14 05:54 UTC
**Branch:** fix/phase-19-7-profile-yaml-durable-volume
**Base:** origin/staging
**Commits reviewed:** 34debd3..cdbb17f (includes round-1 fixes 688b6d7, cdbb17f)
**Prior rounds in scope:** reviews/round-1.md
**Reviewer:** subagent (Codex still usage-limited until Jul 20 — clean general-purpose subagent, same fallback as round 1)

## Codex output

<!-- Reviewer was a general-purpose subagent (Codex unavailable). Output pasted verbatim below. -->

I have everything I need. Both fixes verified working; let me summarize the round-2 findings.

## Round-2 Review — Phase 19.7 profile.yaml durable volume

**Verdict: both round-1 fixes are correct and sufficient. No regressions. Reject #3 was defensible. Nothing blocking; four low/informational notes below.**

Verification performed:
- Smoke test `sh scripts/profile_seed_smoke.sh` → **7/7 PASS, exit 0** on this BSD/macOS laptop, so `mktemp "${PROFILE_PATH}.seed.XXXXXX"` accepts a full-path template on BSD.
- Container base is `python3.13-bookworm-slim` (Debian → dash + GNU coreutils `mktemp`), which also accepts a full-path template. So Fix #1 works on **both** the dev-laptop (BSD) and container (GNU) mktemp.
- Strengthened round-trip `test_write_profile_default_path_honours_env_override` → **passed** (`uv run pytest`).

### Fix #1 (atomic seed) — sufficient
- Runs as a subprocess (`sh /app/scripts/seed_profile.sh`), so its `trap … EXIT` is process-isolated — it **cannot clobber a caller trap** (entrypoint's flow is untouched).
- Under `set -e`, a failing `cp`/`mv` fires the EXIT trap (`rm -f "$tmp"`), and dash preserves the triggering non-zero status — **the failure is not masked**, seed still fails loud.
- `mv` is truly atomic: temp is `${PROFILE_PATH}.seed.XXXXXX` = same dir (`/data`) → same filesystem → `rename(2)`. Correct.
- Self-heal holds: an interrupted seed never lands a partial file *at* `PROFILE_PATH`, so the `[ ! -f ]` guard re-seeds cleanly next boot.

### Fix #2 (RUNBOOK two-step docker cp) — correct
`docker cp <old>:/app/profile.yaml ./profile.yaml` then `docker cp ./profile.yaml <new>:/data/profile.yaml` is runnable and lands on the durable volume (docker cp writes through a VOLUME mount). It correctly overwrites a default the entrypoint already seeded. Also semantically right: pre-19.7 the recompute wrote to the anchor `/app/profile.yaml`, so `<old>:/app/profile.yaml` *is* the live file.

### Findings (all low / informational)

1. **Stray temp leak on untrappable SIGKILL** — low · `scripts/seed_profile.sh:31-32`. If the container is `SIGKILL`/OOM-killed between `cp` and `mv`, the EXIT trap can't fire (SIGKILL is untrappable), leaving a truncated `/data/profile.yaml.seed.XXXXXX` on the durable volume forever; repeated interrupted boots accumulate them. **Not a correctness bug** — `PROFILE_PATH` self-heals, and I confirmed nothing consumes the strays: `backup_profile.sh` copies the *exact* `$PROFILE_PATH` (no glob), litestream is SQLite-only, and no code globs `/data`. Cosmetic leak only.

2. **RUNBOOK cutover has a boot→cp window** — low · `RUNBOOK.md:174-183`. To `docker cp` into `<new-container>` the container must already exist, so its entrypoint has *already* seeded the baked default. The cp overwrite is fine, but in the window between boot and the operator's cp a recompute could run; worse, if a recompute *writes* in that window the cp would overwrite the fresher file with the older `/app` copy. Single-user/operator-controlled, so negligible — but consider steering operators to the `?refresh=true` alternative (already documented) as the safer default, or adding "do this immediately after boot / before serving traffic."

3. **Reject #3 (bind-mount /data) is defensible** — informational. Confirmed the shipped topology is a **named** volume (`VOLUME ["/data"]` + image `chown app:app /data`), whose root ownership Docker initializes to the app user, and in the actual redeploy case `/data` is already app-owned (app.db lives there). The bind-mount-with-mismatched-uid case is unsupported and fails loud, not silent. Agree with reject; an optional one-line doc caveat ("a bind-mounted `/data` must be app-writable") would fully close the gap between the script header's "non-root-safe" claim and reality.

4. **Self-heal path is untested** — low · `scripts/profile_seed_smoke.sh`. The smoke test covers both happy branches (seed / no-clobber / idempotent) but not the interrupted-seed → re-seed self-heal that Fix #1 is *about*. Argued, not demonstrated. Acceptable (hard to simulate a mid-copy kill in a shell test).

Non-issue noted in passing: `mktemp`+`mv` gives the seeded file mode `0600` vs the old `cp`'s `~0644`. Harmless — it matches `write_profile`'s own mkstemp+`os.replace` output, and the app is the sole owner/reader/writer.

## Triage

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | Stray truncated `.seed.XXXXXX` temp leaks on untrappable SIGKILL between cp and mv | low | reject | Not a correctness bug (reviewer confirmed): `PROFILE_PATH` self-heals and nothing on `/data` is globbed/consumed (`backup_profile.sh` copies the exact path, litestream is SQLite-only). Cosmetic-only; closing an untrappable-SIGKILL window is not worth added complexity. | |
| 2 | RUNBOOK cutover has a boot→operator-`cp` window where a recompute could be overwritten | low | defer | Single-operator, self-hosted deployment makes this negligible, and the doc already offers the safer `?refresh=true` alternative. A one-line "do this before serving traffic" nicety is worth capturing but out of scope for this fix branch. | |
| 3 | Optional doc caveat that a bind-mounted `/data` must be app-writable | low | reject | Confirms/agrees with round-1 #3 (already rejected). Shipped topology is a named volume; bind-mount-with-mismatched-uid is unsupported and fails loud. No new action. | |
| 4 | Interrupted-seed → re-seed self-heal path is not covered by the smoke test | low | reject | Reviewer deems it acceptable: the atomic design means a partial seed never lands at `PROFILE_PATH`, so self-heal reduces to the already-covered fresh-path branch A; simulating a mid-`cp` kill in a shell test is impractical for negligible value. | |

**Outcome:** no `fix` rows in round 2 — both round-1 fixes verified sufficient with no regressions. Per the shared protocol (round 2 yields only defer/reject → done), no round 3.
