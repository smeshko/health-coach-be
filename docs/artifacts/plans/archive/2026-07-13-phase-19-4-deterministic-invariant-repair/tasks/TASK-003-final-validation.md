# TASK-003: Final validation

Run `just test` (full suite) + `just lint`. Capture failing-then-passing evidence covering
EVERY PLAN acceptance criterion:
1. Weekly alternation via TWO committed adjacent generations (W→W+1→W+2), focus transported
   through `metadata["computed"]["constants"]` into `GeneratePlanNode.build_deps` (not fed
   directly to the helpers);
2. same-week `refresh=true` replacement (real delete/regenerate path, e.g. via the service or
   route seam) → persisted focus unchanged (no double-flip);
3. cold-start + the full legacy/malformed matrix (`constants: null`, null snapshot,
   non-object JSON, `{}`, `{"constants": {}}`, invalid value) → THRESHOLD (no crash);
4. W01/W53 ISO-year boundary prior-week resolution; unpadded request `2026-W1` canonicalized
   to `2026-W01` (cache key + persistence + prior-lookup agree, round-3 #1);
5. not-due week emits a focus yet still reports `constantsRecomputed=false`; both readers agree;
6. zone merge — injected max-HR move validates (zones+thresholds), RHR-only move updates
   rhr_baseline with unchanged bounds, default path no-op.
Tick each PLAN acceptance criterion with the demonstrated output. No non-test/doc code unless
a gate fails.
