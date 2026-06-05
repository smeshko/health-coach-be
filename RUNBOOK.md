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
  the network boundary terminate at the **edge** (a reverse proxy / tailnet); the container
  itself serves plain HTTP on `:8000`. **Never** expose an unauthenticated public surface.
