# TASK-005: Final Validation

Depends on: all prior tasks
Suggested commit: `chore: final validation for phase-19-7-profile-yaml-durable-volume`

## Goal

Confirm the plan is fully implemented and production-ready.

## Steps

- [ ] All task checkboxes in `PLAN.md` are ticked
- [ ] Project analyzer/linter passes with no issues
- [ ] `uv run pytest` (full suite) green — includes the TASK-003 override round-trip
- [ ] `uv run ruff check` green
- [ ] `sh scripts/profile_seed_smoke.sh` exits 0 (both seed branches asserted) — paste output
- [ ] AC #1 (no-daemon proof of the durable ENV): `grep -n 'PROFILE_PATH=/data/profile.yaml' Dockerfile`
      shows the `PROFILE_PATH` env-var line (a continuation line of the multi-line `ENV` block, so the
      matched line itself carries no literal `ENV` token), and `grep -n 'COPY .*profile.yaml' Dockerfile` shows the baked seed source
      (L42) is retained — paste both. (The daemon-based `docker run … echo $PROFILE_PATH` proof is the
      optional `docker_boot_smoke.sh` step below.)
- [ ] AC #4 (docs): `git diff RUNBOOK.md .env.docker.example` shows §5 retitled "Resolved (Phase 19.7)"
      with the seed-on-boot/durable-path description + the one-time cutover note + the retained
      profile-backup note, and the `.env.docker.example` comment now says `/data/profile.yaml` — paste the diff
- [ ] (Optional, if a Docker daemon is available) `bash scripts/docker_boot_smoke.sh` green,
      including the fresh-volume `/data/profile.yaml` seed assertion
- [ ] `PLAN.md` acceptance criteria all met, each with its Evidence produced (test output, screenshot, log) — no criterion ticked on "the code looks right"

### Epic update — CROSS-REPO (the Epic 19 tracking doc lives in the iOS repo, NOT here)

- [ ] Do NOT run `link_plan.py` and do NOT edit any `docs/artifacts/epics/*` from this backend
      repo — this is a STANDALONE backend plan whose `Epic:`/`Phase:` fields were set by hand.
- [ ] After the backend PR merges, hand off to the iOS repo: tick Phase 19.7's acceptance in
      `docs/artifacts/epics/19-trustworthy-numbers.md` (iOS repo) and note the PR number there.
      That update happens in the iOS repo, not in this worktree.
