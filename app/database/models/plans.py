"""`plans` — weekly plan brief cache (DB.md §4).

`WEEKLY_PLANNER` output, one cached brief per ISO week. Surrogate `id` PK with a
`UNIQUE(iso_week)` cache key enforcing "one plan per period" for the get-or-generate
flow (epic R5). `payload` (JSON-as-TEXT) is NOT NULL — a cached brief with no body is
meaningless; `rationale`/`inputs_snapshot` are nullable snapshots. JSON is stored as
TEXT (SQLite JSON1 operates on TEXT). Schema only — brief writes are E10.
"""

from sqlalchemy import Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Plans(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iso_week: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    inputs_snapshot: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    constitution_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("iso_week"),)
