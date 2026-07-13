# Coach App — Operations Runbook

The single-user deployment shape (ARCHITECTURE §1): **one** `uvicorn app.main:app` process over
**one** `app.db` (SQLite/WAL) on a durable volume, with **litestream** streaming the WAL to
object storage for disaster recovery. This runbook covers **bootstrap → deploy → restore** and
the access posture. (The container is authored in E12·P2; the litestream config in
[`litestream.yml`](./litestream.yml); the e2e smoke in `tests/e2e/test_app_open_smoke.py`.)

---

## 1. Bootstrap (one-time, offline — E4)

Build the read-only corpus and seed the runtime DB so the **first** brief has valid 7/28-day
rollups + 30-day baselines on day one. These are the **E4** scripts (referenced, not redefined
here); run them from the repo root with the project env:

```sh
# Regenerate baseline.db from the HealthKit export (the read-only build input).
uv run python scripts/build_db.py            # export.xml → baseline.db
# Freeze the constitution constants (zones, cadence, thresholds) into profile.yaml.
uv run python scripts/derive_constants.py    # baseline.db → profile.yaml
# Apply Alembic migrations, then copy the trailing ~90 days from baseline.db into app.db's
# ingest tables (so rollups/baselines exist before the first /sync).
uv run python scripts/seed_app_db.py         # → app.db (migrated + seeded)
```

`baseline.db`/`export.xml` are **build inputs only** — never shipped in the image, never opened
at runtime (`Settings` refuses `baseline.db` as `app_db_path`). The durable runtime file is
`app.db` (+ its `-wal`/`-shm` sidecars).

---

## 2a. Deploy — native macOS home server (recommended for a single MacBook)

For a personal box (e.g. a MacBook Air reached over Tailscale), skip Docker and run uvicorn
natively under `launchd`, supervised by litestream. The start script
([`scripts/start.sh`](./scripts/start.sh)) hardens boot against the failure that matters most here
— **`app.db` is the only durable copy and the phone only ever sends go-forward deltas**, so a
silent empty boot is a permanent data hole:

1. **restore** `app.db` from the litestream replica if it is missing,
2. **refuse to boot empty** (never let Alembic create+serve a blank DB),
3. optionally restore `profile.yaml` from its snapshot dir,
4. `alembic upgrade head`,
5. **reconcile** the seed↔sync overlap (`scripts/reconcile_seed.py`, idempotent),
6. `exec litestream replicate -exec "uvicorn …"` so the WAL streams to B2 the whole run.

```sh
brew install benbjohnson/litestream/litestream     # litestream is NOT a venv dep
uv sync                                            # project venv (.venv)
just bootstrap                                     # one-time: build_db → derive_constants → migrate → seed (creates app.db)

# Edit the templates: set every CHANGEME (paths, API_TOKEN ≥16 chars, ANTHROPIC_API_KEY,
# LITESTREAM_*/AWS_* for your Backblaze B2 bucket). profile.yaml backup is a separate job
# (litestream can't replicate YAML — see scripts/backup_profile.sh).
sudo cp deploy/launchd/com.coachapp.server.plist         /Library/LaunchDaemons/
sudo cp deploy/launchd/com.coachapp.profile-backup.plist /Library/LaunchDaemons/
sudo launchctl load -w /Library/LaunchDaemons/com.coachapp.server.plist
sudo launchctl load -w /Library/LaunchDaemons/com.coachapp.profile-backup.plist

# Keep the laptop awake as a server (lid-closed needs power + this):
sudo pmset -c sleep 0 disablesleep 1
```

Logs: `tail -f ~/Library/Logs/coachapp-server.{log,err.log}`. The app binds **loopback only**
(`BIND_HOST=127.0.0.1`), so reach it through your ingress — a **cloudflared tunnel** (custom
domain, TLS at Cloudflare's edge) or a Tailnet (§4). **Run the §3 restore drill once before you
trust it.**

---

## 2. Deploy (the E12·P2 single-process container + the litestream sidecar)

Build + run the single `api` container (it applies migrations on start, then runs one uvicorn
process). Put the seeded `app.db` on the mounted volume; inject config via env (no `.env` in the
image). See [`.env.docker.example`](./.env.docker.example) for the full var set.

```sh
docker build -t coach-app-api .

# A NAMED volume inherits the image's non-root `app` ownership (a host bind-mount must be
# pre-chowned to that uid). Seed app.db into the volume before first boot if bootstrapping.
docker run -d --name coach-app \
  -e API_TOKEN="$API_TOKEN" \
  -e APP_DB_PATH=/data/app.db \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -e LANGFUSE_PUBLIC_KEY="$LANGFUSE_PUBLIC_KEY" \
  -e LANGFUSE_SECRET_KEY="$LANGFUSE_SECRET_KEY" \
  -v coach-app-data:/data \
  -p 8000:8000 \
  coach-app-api
```

**Alongside** the container, run litestream as a sidecar so the WAL streams continuously
(`APP_DB_PATH` must point at the **same** `app.db`, e.g. the volume path / a host mount):

```sh
export APP_DB_PATH=/data/app.db
export LITESTREAM_BUCKET=... LITESTREAM_PATH=coach-app/app.db \
       LITESTREAM_ENDPOINT=... LITESTREAM_REGION=... \
       AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...
litestream replicate -config litestream.yml
```

Health: `GET /health` is unauthenticated (the container HEALTHCHECK / uptime probe). The token
gate is observable via `GET /probe` (`401` without, `200` with the bearer token).

---

## 3. Restore (disaster recovery)

On a fresh disk, rebuild `app.db` from the object-storage replica **before** starting the
container, then deploy as in §2:

```sh
export APP_DB_PATH=/data/app.db
export LITESTREAM_BUCKET=... LITESTREAM_PATH=coach-app/app.db ... AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...
litestream restore -config litestream.yml "$APP_DB_PATH"   # → last-replicated app.db
```

### Replicate → restore drill (validate backup before you need it)

1. `litestream replicate -config litestream.yml &` against a known `app.db`.
2. Write a known marker (e.g. a `/sync` request), wait for a replication cycle.
3. Simulate disk loss: `rm "$APP_DB_PATH" "$APP_DB_PATH"-wal "$APP_DB_PATH"-shm`.
4. `litestream restore -config litestream.yml "$APP_DB_PATH"`.
5. Verify the marker survived (the row is present after restore). ✅

---

## 4. Access posture (ARCHITECTURE §1 Access)

- **One long-lived `API_TOKEN`** (the bearer secret) is the sole auth credential. It is
  **env-only** — never committed (`.env` is gitignored, `.dockerignore`d). Rotate by changing the
  env var and restarting.
- Serve over **HTTPS** and reach the service only on a **private network / Tailscale** — TLS and
  the network boundary terminate at the **edge** (a reverse proxy / tailnet); the app
  itself serves plain HTTP on loopback `127.0.0.1:8000`. **Never** expose an unauthenticated public surface.
- **cloudflared tunnel + custom domain** (the chosen ingress): the app stays bound to loopback and
  cloudflared connects to it locally, so **no port-forwarding / public IP** is needed and TLS
  terminates at Cloudflare. But the tunnel makes the API **publicly reachable** — the bearer token
  is then the *only* thing protecting `/sync` and `/brief/*`. Therefore:
  - use a **long, random `API_TOKEN`** (32+ bytes); the placeholder/weak-token check still applies.
  - put **Cloudflare Access (Zero Trust)** in front of the hostname (service token or email OTP) so
    the origin isn't hittable without passing Cloudflare auth first — restores a private posture and
    adds rate-limiting/WAF. Add a Cloudflare **rate-limit** rule on `/sync` as a backstop.
  - note Cloudflare's edge **sees the token** (TLS terminates there) and free-plan limits: ~100 MB
    request body (first sync is small — fine) and a **100 s origin timeout** (briefs are 3–8 s — fine).

---

## 5. Known limitation: profile.yaml durability (Phase 19.5)

The weekly recompute stages an updated `profile.yaml` (the constants file) and the route
writes it **after** the DB commit. Two integrity properties:

- **Write failure is now safe.** If the write fails after retries, the just-committed plan row
  is invalidated so the next request regenerates and re-attempts the write — a cache hit can
  never silently serve constants that diverge from a failed write (Phase 19.5).
- **Redeploy can still lose a *successful* write.** The Docker image bakes `profile.yaml` into
  the ephemeral `/app` layer, while `app.db` lives on the durable `/data` volume, and
  litestream replicates `app.db` but **not** the YAML (only the 6-hourly
  `com.coachapp.profile-backup` job snapshots it). So a container replacement can restore an
  older `profile.yaml` while keeping the newer committed plan → subsequent cache hits use stale
  constants until the next recompute rewrites the file.

  **Mitigation / follow-up:** move `PROFILE_PATH` onto the durable `/data` volume (with
  entrypoint logic to seed the baked default on first boot), or restore the latest
  profile-backup snapshot after a redeploy. Until then, after any redeploy that might straddle
  a recompute, force a weekly `?refresh=true` to re-stage + re-write the constants.
