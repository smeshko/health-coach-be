# TASK-001: Dockerfile: default PROFILE_PATH to /data/profile.yaml, keep baked seed source

Depends on: None
Suggested commit: `fix(docker): default PROFILE_PATH to the durable /data volume`

## Goal

Point the runtime constants file at the durable `/data` volume by adding
`ENV PROFILE_PATH=/data/profile.yaml` to the image, while keeping the baked
`/app/profile.yaml` as the seed source, so both the loader and the recompute writer resolve
to durable storage.

## Files

- `Dockerfile` — add `PROFILE_PATH=/data/profile.yaml` to the existing `ENV` block at L61-62
  (currently `ENV APP_DB_PATH=/data/app.db \` + `HOME=/app`). Keep the `COPY … profile.yaml …`
  at L42 unchanged (it stays as the seed source + source-tree anchor). Update the nearby
  comment (L32-35 / L58-60) to note `/app/profile.yaml` is now the seed source and the runtime
  file lives on `/data`.

## Acceptance

- [ ] `docker build` succeeds and the built image reports `PROFILE_PATH=/data/profile.yaml`
      (e.g. `docker run --rm <img> sh -c 'echo $PROFILE_PATH'` → `/data/profile.yaml`).
- [ ] The baked `/app/profile.yaml` still exists in the image (seed source retained).

Evidence: paste the `docker build` tail + the `echo $PROFILE_PATH` output showing
`/data/profile.yaml`, and `docker run --rm <img> ls -l /app/profile.yaml` showing the baked
file present. (If no Docker daemon is available in the run environment, note it and rely on
the TASK-002 shell demo + TASK-003 pytest as the runtime proof that the override path is honored.)

## Steps

### RED
- [ ] N/A (Dockerfile `ENV`/comment change — no unit test harness; verified by build + env echo,
      and downstream by TASK-002/TASK-003). The behavioral proof lands in TASK-002/003.

### GREEN
- [ ] Add `PROFILE_PATH=/data/profile.yaml` to the `ENV` block alongside `APP_DB_PATH`
      (keep the `HOME=/app` continuation).
- [ ] Adjust the constants-file comment to say `/app/profile.yaml` is the baked **seed
      source**, the durable runtime file is `/data/profile.yaml` (seeded on first boot by the
      entrypoint — TASK-002).

### REFACTOR
- [ ] Confirm no other Dockerfile line assumes the runtime file is at `/app` (grep `profile`);
      leave the `COPY` and `VOLUME` lines intact.

## Notes

- Do NOT remove or rename the `COPY … profile.yaml …` line — the entrypoint (TASK-002) reads
  `/app/profile.yaml` as the seed, and it also remains the `_default_profile_path()` fallback
  for any non-container `uv run` inside the image.
- Non-root: `/data` is already `chown app:app` (L56); no ownership change needed here.
