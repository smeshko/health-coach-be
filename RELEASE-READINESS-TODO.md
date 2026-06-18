# Release-Readiness TODO — before trusting real data (home MacBook Air server)

Context: single user, single-process FastAPI + SQLite(WAL) on a home MacBook Air, reached over
Tailscale. `app.db` is the **only** durable copy of your data — and the iOS app only ever sends
deltas newer than its stored anchor, so it will **not** re-push history if the backend is wiped.
That makes backup + "never boot empty" the whole game.

Chosen path: **native uvicorn + launchd**, **litestream → Backblaze B2**, **reconcile on boot**.

---

## ✅ Done in code (branch `fix/release-hardening-data-safety`)

**Correctness/robustness fixes (1300 tests pass, ruff clean):**
- **`engine.py`** — `busy_timeout=5000` (no instant `SQLITE_BUSY` 5xx on overlapping requests) +
  `synchronous=NORMAL` (durable under WAL + battery-as-UPS; faster than FULL).
- **`POST /sync`** — post-commit recompute failure now acks `200` with **`recomputeOk:false`**
  instead of 5xx-ing durable, idempotent ingest into a retry loop that blocks the brief.
- **Workouts** — late RPE (`effortScore`) **backfills** onto an already-synced workout when the
  stored score is `NULL` (was silently dropped). Backfill-only — never clobbers an existing score.
  - ⚠️ A *changed* RPE (7→9 edited later) is intentionally NOT overwritten. To switch to
    last-write-wins, drop the `WHERE effort_score IS NULL` guard in
    `app/services/workout_upsert.py::_backfill_effort_scores`.

**Deployment hardening (wired, ready to use):**
- **`scripts/start.sh`** — boot order: restore-if-missing → **refuse-to-boot-empty** → optional
  profile.yaml restore → migrate → **reconcile seed↔sync** → `litestream replicate -exec "uvicorn …"`.
- **`scripts/reconcile_seed.py`** now runs on every boot (idempotent) → resolves the seed↔sync
  double-count durably in the raw tables. **(Decision #4 resolved.)**
- **`scripts/backup_profile.sh`** + `deploy/launchd/com.coachapp.profile-backup.plist` — snapshots
  `profile.yaml` (litestream can't cover YAML) every 6h to an iCloud/external dir.
- **`deploy/launchd/com.coachapp.server.plist`** — LaunchDaemon template, `KeepAlive`, env inline.
- **RUNBOOK.md §2a** — the native install steps.

---

## 🔴 You must do (operator actions — I can't do these for you)

These are config/secrets/infra, not code. Steps + commands are in **RUNBOOK.md §2a / §3**.

1. **Backblaze B2** — create a bucket + application key. (~free at this DB size.)
2. **`brew install benbjohnson/litestream/litestream`** (it's not a venv dependency).
3. **Bootstrap the DB** — `just bootstrap` (creates the seeded `app.db`). The start script
   **refuses to boot** if `app.db` is missing and no replica exists, so this is required first.
4. **Fill every `CHANGEME`** in both plists: paths, `API_TOKEN` (≥16 chars — a placeholder is
   rejected at boot on purpose), `ANTHROPIC_API_KEY`, and `LITESTREAM_*`/`AWS_*` for your B2 bucket.
   Then `launchctl load -w` both (RUNBOOK §2a).
5. **Run the restore drill once** (RUNBOOK §3) — replicate, write a marker, delete the local DB,
   restore, confirm the marker survived. Do this **before** trusting real data.
6. **Keep the laptop awake**: `sudo pmset -c sleep 0 disablesleep 1` (lid-closed needs power + this).

---

## 🟡 Optional follow-ups (not blocking)

- **Offsite profile.yaml** — `backup_profile.sh` writes locally/iCloud; uncomment the `aws s3 cp`
  line (+ `awscli`) to also push it to the B2 bucket.
- **RPE last-write-wins** — if you'd rather corrected RPE overwrite an existing score (see ⚠️ above).
- **Seed-anchor alternative** — instead of boot reconcile, set the phone's first-sync anchor to the
  seed cutoff so there's never any overlap (needs an iOS change; reconcile already handles it server-side).

---

## Verdict
**HIGH risk until items 1–5 are done** (a wipe is total and unrecoverable). After that, **Low–Medium**
for single-user home use.
