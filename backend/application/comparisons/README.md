# Backend Comparisons Application Node

This node owns collection-facing comparison row generation over the evidence
backbone.

## Scope

- `service.py`

## Responsibilities

- read or build `comparison_rows.parquet`
- normalize evidence cards into collection-facing comparison rows
- derive `comparability_status`
- attach `comparability_warnings`
- preserve supporting evidence references for traceback

## Boundary

This node owns comparison-row generation and retrieval.

It may depend on:

- `application/evidence/`
- `application/collections/`
- `application/workspace/`

It should not own:

- document profiling
- raw evidence extraction
- protocol-step derivation
- graph or report presentation

## Important Files

- `service.py`
  Generates, normalizes, persists, and serves `comparison_rows.parquet`

## Upstream / Downstream

- upstream input:
  `evidence_cards.parquet`
- downstream artifact:
  `comparison_rows.parquet`
- downstream consumers:
  workspace readiness, collection comparison workspace, protocol gating
  context, and future derived views

## Related Docs

- [`../../docs/specs/api.md`](../../docs/specs/api.md)
- [`../../../docs/40-specs/lens-core-artifact-contracts.md`](../../../docs/40-specs/lens-core-artifact-contracts.md)
- [`../README.md`](../README.md)
