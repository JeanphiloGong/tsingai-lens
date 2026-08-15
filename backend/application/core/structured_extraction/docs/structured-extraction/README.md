# Core LLM Structured Extraction

This topic family keeps the model-specific implementation history for the Core
structured-extraction contract under
`application/core/structured_extraction/`.

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
- [`semantic-routing-targeted-extraction-plan.md`](semantic-routing-targeted-extraction-plan.md)
  Next Core extraction redesign for routing source units before running
  targeted method/sample and result/measurement prompts
- [`table-first-extraction-plan.md`](table-first-extraction-plan.md)
  Table-first routing and whole-table extraction plan for table-grounded paper
  facts

## Related Docs

- [`../../../../../docs/architecture/overview.md`](../../../../../docs/architecture/overview.md)
  Maintained backend architecture and ownership boundaries
- [`../../../objectives/README.md`](../../../objectives/README.md)
  Current Objective extraction ownership and flow
