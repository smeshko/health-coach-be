"""initial (empty) migration — engine/Alembic scaffolding only, no tables yet

This phase (E2·P1) creates **zero** tables. The nine application tables and their
R5 constraints arrive in E2·P2 (ingest) and E2·P3 (derived + coaching state) and
will autogenerate against ``Base.metadata`` with deterministic names from the
naming convention. This empty base revision still exercises the
``upgrade``/``downgrade`` round-trip and the WAL-on-connect listener wiring.

Revision ID: 0001
Revises:
Create Date: 2026-06-03

"""

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
