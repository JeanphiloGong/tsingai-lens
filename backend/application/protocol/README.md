# Backend Protocol Application Node

This node owns the conditional protocol branch in the backend.

## Scope

- `pipeline_service.py`
- `block_service.py`
- `extract_service.py`
- `validate_service.py`
- `normalize_service.py`
- `artifact_service.py`
- `search_service.py`
- `sop_service.py`
- `document_meta_service.py`

## Responsibilities

- derive protocol-oriented source views from indexed collection documents
- build `sections.parquet`, `procedure_blocks.parquet`, and
  `protocol_steps.parquet`
- normalize and validate protocol-step outputs
- support collection-scoped protocol listing and search
- generate SOP drafts over protocol artifacts

## Boundary

This node is a conditional downstream branch, not the default Lens v1 parsing
backbone.

It may depend on:

- collection-scoped indexed outputs
- collection protocol suitability decisions produced upstream by
  `application/documents/`
- workspace or controller gating that determines whether protocol is exposed

It should not redefine:

- the primary collection comparison workflow
- document-profile semantics
- evidence-card contracts
- comparison-row contracts

## Important Files

- `pipeline_service.py`
  Builds protocol artifacts from indexed collection inputs
- `artifact_service.py`
  Persists protocol branch artifacts over the Documents-owned collection-input seam
- `block_service.py`
  Builds procedure blocks from sections
- `extract_service.py`
  Converts procedure blocks into protocol-step tables
- `search_service.py`
  Supports collection-scoped protocol search
- `sop_service.py`
  Builds SOP drafts over available protocol artifacts

## Upstream / Downstream

- upstream inputs:
  indexed collection documents, text units, shared Core parsing seam, and
  document suitability gating
- downstream artifacts:
  `sections.parquet`, `procedure_blocks.parquet`, `protocol_steps.parquet`
- downstream consumers:
  protocol listing/search APIs, SOP drafting, collection capabilities and
  conditional protocol entry

## Related Docs

- [`../../docs/plans/evidence-first-parsing-plan.md`](../../docs/plans/evidence-first-parsing-plan.md)
- [`../../docs/architecture/domain-architecture.md`](../../docs/architecture/domain-architecture.md)
- [`../../../docs/architecture/lens-v1-architecture-boundary.md`](../../../docs/architecture/lens-v1-architecture-boundary.md)
- [`../README.md`](../README.md)
