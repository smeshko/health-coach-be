"""Declarative ``Base`` and the metadata naming convention for migrations.

``Base.metadata`` is the **single** autogenerate target for Alembic (see
``alembic/env.py``). The ``naming_convention`` gives every index/constraint a
stable, deterministic name, so the R5 UNIQUE/index/FK constraints that E2·P2/P3
attach to this base (`records.uuid`, `workouts.uuid`, `strength_tests.iso_week`,
`plans.iso_week`, `suggestions.date`, the `workout_statistics` FK) autogenerate
clean, reviewable diffs across machines (epic E2·P1 bullet 4, R5).

This module defines **no tables** — the nine tables land in E2·P2 and E2·P3.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base; all ORM models attach to ``metadata`` (the autogen target)."""

    metadata = metadata
