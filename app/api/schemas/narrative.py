"""The shared coach-prose section model (MODELS `NarrativeSection`).

Re-homed here from `weekly.py` (E10·P1 defined it for the weekly output and
flagged "E11 imports or re-homes it — a one-line move, not a duplicate"), so the
**one** `NarrativeSection` is shared by both the weekly and daily LLM outputs —
no second wire shape that could drift. `weekly.py` and `daily.py` both import it
from here, so `weekly.NarrativeSection is daily.NarrativeSection`.

`type` keys placement/styling in the app; `heading`/`body` are the prose. Each
brief restricts `type` to its own subset (weekly `plan|session|nutrition`; daily
`summary|session|nutrition|caution`) in the **validator** path — not as a
`Literal` here (so a stray kind is a `ModelRetry` the model sees, not a 422).
"""

from app.api.schemas.base import CamelModel
from app.core.enums import NarrativeType


class NarrativeSection(CamelModel):
    """One unit of LLM-authored coach prose for display (MODELS `NarrativeSection`)."""

    type: NarrativeType
    heading: str
    body: str
