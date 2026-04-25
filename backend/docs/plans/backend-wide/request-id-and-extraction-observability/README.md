# Request ID And Extraction Observability

## Purpose

This topic family records backend-wide request correlation and Core extraction
diagnostics work so failures can be traced across collection processing and
semantic build steps.

## Authority Boundary

- this family is backend-owned observability and diagnostics material
- it does not own the public API contract or shared product meaning
- operational context stays here, while shared contract or product decisions
  stay in root `docs/`

## Reading Order

- [`implementation-plan.md`](implementation-plan.md)
  Backend request correlation and extraction diagnostics plan

## Related Docs

- [`../api-surface-migration/current-state.md`](../api-surface-migration/current-state.md)
- [`../goal-source-core-layering/proposal.md`](../goal-source-core-layering/proposal.md)
- [`../../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md`](../../../../application/core/semantic_build/llm/docs/structured-extraction/hard-cutover.md)
