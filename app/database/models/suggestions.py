"""`suggestions` — daily tuned-session brief cache (DB.md §4).

`DAILY_ADJUSTER` output, one cached brief per Europe/Sofia day. Surrogate `id` PK
with a `UNIQUE(date)` cache key ("one suggestion per day"); `?refresh=true` deletes
the row and regenerates (epic R5). `payload` (JSON-as-TEXT) is NOT NULL;
`gate_reason` is nullable (set only when the §6.2 safety gate trips). Schema only —
readiness/gate computation and brief writes are E8/E11.
"""

from sqlalchemy import Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Suggestions(Base):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(Text, nullable=False)
    readiness_score: Mapped[int | None] = mapped_column(Integer)
    band: Mapped[str | None] = mapped_column(Text)
    safety_gate_tripped: Mapped[int | None] = mapped_column(Integer)
    gate_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    inputs_snapshot: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    constitution_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("date"),)
