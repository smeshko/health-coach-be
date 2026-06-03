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

    op.create_table(
        "workouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.Text(), nullable=True),
        sa.Column("activity_type", sa.Text(), nullable=False),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("duration_unit", sa.Text(), nullable=True),
        sa.Column("total_distance", sa.Float(), nullable=True),
        sa.Column("total_distance_unit", sa.Text(), nullable=True),
        sa.Column("total_energy_burned", sa.Float(), nullable=True),
        sa.Column("total_energy_burned_unit", sa.Text(), nullable=True),
        sa.Column("effort_score", sa.Float(), nullable=True),
        sa.Column("physical_effort", sa.Float(), nullable=True),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("source_version", sa.Text(), nullable=True),
        sa.Column("device", sa.Text(), nullable=True),
        sa.Column("creation_date", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Text(), nullable=False),
        sa.Column("end_date", sa.Text(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workouts")),
        sa.UniqueConstraint("uuid", name=op.f("uq_workouts_uuid")),
    )

    op.create_table(
        "workout_statistics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workout_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Text(), nullable=True),
        sa.Column("end_date", sa.Text(), nullable=True),
        sa.Column("sum", sa.Float(), nullable=True),
        sa.Column("average", sa.Float(), nullable=True),
        sa.Column("minimum", sa.Float(), nullable=True),
        sa.Column("maximum", sa.Float(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workout_id"],
            ["workouts.id"],
            name=op.f("fk_workout_statistics_workout_id_workouts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workout_statistics")),
    )
    op.create_index(
        op.f("ix_workout_statistics_workout_id"),
        "workout_statistics",
        ["workout_id", "type"],
        unique=False,
    )

    op.create_table(
        "activity_summary",
        sa.Column("date", sa.Text(), nullable=False),
        sa.Column("active_energy_burned", sa.Float(), nullable=True),
        sa.Column("active_energy_burned_goal", sa.Float(), nullable=True),
        sa.Column("apple_exercise_time", sa.Float(), nullable=True),
        sa.Column("apple_exercise_time_goal", sa.Float(), nullable=True),
        sa.Column("apple_stand_hours", sa.Integer(), nullable=True),
        sa.Column("apple_stand_hours_goal", sa.Integer(), nullable=True),
        sa.Column("apple_move_time", sa.Float(), nullable=True),
        sa.Column("apple_move_time_goal", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("date", name=op.f("pk_activity_summary")),
    )


def downgrade() -> None:
    # Drop children before parents so the workout_statistics → workouts FK never dangles.
    op.drop_table("activity_summary")
    op.drop_index(op.f("ix_workout_statistics_workout_id"), table_name="workout_statistics")
    op.drop_table("workout_statistics")
    op.drop_table("workouts")
    op.drop_index(op.f("ix_records_start_date"), table_name="records")
    op.drop_index(op.f("ix_records_type"), table_name="records")
    op.drop_table("records")
