"""state tables — daily_metrics, checkins, strength_tests, plans, suggestions

The five derived + coaching-state tables that complete app.db to its 9 tables (no
`profile` table — constants live in profile.yaml). Authored complete in one revision
(E2·P3 TASK-003), chained off the E2·P2 ingest head. None of the five has an
inter-table FK, so the downgrade drop order is unconstrained. Constraint names use
the E2·P1 naming convention (`op.f`), so `alembic check` / compare_metadata is clean.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-03

"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "daily_metrics",
        sa.Column("date", sa.Text(), nullable=False),
        sa.Column("sleep_h", sa.Float(), nullable=True),
        sa.Column("hrv_sdnn", sa.Float(), nullable=True),
        sa.Column("rhr", sa.Float(), nullable=True),
        sa.Column("hrv_30d_mean", sa.Float(), nullable=True),
        sa.Column("hrv_30d_sd", sa.Float(), nullable=True),
        sa.Column("rhr_30d_mean", sa.Float(), nullable=True),
        sa.Column("steps", sa.Integer(), nullable=True),
        sa.Column("active_energy", sa.Float(), nullable=True),
        sa.Column("z1_min", sa.Float(), nullable=True),
        sa.Column("z2_min", sa.Float(), nullable=True),
        sa.Column("z3_min", sa.Float(), nullable=True),
        sa.Column("z4_min", sa.Float(), nullable=True),
        sa.Column("z5_min", sa.Float(), nullable=True),
        sa.Column("kcal_in", sa.Float(), nullable=True),
        sa.Column("protein_in_g", sa.Float(), nullable=True),
        sa.Column("carbs_in_g", sa.Float(), nullable=True),
        sa.Column("fat_in_g", sa.Float(), nullable=True),
        sa.Column("fiber_in_g", sa.Float(), nullable=True),
        sa.Column("sodium_in_mg", sa.Float(), nullable=True),
        sa.Column("water_in_l", sa.Float(), nullable=True),
        sa.Column("body_weight", sa.Float(), nullable=True),
        sa.Column("hard_day", sa.Integer(), nullable=True),
        sa.Column("readiness_score", sa.Integer(), nullable=True),
        sa.Column("band", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("date", name=op.f("pk_daily_metrics")),
    )

    op.create_table(
        "checkins",
        sa.Column("date", sa.Text(), nullable=False),
        sa.Column("gi_symptoms", sa.Integer(), nullable=True),
        sa.Column("illness", sa.Integer(), nullable=True),
        sa.Column("knee_pain", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("date", name=op.f("pk_checkins")),
    )

    op.create_table(
        "strength_tests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Text(), nullable=False),
        sa.Column("iso_week", sa.Text(), nullable=False),
        sa.Column("max_pushups", sa.Integer(), nullable=True),
        sa.Column("max_pullups", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strength_tests")),
        sa.UniqueConstraint("iso_week", name=op.f("uq_strength_tests_iso_week")),
    )

    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("iso_week", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("inputs_snapshot", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("constitution_version", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("iso_week", name=op.f("uq_plans_iso_week")),
    )

    op.create_table(
        "suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Text(), nullable=False),
        sa.Column("readiness_score", sa.Integer(), nullable=True),
        sa.Column("band", sa.Text(), nullable=True),
        sa.Column("safety_gate_tripped", sa.Integer(), nullable=True),
        sa.Column("gate_reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("inputs_snapshot", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("constitution_version", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suggestions")),
        sa.UniqueConstraint("date", name=op.f("uq_suggestions_date")),
    )


def downgrade() -> None:
    op.drop_table("suggestions")
    op.drop_table("plans")
    op.drop_table("strength_tests")
    op.drop_table("checkins")
    op.drop_table("daily_metrics")
