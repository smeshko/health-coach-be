# Review Summary — phase-19-4-deterministic-invariant-repair

**Rounds:** 3 (post-implementation)
**Fix commits:** 1e102aa..d77e7d2

## Rounds

| Round | Findings | Fixed | Deferred | Rejected |
|-------|----------|-------|----------|----------|
| 1     | 2        | 2     | 0        | 0        |
| 2     | 1        | 1     | 0        | 0        |
| 3     | 1        | 1     | 0        | 0        |

The stream converged (2 → 1 → 1), each round narrower and all on the same
migration collision-ordering path after the two substantive round-1 fixes.
Round 3 hit the protocol cap; the design was confirmed coherent and the last
finding is a vanishingly-unlikely edge for a single-user app, trivially closed.

## Fixes

### Round 1
- `1e102aa` — the zone-rederivation merge now keeps the current zones (and reports
  `zones_changed=False`) when a rederived anchor would violate a dependent `Thresholds`
  constraint (a downward `max_hr` below `easy_hr_cap`, or `rhr >= max_hr`), instead of
  raising and aborting weekly generation. The fallback still re-validates the base dump, so
  an invalid cadence still raises. Verified RED. (round-1 #2)
- `2c43095` — new alembic migration `0004` canonicalizes any pre-existing noncanonical
  `plans.iso_week` to the padded `%G-W%V` form (D5), so the exact-equality cache / refresh /
  prior-week-focus lookups don't strand a legacy `2026-W1` row. Collision-safe (keeps the
  survivor, drops duplicates → `UNIQUE(iso_week)` holds). (round-1 #1)

### Round 2
- `d93d3bb` — migration `0004`'s collision survivor is chosen by parsing `created_at` into an
  aware UTC instant (not a lexicographic offset-string compare, which mis-ranks across Sofia's
  autumn DST rollback), with the surrogate `id` as a deterministic tie-breaker for
  missing/tied timestamps. Added DST-offset / null / three-alias / empty-idempotent tests.
  (round-2 #1)

### Round 3
- `d77e7d2` — `_sort_key` now requires `utcoffset() is not None`, so a tz-less/date-only
  `created_at` is classified as malformed (id-fallback) rather than read in the migration
  host's local timezone — the survivor is host-independent. Added a tz-less-loses-to-aware
  test. (round-3 #1)

## Deferred

- (none)

## Rejected

- (none)
