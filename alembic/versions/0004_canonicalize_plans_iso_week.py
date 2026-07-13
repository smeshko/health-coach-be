"""canonicalize plans.iso_week to zero-padded ISO %G-W%V

Phase 19.4 (D5) canonicalizes `iso_week` at the request boundary so an accepted unpadded
`2026-W1` becomes `2026-W01`. Existing rows created before that change may hold noncanonical
keys; the cache lookup, refresh delete, and the new prior-week quality-focus lookup all use
exact textual equality, so a stranded `2026-W1` row would be missed after deploy (a duplicate
plan for one logical week, or a cold-started focus). This one-shot data migration rewrites any
noncanonical `plans.iso_week` to its padded form, resolving a `2026-W1`/`2026-W01` collision by
keeping the most recent row (`created_at`) and dropping the older duplicate — so the
`UNIQUE(iso_week)` constraint holds. Idempotent: already-canonical keys are untouched.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-13

"""

from datetime import datetime, timezone

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def _canonical(iso_week: str) -> str | None:
    """`YYYY-Www` → zero-padded `%G-W%V`, or ``None`` if unparseable (left untouched)."""
    year_str, sep, week_str = iso_week.partition("-W")
    if sep != "-W" or not year_str.isdigit() or not week_str.isdigit():
        return None
    return f"{int(year_str):04d}-W{int(week_str):02d}"


def _sort_key(row_id: int, created_at: str | None) -> tuple:
    """A total, DST-safe ordering key for picking a collision survivor (review #2.1).

    Compares the ACTUAL instant (parsed as an aware datetime → UTC), never the raw
    offset-bearing string — so a pre-DST-rollback `+03:00` row does not spuriously outrank a
    later `+02:00` row. A row with a real timestamp always outranks a null/malformed one; ties
    (equal/missing/unparseable instants) fall back to the surrogate `id` (later insert wins),
    so the choice is deterministic regardless of SELECT order. ``max(key)`` picks the survivor.
    """
    if created_at:
        try:
            parsed = datetime.fromisoformat(created_at)
        except ValueError:
            parsed = None
        # Require an explicit offset (review #3.1): a tz-less/date-only string would otherwise be
        # read in the migration HOST's local timezone, making the survivor host-dependent — so
        # classify it as malformed and fall through to the id-only ordering instead.
        if parsed is not None and parsed.utcoffset() is not None:
            return (1, parsed.astimezone(timezone.utc), row_id)
    return (0, datetime.min.replace(tzinfo=timezone.utc), row_id)


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.exec_driver_sql("SELECT id, iso_week, created_at FROM plans").fetchall()
    # Group every row by its canonical key, then per key keep the survivor (max _sort_key) and
    # drop the rest — so `UNIQUE(iso_week)` holds after the renames.
    by_key: dict[str, list[tuple[tuple, int, str]]] = {}
    for row_id, iso_week, created_at in rows:
        canonical = _canonical(iso_week)
        if canonical is None:
            continue  # leave an unparseable key untouched
        by_key.setdefault(canonical, []).append((_sort_key(row_id, created_at), row_id, iso_week))

    for canonical, group in by_key.items():
        group.sort(key=lambda t: t[0])
        survivor = group[-1]
        for _key, row_id, _iso in group[:-1]:
            conn.exec_driver_sql("DELETE FROM plans WHERE id = ?", (row_id,))
        if survivor[2] != canonical:  # rename the survivor only if noncanonical
            conn.exec_driver_sql(
                "UPDATE plans SET iso_week = ? WHERE id = ?", (canonical, survivor[1])
            )


def downgrade() -> None:
    # Canonicalization is not reversible (the original noncanonical spelling + any dropped
    # duplicate are not recoverable). A no-op downgrade keeps the padded keys, which remain
    # valid `YYYY-Www` values.
    pass
