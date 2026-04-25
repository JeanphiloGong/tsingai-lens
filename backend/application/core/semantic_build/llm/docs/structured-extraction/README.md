# Core LLM Structured Extraction

This topic family keeps the live LLM-specific plan lineage for the Core
semantic-build extraction contract under
`application/core/semantic_build/llm/`.

These pages are node-local because they describe the owned prompt, schema, and
extractor boundary for this package, not a repo-wide planning bucket.

## Start Here

- [`../../README.md`](../../README.md)
  Node entry for package ownership and local file responsibilities

## Reading Order

- [`hard-cutover.md`](hard-cutover.md)
  Primary cutover plan for replacing heuristic Core extraction with
  schema-bound LLM structured extraction
- [`id-boundary.md`](id-boundary.md)
  Boundary-cleanup plan for removing backend and Source identifiers from the
  model-facing contract
- [`prompt-hardening-and-extraction-mode.md`](prompt-hardening-and-extraction-mode.md)
  Production prompt-hardening and temporary extraction-mode comparison plan

## Related Docs

- [`../../../../../../docs/plans/core/core-parsing-quality-hardening-plan.md`](../../../../../../docs/plans/core/core-parsing-quality-hardening-plan.md)
  Parent Core quality wave
- [`../../../../../../docs/plans/core/core-text-window-atomic-mentions-plan.md`](../../../../../../docs/plans/core/core-text-window-atomic-mentions-plan.md)
  Later text-window narrowing plan that extends this family
- [`../../../../../../docs/plans/core/core-benchmark-script-consolidation-plan.md`](../../../../../../docs/plans/core/core-benchmark-script-consolidation-plan.md)
  Canonical benchmark surface used to evaluate this extraction contract
