# TASK-004: RUNBOOK §5 + .env.docker.example: Known limitation -> Resolved (Phase 19.7)

Depends on: TASK-001, TASK-002
Suggested commit: `docs(runbook): mark profile.yaml durability resolved (Phase 19.7)`

## Goal

Update the operator docs to reflect the fix: RUNBOOK §5 changes from "Known limitation" to
"Resolved (Phase 19.7)" describing seed-on-boot + the durable path, records the one-time
cutover step, and keeps the profile-backup note as still-true; `.env.docker.example`'s stale
default comment is corrected.

## Files

- `RUNBOOK.md` §5 (L152-170) — retitle to `## 5. Resolved: profile.yaml durability (Phase 19.7)`.
  Keep the two Phase 19.5 integrity properties. Replace the "Redeploy can still lose a
  successful write" paragraph + "Mitigation / follow-up" with: the runtime file now lives at
  `PROFILE_PATH=/data/profile.yaml` on the durable volume; the entrypoint seeds the baked
  `/app/profile.yaml` default only when `/data/profile.yaml` is absent (idempotent, never
  clobbers a recomputed file); a redeploy therefore preserves the file. Retain the
  `com.coachapp.profile-backup` / litestream note as defense-in-depth (still true).
- `RUNBOOK.md` §5 — add a short **one-time cutover** note (see Notes) for the first 19.7 deploy.
- `.env.docker.example` L28-29 — fix the comment "PROFILE_PATH defaults to the image's
  /app/profile.yaml" → it now defaults to `/data/profile.yaml` (the durable volume, seeded on
  first boot); keep the example override line.

## Acceptance

- [ ] RUNBOOK §5 header reads "Resolved" / "Phase 19.7" and describes seed-on-boot + durable path.
- [ ] The one-time cutover step is documented (copy live `/app/profile.yaml` or latest
      profile-backup snapshot into `/data/profile.yaml`, or run one `?refresh=true`, at cutover).
- [ ] The profile-backup / litestream note is retained (not deleted) as still-true.
- [ ] `.env.docker.example` comment reflects the `/data/profile.yaml` default.

Evidence: `git diff RUNBOOK.md .env.docker.example` showing the retitled §5, the cutover note,
and the corrected env comment.

## Steps

- [ ] Rewrite RUNBOOK §5 per Files (retitle, replace the redeploy-loss paragraph, keep the two
      19.5 properties + the backup note).
- [ ] Add the one-time cutover paragraph.
- [ ] Correct the `.env.docker.example` default comment.

## Notes

- One-time cutover rationale (also the plan's open risk): an existing prod `/data` volume has no
  `/data/profile.yaml` yet, so the first 19.7 redeploy seeds the *baked* default — which may be
  older than the `/app` file recompute had been rewriting under the old ephemeral behavior. This
  is the same one-time loss the old limitation risked on every redeploy, and the LAST time it can
  happen. The cutover step (copy the live file / latest backup, or force one `?refresh=true`)
  prevents it.
- Keep §5's numbering/anchors stable if other docs link to it.
