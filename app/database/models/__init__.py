"""Ingest + derived ORM models.

Importing this package registers every model on the shared `Base.metadata`, so
`alembic/env.py` (which imports it) sees them as the autogenerate target. Re-export
each model here as it lands (records: TASK-001; workouts/workout_statistics:
TASK-002; activity_summary: TASK-003).
"""

from app.database.models.records import Records

__all__ = ["Records"]
