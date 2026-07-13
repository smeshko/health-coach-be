# Adversarial Review — Round 3 (post-implementation)

**Run:** 2026-07-13 19:52 UTC
**Branch:** fix/phase-19-4-deterministic-invariant-repair
**Base:** staging
**Commits reviewed:** 9bac074..d93d3bb
**Prior rounds in scope:** reviews/round-1.md, reviews/round-2.md
**Reviewer:** Codex

## Codex output

<!-- Paste /codex:adversarial-review stdout verbatim below this line. Do not edit. -->

# Codex Adversarial Review

Target: branch diff against staging
Verdict: needs-attention

Do not ship yet: d93d3bb fixes offset-aware DST ordering, but timezone-less timestamps still receive host-dependent instants and can cause irreversible deletion of the legitimate collision survivor. The other prior-round fixes appear coherent.

Findings:
- [medium] Naive timestamps are treated as real, host-local instants (alembic/versions/0004_canonicalize_plans_iso_week.py:45-50)
  `datetime.fromisoformat(created_at).astimezone(UTC)` accepts timezone-less and date-only strings, interpreting them in the migration host's local timezone instead of classifying them as malformed. For example, a malformed `2026-01-06T01:00:00` outranks a legitimate `2026-01-06T00:30:00+00:00` on a UTC host but loses on a Europe/Sofia host. In an alias collision, deployment environment therefore determines which plan is permanently deleted, contradicting the promised aware-instant ordering and "real timestamp outranks malformed" rule.
  Recommendation: Parse first and require `tzinfo is not None` and `utcoffset() is not None` before converting to UTC; otherwise use the malformed/id fallback. Catch parsing/conversion failures consistently, and add regression tests where naive/date-only timestamps collide with an aware timestamp under differing host timezones.

Next steps:
- Reject timezone-less timestamps in `_sort_key` and extend the migration collision tests before shipping.

## Triage

Round-3 cap reached. The stream converged (2 med → 1 med → 1 med), each a narrower edge-case
on the same collision-ordering helper; Codex confirms "the other prior-round fixes appear
coherent". The final finding is a real host-dependence bug but on a path that requires
padded+unpadded collisions with tz-less timestamps — vanishingly unlikely for this single-user
app, yet trivially closed. Applied and shipping (no round 4 per protocol).

| # | Finding | Severity | Verdict | Rationale | Commit |
|---|---------|----------|---------|-----------|--------|
| 1 | `_sort_key` treats a tz-less/date-only `created_at` as a real host-local instant → host-dependent collision survivor | med | fix | Confirmed; require `utcoffset() is not None` before ranking by instant, else id-fallback; tz-less-loses-to-aware test added | d77e7d2 |
