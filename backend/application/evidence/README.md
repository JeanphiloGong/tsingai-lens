# Backend Evidence Application Node

This node owns claim-centered evidence extraction for collection-backed
inspection.

## Scope

- `service.py`

## Responsibilities

- read or build `evidence_cards.parquet`
- convert profiled documents into claim-centered evidence cards
- preserve one primary claim per card with one or more evidence anchors
- retain material-system and condition-context structure needed by downstream
  comparison logic
- surface traceability strength through `traceability_status`

## Boundary

This node owns evidence-card generation and retrieval.

It may depend on:

- `application/documents/`
- `application/collections/`
- `application/workspace/`
- `application/protocol/section_service.py`
- `application/protocol/source_service.py`

It should not own:

- collection-level comparability judgments
- task orchestration
- protocol browsing or SOP synthesis

## Important Files

- `service.py`
  Generates, normalizes, persists, and serves `evidence_cards.parquet`

## Upstream / Downstream

- upstream inputs:
  `document_profiles.parquet`, `documents.parquet`, text units, derived sections
- downstream artifact:
  `evidence_cards.parquet`
- downstream consumers:
  comparisons, workspace readiness, frontend evidence inspection

## Related Docs

- [`../../docs/specs/api.md`](../../docs/specs/api.md)
- [`../../../docs/40-specs/lens-core-artifact-contracts.md`](../../../docs/40-specs/lens-core-artifact-contracts.md)
- [`../README.md`](../README.md)
