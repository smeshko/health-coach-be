# TASK-004: camelCase Pydantic base model

Depends on: TASK-001
Suggested commit: `feat(api): add camelCase Pydantic base model`

## Goal

A shared Pydantic base that serializes camelCase on the wire while keeping snake_case in Python, inherited
by every request/response model.

## Files

- `app/api/schemas/base.py` — `CamelModel(BaseModel)` with `alias_generator=to_camel`,
  `populate_by_name=True`, `from_attributes=True`, **and `serialize_by_alias=True`** (so raw
  `model_dump_json()` emits camelCase, not just FastAPI response handling)
- `tests/test_camel_base.py` — round-trip casing test + a FastAPI route returning a `CamelModel` asserting
  the **actual wire JSON** is camelCase

## Acceptance

- [ ] A model with `snake_case` fields inheriting `CamelModel` emits camelCase keys from **raw**
      `model_dump_json()` (no `by_alias=True` needed at the call site) — i.e. aliasing is configured on the
      model, not left to the caller.
- [ ] A FastAPI route returning the model produces camelCase JSON on the wire (asserted via `TestClient`).
- [ ] It accepts **both** camelCase (alias) and snake_case (field name) on input.
- [ ] **Null-vs-absent (MODELS "Nulls vs absent"):** an optional field declared `T | None = None` accepts
      **both** omission **and** explicit `null` (tested) — the convention `T | None = None` is documented in
      the module docstring so later wire models don't reject omission.

## Steps

### RED
- [ ] `tests/test_camel_base.py`: define a sample model with a required + an optional (`T | None = None`)
      field; assert raw `model_dump_json()` is camelCase, both-casing accepted in, a `TestClient` route
      returns camelCase wire JSON, and the optional field accepts **both** omission and explicit `null`.

### GREEN
- [ ] Implement `CamelModel` using `pydantic.alias_generators.to_camel` with `serialize_by_alias=True`.

### REFACTOR
- [ ] Document the convention in a short module docstring.

## Notes

Wire is camelCase, Python snake_case behind an `alias_generator` (MODELS "Conventions → Casing"). All E5/
E10/E11 wire models inherit this — define it once.
