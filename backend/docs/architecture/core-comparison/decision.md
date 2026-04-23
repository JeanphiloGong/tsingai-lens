# Core Comparison Semantic Center

## Summary

This page records the accepted backend-local comparison-semantic boundaries for
Lens v1.

The stable rule is:

`paper facts -> comparable results -> collection-scoped overlays -> row projection`

Collection-facing rows remain useful product surfaces, but they are not the
semantic center of the comparison model.

## Accepted Boundaries

- paper facts remain the canonical one-document semantic foundation
- `ComparableResult` is the first reusable comparison-semantic unit
- `CollectionComparableResult` owns collection-scoped assessment, inclusion,
  ordering, and policy metadata
- `ComparisonRowRecord` is a collection-facing projection or cache record, not
  the primary domain object

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

`ComparisonRowRecord` exists to support collection-facing row rendering and
other downstream views.

It may be rebuilt from semantic and scope artifacts. It must not become the
only durable comparison truth.

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
- assembly, overlay refresh, corpus retrieval, and projection orchestration stay
  in [`../../../application/core/comparison_service.py`](../../../application/core/comparison_service.py)
- collection-facing row routes, document-first comparison-semantic inspection,
  and corpus comparable-result routes consume that owned substrate instead of
  rebuilding semantics ad hoc

## Guardrails

- no row-first compatibility path as the semantic source of truth
- no `collection_id` on `ComparableResult`
- no hidden semantic rebuild inside graph, report, or export readers
- no generic service layer added only to rename existing ownership

## Historical Lineage

This page replaces the old plan page as the current semantic authority.

Use [`../../plans/historical/comparable-result/core-comparable-result-domain-model-plan.md`](../../plans/historical/comparable-result/core-comparable-result-domain-model-plan.md)
only when you need the original decision narrative and rollout context.

## Related Docs

- [`current-state.md`](current-state.md)
- [`../../specs/api.md`](../../specs/api.md)
- [`../overview.md`](../overview.md)
- [`../goal-core-source-layering.md`](../goal-core-source-layering.md)
