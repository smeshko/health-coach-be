"""ingest tables — records, workouts, workout_statistics, activity_summary

The four E2·P2 ingest tables in one revision (they form one cohesive ingest unit).
`upgrade()` creates parents before children (`workouts` before `workout_statistics`);
`downgrade()` drops children before parents so the `workout_statistics → workouts(id)`
FK never dangles on round-trip. Constraint/index names use the E2·P1 metadata naming
convention (`op.f(...)`), so a follow-up `--autogenerate` emits an empty diff.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-03

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("source_version", sa.Text(), nullable=True),
        sa.Column("device", sa.Text(), nullable=True),
        sa.Column("creation_date", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Text(), nullable=False),
        sa.Column("end_date", sa.Text(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_records")),
        sa.UniqueConstraint("uuid", name=op.f("uq_records_uuid")),
    )
    op.create_index(op.f("ix_records_type"), "records", ["type", "start_date"], unique=False)
    op.create_index(op.f("ix_records_start_date"), "records", ["start_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_records_start_date"), table_name="records")
    op.drop_index(op.f("ix_records_type"), table_name="records")
    op.drop_table("records")
