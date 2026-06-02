# E9 — LLM Brain (shared)

| | |
|---|---|
| **Status** | 🔵 ready for dev |
| **Phases** | 2 |
| **Depends on** | E3, E7, E1 |
| **Unblocks** | E10, E11 |
| **Primary refs** | [`LLM.md`](../docs/architecture/LLM.md) §0–§5 · [`ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §2 |

---

## 1. Summary & goal

Build the **PydanticAI integration both briefs reuse** — the `AgentNode`↔`Agent` wrapper, the system/user
context assembly, and the **validation→`ModelRetry`** harness. The model is a **selector and sequencer,
never a calculator**: code computes every number/boolean (E6/E8) and fills card-derived fields (E7); the
LLM only picks, tunes within them, and writes the coach prose ([`LLM.md`](../docs/architecture/LLM.md) §0,
§3). Each brief is **one** `AgentNode` wrapping a PydanticAI `Agent` returning a strict `OutputType`.

## 2. Requirements

- **R1** — Model = **Claude Opus**; **tool-based structured output** (`output_type`); **low temperature**;
  **caching off**; **retries ≤ 2**; **fallback none** (failure surfaces as an error, no synthetic session)
  ([`LLM.md`](../docs/architecture/LLM.md) §2 model settings, §5).
- **R2** — The **call envelope**: `SYSTEM` = the rendered constitution (E3), `USER` = computed context JSON
  for this period (readiness/budgets|weekPlan, 7/28d aggregates incl. nutrition, flags, constants), `TOOL`
  = the structured `OutputType` ([`LLM.md`](../docs/architecture/LLM.md) §0, §2).
- **R3** — **Derive-don't-emit** end-to-end: the agent emits only the slim `*Pick` subset + the daily
  `dayType` lever + narrative; E7 expands and E8 supplies numbers
  ([`LLM.md`](../docs/architecture/LLM.md) §1, §3).
- **R4** — **Output validation** wired as a PydanticAI `@agent.output_validator` that receives the
  `RunContext` deps and calls the **pure** `validate_*` (E7); a **hard** violation does `raise
  ModelRetry(messages)` so the model sees exactly what it broke; exhausted retries ⇒
  `brief_generation_failed`; plus a **belt-and-suspenders re-check before persist**
  ([`LLM.md`](../docs/architecture/LLM.md) §4).
- **R5** — Failure path: timeout / invalid structure / persistent validation failure ⇒ `Error { code:
  brief_generation_failed | upstream_timeout }` ([`LLM.md`](../docs/architecture/LLM.md) §5;
  [`MODELS.md`](../docs/architecture/MODELS.md) Errors).
- **R6** — The two halves of a brief (`data` structured + `narrative` prose) are returned **together** so
  the pick and prose can't drift ([`LLM.md`](../docs/architecture/LLM.md) §0).

## 3. What to implement (by phase)

### E9·P1 — AgentNode ↔ PydanticAI wrapper
- An `AgentNode` (extending E1's node type) wrapping a PydanticAI `Agent` with the model settings (R1),
  generic over the two `OutputType`s.
- The agent runner integrated with `TaskContext` (reads computed context, writes the `*LLMOutput`).
- Tool-based structured output enforced; retries ≤ 2; no fallback.

### E9·P2 — Context assembly & validator harness
- **System prompt** = rendered constitution (E3·P2); **user context** = JSON builder assembling the
  per-period computed inputs (E6/E8) + flags + constants + live weight.
- `@agent.output_validator` calling `validate_weekly`/`validate_daily` (E7) with `RunContext` deps; hard
  violation ⇒ `ModelRetry(reason)`.
- Final re-check before persist; map exhausted retries / timeouts to the error envelope.

## 4. Acceptance criteria

- [ ] An `AgentNode` runs a PydanticAI `Agent` and returns a validated `OutputType` instance (mock the
      model in tests).
- [ ] System prompt is the rendered constitution with the live constants; user context carries the
      computed numbers/flags for the period.
- [ ] A deliberately invalid model output triggers `ModelRetry` with the violation messages; a second
      failure within the cap surfaces `brief_generation_failed`.
- [ ] A timeout surfaces `upstream_timeout`; no synthetic fallback session is ever produced.
- [ ] Caching is off; temperature low; ≤2 retries — all observable in config/tests.
- [ ] The harness is brief-agnostic — both E10 and E11 plug their `OutputType` + validator into it.

## 5. Expected outcome

A reusable, validated LLM call harness — the shared engine E10 (weekly) and E11 (daily) specialise with
their `OutputType`, context payload, and validator.

## 6. Validation

- Unit tests with a mocked PydanticAI model: happy path, `ModelRetry` on invalid output, retry exhaustion
  → error, timeout → error.
- Context-builder tests (correct fields present per brief type).

## 7. Out of scope

The specific agents/workflows/endpoints (E10/E11), Langfuse tracing (E12·P1 — hooks here, wired there),
and the pure validators themselves (E7).
