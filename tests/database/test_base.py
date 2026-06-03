"""Declarative base + naming-convention tests (E2·P1 TASK-002).

The naming convention is the load-bearing deliverable: E2·P2/P3 attach the nine
tables and the R5 UNIQUE/index/FK constraints to this `Base`, and their generated
names must be deterministic across machines for clean autogen diffs.
"""

from sqlalchemy.orm import DeclarativeBase

from app.database import Base, metadata

EXPECTED_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def test_naming_convention_keys_and_templates():
    convention = dict(Base.metadata.naming_convention)
    assert set(convention) == {"ix", "uq", "ck", "fk", "pk"}
    assert convention == EXPECTED_CONVENTION


def test_base_is_declarative_and_shares_metadata():
    assert issubclass(Base, DeclarativeBase)
    assert Base.metadata is metadata


def test_no_tables_defined_in_this_phase():
    # This phase ships zero tables; the nine tables land in E2·P2/P3.
    assert Base.metadata.tables == {}
