"""Derive-don't-emit expanders (E7·P2).

Pure functions that turn a slim LLM **pick** (`card` + dose) into a full,
code-completed session by filling every *function-of-the-card* field from
`CARD_META` (E7·P1) and resolving the card's `hr_cap`/`cadence` symbolic
`profile.yaml` references into live bpm/spm from an **injected** `Profile` (E3).
No validation, no arithmetic, no I/O — the merged shapes "can't be wrong by
construction" (MODELS rule 2; epic R4).
"""
