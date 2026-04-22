# Core Comparable Result Phase 1 Persistence Split Plan

Historical note: this page is retained lineage. Use
[`../../../architecture/core-comparison/decision.md`](../../../architecture/core-comparison/decision.md)
for the current semantic authority and
[`../../../architecture/core-comparison/current-state.md`](../../../architecture/core-comparison/current-state.md)
for the implemented substrate.

## Summary

This child plan defines the first storage wave after the comparable-result
domain-model correction.

Its job is to introduce explicit semantic and scope artifacts so the backend no
longer collapses comparison semantics directly into `comparison_rows.parquet`.

This plan does not redesign the public API or require a database cutover.

## Goal

Introduce the minimum artifact split required for `Phase 1`:

- `comparable_results.parquet`
- `collection_comparable_results.parquet`
- `comparison_rows.parquet` retained as projection/cache output

## Non-Goals

- changing `/comparisons` response shape
- corpus-wide comparable-result retrieval
- generalized repository abstraction rollout
- policy-family configuration

## Target Artifact Split

### Semantic Artifacts

- `comparable_results.parquet`
  - owned by the comparable-result layer
  - stores reusable `ComparableResult` records

### Scope Artifacts

- `collection_comparable_results.parquet`
  - owned by the collection-scope layer
  - stores `CollectionComparableResult` records

### Projection Artifact

- `comparison_rows.parquet`
  - owned by the projection/cache layer
  - stores `ComparisonRowRecord`
  - must remain downstream from semantic and scope artifacts

## Write Path

The intended write sequence is:

1. load paper-fact artifacts
2. assemble `ComparableResult` records
3. write `comparable_results.parquet`
4. compute collection-scoped assessment and membership
5. write `collection_comparable_results.parquet`
6. project collection-facing rows
7. write `comparison_rows.parquet`

The row artifact must not be the only durable output of the comparison build.

## Ownership Rules

- paper-fact artifacts remain owned by the paper-facts build
- `ComparableResult` artifacts are owned by the comparison semantic build
- `CollectionComparableResult` artifacts are owned by the collection-scope
  comparison build
- row artifacts are projection/cache outputs only

## File Scope

Expected primary file ownership:

- `backend/application/core/comparison_service.py`
- `backend/domain/core/comparison.py`
- `backend/application/core/semantic_build/core_semantic_version.py`
- `backend/application/source/artifact_registry_service.py`

Likely verification paths:

- `backend/tests/unit/domains/test_comparison_domain.py`
- `backend/tests/unit/services/test_paper_facts_services.py`
- `backend/tests/unit/services/test_core_semantic_version.py`

## Acceptance Criteria

- `comparable_results.parquet` exists as a Core-owned semantic artifact
- `collection_comparable_results.parquet` exists as a Core-owned scope artifact
- `comparison_rows.parquet` is generated downstream from those artifacts
- rebuild logic invalidates or regenerates the three layers coherently
- row cache is no longer the only durable comparison artifact

## Verification

- artifact round-trip tests for the two new parquet artifacts
- comparison-service build tests for artifact creation order
- deterministic identity tests for `comparable_result_id`
- targeted semantic-version or rebuild tests for invalidation behavior

## Relationships

- Parent roadmap:
  [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
- Sibling child plans:
  [`core-comparable-result-phase1-read-path-cutover-plan.md`](core-comparable-result-phase1-read-path-cutover-plan.md)
  and
  [`core-comparable-result-phase1-service-boundary-plan.md`](core-comparable-result-phase1-service-boundary-plan.md)
