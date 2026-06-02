# TASK-002: Declarative base and migration naming conventions

Depends on: TASK-001
Suggested commit: `feat(database): add declarative Base with deterministic naming convention`

## Goal

Add the declarative `Base` over a `MetaData` that carries a `naming_convention`, so every index/constraint
the later table phases define gets a stable, deterministic name in Alembic autogenerate.

## Files

- `app/database/base.py` — new:
  - `NAMING_CONVENTION = {"ix": "ix_%(column_0_label)s", "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s", "fk":
    "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s"}`.
  - `metadata = MetaData(naming_convention=NAMING_CONVENTION)`.
  - `class Base(DeclarativeBase): metadata = metadata` (SQLAlchemy 2.0 declarative style).
- `app/database/__init__.py` — extend re-exports with `Base`, `metadata`.
- `tests/database/test_base.py` — new: assert the convention keys/values and that `Base.metadata is
  metadata` with the convention attached.

## Acceptance

- [ ] `Base.metadata.naming_convention` contains keys `ix`, `uq`, `ck`, `fk`, `pk` with the expected
      templates.
- [ ] `Base` is a `DeclarativeBase` subclass and `Base.metadata is metadata`.
- [ ] `Base.metadata.tables == {}` — **no** tables are defined in this phase.
- [ ] `from app.database import Base, metadata` resolves.

## Steps

### RED
- [ ] `tests/database/test_base.py`: assert the five naming-convention keys and templates; assert
      `Base.metadata is metadata`; assert `Base.metadata.tables == {}`.

### GREEN
- [ ] Implement `app/database/base.py` and extend the `__init__.py` re-exports.

### REFACTOR
- [ ] Module docstring noting that `Base.metadata` is the **single** autogenerate target for Alembic
      (TASK-004) and that the convention makes the R5 UNIQUE/index/FK names deterministic.

## Notes

The naming convention is the load-bearing deliverable: E2·P2/P3 attach the nine tables and the R5
constraints (`records.uuid` UNIQUE, `workouts.uuid` UNIQUE, `strength_tests.iso_week` UNIQUE,
`plans.iso_week` UNIQUE, `suggestions.date` UNIQUE, the `workout_statistics` FK) to **this** `Base`, and
their generated names must be deterministic across machines for clean autogen diffs (epic E2·P1 bullet 4,
R5). No tables are declared here.
