"""index workouts.start_date

Every hot workouts query filters by a `start_date` range (the per-day metrics recompute, the
hard-day scan, the weekly prior-long-run rollup), yet `workouts` carried no `start_date` index
— only the offline build script did (`scripts/build_db.py`), never the ORM/migrations. Mirror
`records`' `ix_records_start_date` (Phase 19.5). The `Index` is also added to the ORM model so
`alembic check` / compare_metadata stays clean. Chains off the 19.4 head `0004`.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-13

"""

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(op.f("ix_workouts_start_date"), "workouts", ["start_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_workouts_start_date"), table_name="workouts")
