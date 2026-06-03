"""`records` — every HealthKit sample (ingest).

Structurally mirrors `baseline.db` plus two additions: a `uuid` idempotency key and
an `origin` flag (`'seed'` | `'sync'`) (DB.md §1; epic R4). `uuid` is **UNIQUE but
nullable** — seeded rows carry no HealthKit UUID, and SQLite treats each NULL as
distinct under a unique index, so all seeded rows coexist while a duplicate live
UUID is rejected. All timestamps are ISO-8601 **TEXT** (offset preserved verbatim,
never `DateTime`). Constraint/index names come from E2·P1's metadata naming
convention. Written by `POST /sync` (E5) — this phase defines schema only.
"""

from sqlalchemy import Float, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Records(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(Text)
    source_version: Mapped[str | None] = mapped_column(Text)
    device: Mapped[str | None] = mapped_column(Text)
    creation_date: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[str] = mapped_column(Text, nullable=False)
    end_date: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("uuid"),
        Index(None, "type", "start_date"),
        Index(None, "start_date"),
    )
