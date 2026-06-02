# E5 — Sync / Ingest (`POST /sync`)

| | |
|---|---|
| **Status** | 🔵 ready for dev |
| **Phases** | 3 |
| **Depends on** | E2 |
| **Unblocks** | E6 (recompute), then the briefs |
| **Primary refs** | [`MODELS.md`](../docs/architecture/MODELS.md) "POST /sync" · [`DB.md`](../docs/architecture/DB.md) §1, §6 · [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §3 |

---

## 1. Summary & goal

Implement the **first of the three endpoints**: `POST /sync` — an **idempotent** upsert of HealthKit
deltas (records, workouts + statistics, activity summary) plus the daily **check-in** and the optional
weekly **strength test**. Idempotency is keyed by the HealthKit **`uuid`** so re-syncing overlapping
ranges or retrying never double-inserts ([`MODELS.md`](../docs/architecture/MODELS.md) /sync provenance;
[`DB.md`](../docs/architecture/DB.md) §1 write rule).

`/sync` does **no** readiness computation — that happens in the brief
([`MODELS.md`](../docs/architecture/MODELS.md) SyncResponse). It **does** trigger the `daily_metrics`
recompute for affected dates (E6) ([`DB.md`](../docs/architecture/DB.md) §6).

## 2. Requirements

- **R1** — Request/response models are **camelCase on the wire** (E1 base): `SyncRequest`, `HealthRecord`,
  `Workout`, `WorkoutStat`, `ActivitySummary`, `DailyCheckin`, `StrengthTest`, `SyncResponse`
  ([`MODELS.md`](../docs/architecture/MODELS.md) /sync section).
- **R2** — `HealthRecord` handles **quantity** (`value`+`unit`) and **category** (`category`) samples; the
  `type` is a `RecordType` enum incl. dietary types and `body_mass`
  ([`MODELS.md`](../docs/architecture/MODELS.md) HealthRecord, Enums).
- **R3** — Only **whitelisted** HealthKit types are accepted/stored (shared list with E4)
  ([`DB.md`](../docs/architecture/DB.md) §1).
- **R4** — Upserts: `records`/`workouts` `INSERT … ON CONFLICT(uuid) DO NOTHING`; `activity_summary` upsert
  by `date`; `checkins` upsert by `date`; `strength_tests` upsert by **server-derived** `iso_week`
  ([`DB.md`](../docs/architecture/DB.md) §1, §3, §6; [`MODELS.md`](../docs/architecture/MODELS.md) StrengthTest).
- **R5** — `SyncResponse` makes idempotency **observable**: counts split upserted vs duplicate, plus
  `serverTime` ([`MODELS.md`](../docs/architecture/MODELS.md) SyncResponse).
- **R6** — Payloads are **deltas** (only what's new), not the full baseline
  ([`MODELS.md`](../docs/architecture/MODELS.md) /sync intro).
- **R7** — Check-in is **objective-only** (gi/illness/knee 0–10); **no body-weight field** (weight is the
  HealthKit `body_mass` record) ([`MODELS.md`](../docs/architecture/MODELS.md) DailyCheckin;
  [`DB.md`](../docs/architecture/DB.md) §3).

## 3. What to implement (by phase)

### E5·P1 — Sync wire models & type whitelist
- All request/response Pydantic models per [`MODELS.md`](../docs/architecture/MODELS.md), camelCase.
- `RecordType` enum (incl. `dietary_*`, `body_mass`); quantity vs category handling.
- Shared **type whitelist** module (with E4); reject/ignore non-whitelisted types.

### E5·P2 — Idempotent upsert services + SyncResponse
- Upsert services for `records` (+ zone-minute capture), `workouts` + `workout_statistics`,
  `activity_summary`.
- `ON CONFLICT(uuid) DO NOTHING`; count upserted vs duplicate.
- Wire `POST /sync` (authed) returning `SyncResponse` with `serverTime`.

### E5·P3 — Check-in & strength-test upsert + recompute hook
- Upsert `checkins` by date; upsert `strength_tests` by **derived ISO week** (Europe/Sofia).
- After persisting, **fire the E6 `daily_metrics` recompute** for every affected date.
- `checkinSaved` / `strengthTestSaved` flags in the response.

## 4. Acceptance criteria

- [ ] Posting a `SyncRequest` upserts records/workouts/activity/checkin/test and returns correct
      `recordsUpserted` / `recordsDuplicate` (and the workout/activity/checkin/test flags).
- [ ] **Re-posting the same payload** inserts nothing new — all counts become duplicates (idempotent).
- [ ] Non-whitelisted record types are not stored.
- [ ] A `strengthTest` with a `date` maps to the correct `iso_week`; a second test in the same week
      upserts (one per week).
- [ ] No body-weight field exists on the check-in; weight arrives only as a `body_mass` record.
- [ ] `/sync` performs **no** readiness computation but **does** trigger `daily_metrics` recompute for the
      affected dates (observable via E6 hook / a spy in tests).
- [ ] All responses authenticated; unauthenticated → `unauthorized` envelope.

## 5. Expected outcome

A correct, idempotent ingest endpoint feeding `app.db`, with recompute fan-out wired to E6 — the data tap
the whole coaching loop drinks from.

## 6. Validation

- Model (de)serialization tests (camelCase, quantity vs category, dietary + body_mass).
- Idempotency tests (first sync vs replay; overlapping ranges).
- Whitelist filtering test; ISO-week derivation test; recompute-hook fired-with-right-dates test.

## 7. Out of scope

Computing `daily_metrics` values (E6 owns that; E5 only triggers it), the brief endpoints (E10/E11), the
90-day seed (E4).
