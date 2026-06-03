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


def test_registered_tables_inherit_the_naming_convention():
    # E2·P2+ attach their tables to this same Base. Whatever is registered must
    # inherit the metadata naming convention so constraint/index names stay
    # deterministic (order-independent: don't assert emptiness now that tables exist).
    import app.database.models  # noqa: F401 — register models on Base.metadata

    assert Base.metadata.naming_convention == EXPECTED_CONVENTION
    for name, table in Base.metadata.tables.items():
        assert table.primary_key.name == f"pk_{name}"
