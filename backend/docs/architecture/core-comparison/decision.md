# Retired Core Comparison Decision

## Summary

This page records why the old comparison-semantic substrate is no longer a
Lens v1 product surface.

The maintained rule is:

`Source -> Objective -> published analysis -> Finding -> ObjectiveEvidence`

Comparison rows, comparable results, Evidence cards, Materials, and Graph
projections cannot become a parallel conclusion identity.

## Accepted Boundaries

- Source owns parsed paper content and exact locators.
- Objective analysis owns scientific comparison and uncertainty.
- Finding owns the published conclusion.
- ObjectiveEvidence owns versioned support and Source traceback.
- Legacy comparison records are removed rather than retained as a second
  persistence model.

## Object Responsibilities

### Paper Facts

Paper-fact objects answer what one document reported.

They remain owned by:

- [`../../../domain/core/evidence_backbone.py`](../../../domain/core/evidence_backbone.py)

### Comparable Results

`ComparableResult` carries the normalized comparison-semantic unit built from
paper facts plus comparison context.

It must:

- preserve one-document provenance through `source_document_id`
- carry normalized comparison context and evidence traceability
- stay reusable across collections

It must not:

- carry `collection_id`
- hide collection-specific judgment inside the base semantic object
- depend on row identity

### Collection-Scoped Overlays

`CollectionComparableResult` carries the working-set layer for one collection.

It owns:

- collection-specific assessment
- inclusion and sort order
- policy family and policy version
- normalization-version and reassessment metadata

### Row Projection

`ComparisonRowRecord` is retired. Published Finding and ObjectiveEvidence
records are the evaluation and export inputs.

## Identity Rules

- `comparable_result_id` belongs to the reusable semantic unit and must be
  deterministic from semantic inputs
- `row_id` belongs to the collection-facing projection and must be deterministic
  from scope-level inputs plus projection version
- collection identity belongs on `CollectionComparableResult`, not on the base
  semantic object

## Ownership Rules

- domain invariants and comparison dataclasses stay in
  [`../../../domain/core/comparison.py`](../../../domain/core/comparison.py)
- no comparison repository or compatibility read remains
- current HTTP resources are defined only by
  [`../../specs/api.md`](../../specs/api.md)

## Guardrails

- no compatibility route for retired comparison resources
- no hidden Finding reconstruction in exports or browser clients
- no generic service layer added only to preserve old ownership

Earlier field-level boundaries remain available in Git history when needed for
offline data archaeology.

## Related Docs

- [`current-state.md`](current-state.md)
- [`../../specs/api.md`](../../specs/api.md)
- [`../overview.md`](../overview.md)
- [`../goal-core-source-layering.md`](../goal-core-source-layering.md)
