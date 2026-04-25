# Core Comparison Current State

## Summary

The comparable-result substrate is implemented.

Current implemented comparison semantics follow this chain:

`document_profiles -> paper facts family -> comparable_results -> collection_comparable_results -> row projection and downstream views`

Collection-facing `/comparisons` still serves rows, but those rows are now a
projection over the semantic and scope artifacts rather than the primary source
of truth.

## Current Artifact Chain

### Semantic Truth

- `comparable_results.parquet`
  reusable `ComparableResult` records for one collection build output

### Scope Truth

- `collection_comparable_results.parquet`
  current collection-scoped overlays with assessment and policy metadata

### Projection And Cache

- `comparison_rows.parquet`
  collection-facing row projection that may be regenerated from the semantic and
  scope artifacts

## Current Read Paths

### Collection Comparison Table

`GET /api/v1/collections/{collection_id}/comparisons`

This route remains the main collection-facing table surface, but it now reads
from comparable-result artifacts and projects rows downstream.

### Document-First Comparison Semantics

`GET /api/v1/collections/{collection_id}/documents/{document_id}/comparison-semantics`

This route reads:

`document -> comparable_results -> collection_comparable_results -> optional row projection`

It does not require prebuilt row cache to expose the semantic substrate.

### Corpus Comparable Results

- `GET /api/v1/comparable-results`
- `GET /api/v1/comparable-results/{comparable_result_id}`

These routes expose `ComparableResult` as the corpus retrieval unit and attach
current collection overlays only when scope-sensitive judgment is needed.

## Current Ownership In Code

- [`../../../domain/core/comparison.py`](../../../domain/core/comparison.py)
  accepted dataclasses, ids, assessments, and reassessment logic
- [`../../../application/core/comparison_assembly.py`](../../../application/core/comparison_assembly.py)
  materialization of comparable-result and scope artifacts
- [`../../../application/core/comparison_projection.py`](../../../application/core/comparison_projection.py)
  row projection from semantic artifacts
- [`../../../application/core/comparison_service.py`](../../../application/core/comparison_service.py)
  artifact IO, collection reads, document inspection, corpus retrieval, and row
  projection orchestration
- [`../../../controllers/core/comparisons.py`](../../../controllers/core/comparisons.py)
  collection-facing comparison row routes
- [`../../../controllers/core/documents.py`](../../../controllers/core/documents.py)
  document-first comparison-semantic drilldown route
- [`../../../controllers/core/comparable_results.py`](../../../controllers/core/comparable_results.py)
  corpus comparable-result routes

## Current Contract Notes

- public API authority remains [`../../specs/api.md`](../../specs/api.md)
- workspace and readiness semantics use `comparable_results.parquet` plus
  `collection_comparable_results.parquet` as the comparison-semantic readiness
  basis
- `comparison_rows.parquet` remains optional projection/cache for routes and
  downstream consumers that need row rendering
- graph and report semantics must continue to consume Core artifacts without
  promoting row cache back into the semantic source of truth

## Remaining Guardrails

- do not reintroduce row-first semantic assembly
- do not add collection identity to the base comparable-result object
- do not let downstream readers become private semantic builders
- keep current and historical docs separate: architecture pages own current
  truth, historical plan pages retain rollout lineage

## Historical Lineage

Historical origin and phase plans now live in
[`../../plans/historical/comparable-result/README.md`](../../plans/historical/comparable-result/README.md).

Use those pages for migration rationale, not for the current authoritative
reading path.

## Related Docs

- [`decision.md`](decision.md)
- [`../../specs/api.md`](../../specs/api.md)
- [`../overview.md`](../overview.md)
- [`../../plans/backend-wide/api-surface-migration/current-state.md`](../../plans/backend-wide/api-surface-migration/current-state.md)
