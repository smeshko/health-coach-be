"""`strength_tests` — the weekly test (DB.md §3).

Two numbers (max push-ups / pull-ups) per week. Keeps a surrogate `id` PK with the
period uniqueness on a separate `UNIQUE(iso_week)` column — "one test per week"
(epic R5). The raw values are stored; trend-smoothing is computed elsewhere. Schema
only — the weekly write path is E5.
"""

from sqlalchemy import Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class StrengthTests(Base):
    __tablename__ = "strength_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(Text, nullable=False)
    iso_week: Mapped[str] = mapped_column(Text, nullable=False)
    max_pushups: Mapped[int | None] = mapped_column(Integer)
    max_pullups: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("iso_week"),)
