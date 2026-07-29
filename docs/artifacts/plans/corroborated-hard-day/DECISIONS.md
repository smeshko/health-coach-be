# Decisions: Corroborated hard-day classification

Date: 2026-07-28

Four decisions weighed ≥2 real options during the planning grill (1–4); three more were
added during adversarial validation (5–7, see `validation/round-1.md`). Together they revise
archived Decision 3 of `2026-06-04-e6-p1-per-day-recompute` (pure type/duration predicate).

---

## Decision 1 — Corroboration signal

### Options Considered

1. Effort score only (`workouts.effort_score`) — simplest, no HR plumbing.
2. Either effort or zones — use all available data, fall back when both absent.
3. Per-workout zone computation only.

### Dependencies

`effort_score` is nullable and backfill-only; HR records exist independently of the
workout row; `hard_day` must remain a real 0/1.

### Selected Option

Option 2 — either signal confirms hard: (`effort_score >= 7` AND duration ≥ 20 min) OR
in-window z4+z5 ≥ 15 min. Thresholds pinned as constants (`HARD_EFFORT_MIN = 7.0`,
`HARD_EFFORT_MIN_DURATION_MIN = 20.0`, `HARD_Z45_MIN = 15.0`).

### Rationale

Each signal alone has coverage gaps (effort often null; HR sometimes not worn). Using
either maximizes days where the classifier sees real physiology; the duration guard on the
effort branch stops a short 7-RPE burst from flagging a whole day.

### Rejected Options

- Effort only — falls back to the label heuristic too often.
- Zones only — misses strap-less sessions where the user did log effort.

---

## Decision 2 — Symmetric promotion vs demotion-only

### Options Considered

1. Demotion only — signals can only clear a typed (HIIT/boxing/…) match.
2. Symmetric — signals also promote an untyped workout day to hard.

### Dependencies

DB.md §2 defines `hard_day` as "boxing/threshold/VO₂/long/HIIT", but threshold/VO₂ runs
arrive typed `running` — unreachable by the label set.

### Selected Option

Option 2 — symmetric.

### Rationale

Same constants, same code path, and it implements what DB.md already documents. The
inverse bug (hard run classified light) is as real as the reported one.

### Rejected Options

- Demotion only — leaves a documented class of hard days permanently misclassified for a
  marginal reduction in diff size.

---

## Decision 3 — In-window vs day-total zone minutes

### Options Considered

1. Day-total `z4_min + z5_min` ≥ 15, gated on some HR sample overlapping the workout.
2. In-window per-workout crediting: only HR samples overlapping the workout's
   start–end window count, reusing `_bucket_zone` + the interval/instant credit helpers.

### Dependencies

Decision 2 (promotion) raises the stakes: day-total z4/z5 earned outside the workout could
confirm an unrelated session. The overlap gate already requires timestamp math.

### Selected Option

Option 2 — in-window, per workout, single highest-priority HR source (same dual-device
rule as `zone_minutes`).

### Rationale

Measures the session itself; immune to z4/z5 earned elsewhere in the day; the "zones
absent" definition (no in-window samples) falls out for free — which also prevents wrongly
demoting a hard session recorded without HR coverage (manual log, dead battery).

### Rejected Options

- Day-total + overlap gate — less new code but cross-contaminates between activities.

---

## Decision 4 — Workout-anchored only

### Options Considered

1. Stay workout-anchored: no workout row → `hard_day = 0`, as today.
2. Day-level fallback: z4+z5 ≥ 15 with no workout still flags hard.

### Dependencies

Raw day-level HR can spike from stress, heat, or sauna; `hard_day` charges a −15 readiness
penalty, so false positives are costly. The user logs real sessions.

### Selected Option

Option 1 — workout-anchored.

### Rationale

Without a workout to anchor it, z4/z5 is too noisy to justify a readiness penalty; scope
stays contained to the classifier.

### Rejected Options

- Day-level fallback — catches untracked sessions but imports HR noise into a scoring
  input; revisit only if untracked hard sessions become common.

---

## Decision 5 — Historical rows: document, don't gate

*Added during validation (round-1 #1).*

### Options Considered

1. Document the real behaviour: no proactive backfill, but a re-sync touching an old day
   reclassifies it.
2. Effective-date guard: the corroborated rule applies only from a pinned cutover date;
   older days keep the legacy type/duration predicate.

### Dependencies

`affected_dates` (`app/services/recompute.py`) buckets **every** submitted workout to its
Sofia day — duplicates included — and `/sync` recomputes that set unconditionally
(`app/api/routes/sync.py`). The original plan's "July 27 stays as-is" was therefore
unenforceable: it described an intention, not a guarantee.

### Selected Option

Option 1 — document, don't gate.

### Rationale

The corroborated rule is the *more correct* one; a historical day being recomputed into a
truer value is an improvement, not a regression. A dated branch inside `hard_day()` would be
permanent dual-path complexity guarding a property nobody needs.

**Known divergence, accepted** (round-2 #1, refined round-3 #2). Two things follow from the
recompute machinery, and both are accepted rather than guarded:

1. **The cascade is ~30 days wide, not one day.** A sync touching day D expands to every
   *existing* `daily_metrics` row in `[D+1, D+29]` (`_expand_forward_window`,
   `daily_metrics_engine.py:678-700`) and runs a full `recompute_day` on each
   (`:852-854`). `hard_day` is recomputed for all of them, so one duplicate payload can
   reclassify up to a month of days whose own workouts were never re-sent.
2. **The stored readiness verdict does not follow.** `recompute_day` never writes
   `PRESERVED_COLUMNS` (`readiness_score`/`band`, owned by E8/E11 — `:803-813`), so a
   flipped `hard_day` on July 27 leaves July 28's stored readiness carrying the old
   `yesterday_hard_day` penalty. This is deliberate: the preserved verdict is the record of
   *what the user was actually told that morning*, and retconning it to match a
   later-improved classifier would destroy that audit trail.

The audit trail is durable by default but **not immutable** — an explicit
`refresh=true` on the daily/weekly brief routes (`app/api/routes/daily.py:106`,
`weekly.py:155`) is a deliberate regeneration path and is out of scope here. The claim this
decision makes is therefore the narrow one: nothing in the *automatic* sync path rewrites a
historical readiness verdict, and no scheduled job re-scores past days under the new rule.

### Rejected Options

- Effective-date guard — freezes known-wrong values forever and leaves the classifier
  carrying two predicates and a magic date for the rest of its life.

---

## Decision 6 — Coverage gate on the zones signal

*Added during validation (round-1 #2).*

### Options Considered

1. Bare presence gate — any in-window HR sample makes zones "present".
2. Coverage gate — zones count as present only when credited in-window minutes reach a
   minimum fraction of the workout's duration.
3. Zones may promote but never block the typed fallback.

### Dependencies

Decision 3 makes "zones absent" the trigger for the typed fallback, so the *absence*
definition carries the whole demotion guard. `zone_minutes` semantics
(`daily_metrics_engine.py:453-482`) turn a single low-zone sample into present, zero-valued
z4/z5 — indistinguishable from a genuinely easy session.

### Selected Option

Option 2 — `HARD_HR_COVERAGE_MIN_FRAC = 0.5`: zones are a *present* signal only when
credited in-window HR minutes ≥ 0.5 × `_duration_minutes(w)` and duration > 0. Promotion
(z4+z5 ≥ 15) stays coverage-independent.

### Rationale

The bare presence gate fails the exact scenario the plan's risk register claims to cover: a
watch that records three warm-up minutes of a hard boxing session and dies would demote it.
A fraction (rather than an absolute minute count) scales correctly across a 20-minute and a
90-minute session. Promotion needs no gate — 15 credited z4/z5 minutes cannot accrue
without real data, so the gate would only ever suppress true positives.

### Rejected Options

- Bare presence — the demotion hole described above.
- Promote-only — simpler and safe, but throws away the classifier's ability to demote a
  mislabelled session on HR evidence alone (a HIIT-typed walk with no effort logged),
  which is half the reported bug.

---

## Decision 7 — Effort validity handled classifier-side

*Added during validation (round-1 #3).*

### Options Considered

1. Classifier-side only: `hard_day()` treats effort outside `[1.0, 10.0]` as absent.
2. Classifier-side **and** ingestion bounds (`Field(ge=1, le=10)` on the sync schema).
3. No change — trust the Apple source.

### Dependencies

`app/api/schemas/sync.py` declares `effort_score: int | None` with no bounds, and
`workouts.effort_score` is an unconstrained nullable `Float`; 99 and -3 are accepted today.
An out-of-range high value promotes an easy workout; a low one suppresses the typed
fallback and demotes a hard one.

### Selected Option

Option 1 — classifier-side only, via `HARD_EFFORT_VALID_RANGE = (1.0, 10.0)`. Invalid or
non-finite values are treated exactly as `NULL`.

### Rationale

The classifier is the component this plan owns, and treating a nonsense value as "no
signal" is the correct local behaviour regardless of what ingestion does. Adding bounds at
`/sync` is an API-contract change that could start rejecting iOS payloads which currently
succeed — a different blast radius, and one worth doing deliberately rather than as a
side-effect of a classifier fix.

### Amendment (round-2 #5)

The classifier-side gate alone is one-way: `_backfill_effort_scores` only writes where the
stored value `IS NULL` (`app/services/workout_upsert.py:87-106`), so once a `99` is stored a
corrected `9` for the same uuid is ignored forever and the workout stays "effort absent"
permanently. TASK-005 therefore extends the backfill guard to treat an **invalid** stored
value as overwritable by a valid incoming one. Ingestion-side *bounds* (rejecting the
payload) remain deferred — repairing our own data is not the same as changing the API
contract.

### Rejected Options

- Classifier + ingestion bounds — right end-state, but widens this plan into the sync
  contract; filed as a follow-up instead.
- No change — the fields are structurally unbounded; "the source is well-behaved" is an
  assumption the classifier does not need to make.
