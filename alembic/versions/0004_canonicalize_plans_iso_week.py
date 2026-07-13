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


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.exec_driver_sql("SELECT id, iso_week, created_at FROM plans").fetchall()
    # Group logical weeks by canonical key; pick the survivor (latest created_at) per key.
    survivors: dict[str, tuple[int, str]] = {}  # canonical -> (id, created_at)
    drops: list[int] = []
    renames: list[tuple[int, str]] = []
    for row_id, iso_week, created_at in rows:
        canonical = _canonical(iso_week)
        if canonical is None:
            continue
        created_at = created_at or ""
        if canonical not in survivors:
            survivors[canonical] = (row_id, created_at)
            if iso_week != canonical:
                renames.append((row_id, canonical))
            continue
        # A collision on the canonical key: keep the newer row, drop the older.
        keep_id, keep_created = survivors[canonical]
        if created_at >= keep_created:
            drops.append(keep_id)
            survivors[canonical] = (row_id, created_at)
            renames.append((row_id, canonical))
            renames[:] = [(rid, c) for rid, c in renames if rid != keep_id]
        else:
            drops.append(row_id)
    for row_id in drops:
        conn.exec_driver_sql("DELETE FROM plans WHERE id = ?", (row_id,))
    for row_id, canonical in renames:
        conn.exec_driver_sql(
            "UPDATE plans SET iso_week = ? WHERE id = ?", (canonical, row_id)
        )


def downgrade() -> None:
    # Canonicalization is not reversible (the original noncanonical spelling + any dropped
    # duplicate are not recoverable). A no-op downgrade keeps the padded keys, which remain
    # valid `YYYY-Www` values.
    pass
