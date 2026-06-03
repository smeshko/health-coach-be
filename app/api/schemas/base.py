"""Shared camelCase Pydantic base for every wire model.

Wire JSON is **camelCase**; Python stays **snake_case** behind an
`alias_generator` (MODELS "Conventions → Casing"). Every request/response model
in E5/E10/E11 inherits `CamelModel`, so casing is defined exactly once.

`serialize_by_alias=True` means raw `model_dump_json()` already emits camelCase —
callers don't pass `by_alias=True`. `populate_by_name=True` means input is
accepted in **either** casing.

**Nulls vs absent (MODELS "Nulls vs absent"):** declare optional fields as
`T | None = None`. That default makes the field accept **both** omission **and**
an explicit `null` — never declare an optional wire field without the `= None`
default, or omission would be rejected.
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model: snake_case in Python, camelCase on the wire, lenient on input."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        serialize_by_alias=True,
    )
