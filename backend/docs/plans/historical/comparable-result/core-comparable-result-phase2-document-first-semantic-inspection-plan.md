# Core Comparable Result Phase 2 Document-First Semantic Inspection Plan

Historical note: this page is retained lineage. Use
[`../../../architecture/core-comparison/decision.md`](../../../architecture/core-comparison/decision.md)
for the current semantic authority and
[`../../../architecture/core-comparison/current-state.md`](../../../architecture/core-comparison/current-state.md)
for the implemented substrate.

## Summary

This child plan defines the first executable wave of `Phase 2`.

Its job is to make the document-first comparison read path explicit now that
`Phase 1` has already established:

- `comparable_results.parquet` as semantic truth
- `collection_comparable_results.parquet` as scope truth
- `comparison_rows.parquet` as downstream projection/cache

This page is intentionally narrower than the full `Phase 2` roadmap. It does
not attempt to complete policy versioning or reassessment history in the same
wave.

## Goal

Make document-centric semantic inspection explicit and testable through the
existing comparable-result substrate.

The intended read path for this wave is:

`document -> comparable_results -> related collection_comparable_results -> optional projection`

## Non-Goals

This child plan does not require:

- a public API redesign
- a corpus-wide search surface
- policy versioning rollout
- reassessment history rollout
- projection-substrate unification for graph, report, or export
- a new generic service layer

## Why This Child Plan Exists

`Phase 1` corrected the semantic center and cut the collection-first read path
over to the new substrate.

What is still missing is an equally explicit document-first path.

Without this wave, the backend can persist reusable `ComparableResult` objects
but still behave as if collection rows are the only practical inspection
surface. That would leave the semantic substrate technically present while
keeping day-to-day inspection logic row-centered.

## Current Baseline

The current baseline after `Phase 1` is:

- comparison build writes:
  - `comparable_results.parquet`
  - `collection_comparable_results.parquet`
  - `comparison_rows.parquet`
- `/comparisons` reads from semantic and scope artifacts, then projects rows
- graph and report are no longer allowed to invent private semantic assembly
- `ComparisonService` remains the owning Core entrypoint

This means `Phase 2` does not need another storage split first. It can begin
directly from the semantic substrate that already exists.

## Phase 2 Decision For This Wave

### Base Inspection Must Be Document-First, Not Row-First

When the operator starts from one document, the backend should inspect:

1. which `ComparableResult` records came from that document
2. which collection-scoped assessment records reference those semantic records
3. which projections are optionally derived from them

The inspection sequence must not begin by scanning `comparison_rows`.

### Comparable Result Remains The First Reusable Unit

This wave does not introduce a new semantic center.

It preserves the `Phase 0` and `Phase 1` decision that:

- paper facts remain the document-semantic foundation
- `ComparableResult` remains the first reusable comparison-semantic unit
- `CollectionComparableResult` remains the scope-sensitive layer
- rows remain projections

### Collection Scope Is Overlay, Not Ownership

Document-first inspection must expose collection-scoped judgment as an overlay
on top of semantic results rather than as the owner of those results.

That means:

- the base read is keyed by `source_document_id`
- scope records are attached by `comparable_result_id`
- row ids are never the primary join key for this path

## Target Read Model

### Base Semantic View

The base document-first read model should answer:

- which normalized comparison units came from this document
- what semantic context each unit carries
- what evidence and traceability each unit carries

Minimum semantic unit for this path:

- `comparable_result_id`
- `source_result_id`
- `source_document_id`
- normalized context
- axis
- result value
- evidence trace
- normalization metadata

### Scope Overlay View

The document-first path should then be able to attach zero or more related
scope records:

- active collection-scoped assessment
- inclusion state
- sort order when relevant

This layer is keyed by:

- `comparable_result_id`
- `collection_id`

### Optional Projection View

Row projection may still be produced for document-facing display needs, but it
must remain explicitly downstream.

The path is:

`document semantic view -> optional collection scope overlay -> optional row projection`

Not:

`row lookup -> recover semantics from row payload`

## Storage And Artifact Rule

This wave should reuse the existing `Phase 1` artifacts.

No new primary storage artifact is required just to support document-first
inspection.

The intended artifact use is:

- `comparable_results.parquet`
  as the semantic source for document-first inspection
- `collection_comparable_results.parquet`
  as the scope overlay source
- `comparison_rows.parquet`
  only when a document-facing projection truly needs row-shaped output

## Service Ownership Rule

### Keep One Owning Entry Service

`ComparisonService` remains the owning Core application entrypoint.

This wave should add explicit document-first read methods or adjacent
Core-owned helpers without introducing:

- a new generic `services/` layer
- a compatibility facade
- a document-specific shadow semantic assembler

### Keep Semantic Judgment In Owned Layers

This wave must preserve:

- semantic assembly ownership in Core comparison helpers
- assessment logic ownership in `domain/core/comparison.py`
- orchestration and artifact IO ownership in `ComparisonService`

## Execution Waves

### Wave 1: Internal Document-First Read Model

Required work:

1. add explicit Core-owned document-first read logic over
   `comparable_results.parquet`
2. attach related `CollectionComparableResult` overlays by
   `comparable_result_id`
3. define the internal response shape for document-first inspection
4. prove this path works without depending on prebuilt row cache

Expected outcome:

- a document can be inspected through semantic artifacts directly

### Wave 2: Collection-Aware Document Drilldown Surface

Optional in the same implementation wave if needed, otherwise the next child
step.

Allowed scope:

- expose the document-first inspection path through an internal/debug route or
  a collection-scoped document drilldown seam

Guardrail:

- do not redesign the public comparison API just to ship this path

### Wave 3: Feed Later Phase 2 Policy Work

This child plan should leave clean hooks for:

- policy versioning
- reassessment triggers
- cross-scope reuse inspection

But those remain separate follow-up work.

## Proposed File Scope

Expected primary file ownership:

- `backend/application/core/comparison_service.py`
- `backend/application/core/comparison_assembly.py`
- `backend/application/core/comparison_projection.py`
- `backend/domain/core/comparison.py`

Potential route ownership only if the surface is explicitly approved:

- `backend/controllers/core/*`
- `backend/controllers/schemas/core/*`

Likely verification paths:

- `backend/tests/unit/domains/test_comparison_domain.py`
- `backend/tests/unit/services/test_paper_facts_services.py`
- comparison-service unit tests or new Core service tests covering
  document-first reads
- app-layer tests only if a route is actually introduced

## Acceptance Criteria

- document-first comparison inspection is explicitly backed by
  `ComparableResult` records keyed by `source_document_id`
- collection-scoped assessment is attached through
  `CollectionComparableResult`, not inferred from rows
- row cache is not required for document-first semantic inspection
- `ComparisonService` remains the owning Core entrypoint
- no generic service layer, wrapper, or per-view semantic assembler is added
- later `Phase 2` policy work has a clean semantic inspection surface to build
  on

## Verification

- service-level tests proving one document can load its `ComparableResult`
  records directly from semantic artifacts
- tests proving scope overlays join through `comparable_result_id`
- tests proving document-first inspection still works when
  `comparison_rows.parquet` is absent
- regression coverage proving collection-first `/comparisons` behavior does not
  break while document-first inspection is added

## Relationships

- Parent roadmap:
  [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
- Parent semantic decision:
  [`core-comparable-result-domain-model-plan.md`](core-comparable-result-domain-model-plan.md)
- Phase 1 predecessors:
  [`core-comparable-result-phase1-persistence-split-plan.md`](core-comparable-result-phase1-persistence-split-plan.md),
  [`core-comparable-result-phase1-read-path-cutover-plan.md`](core-comparable-result-phase1-read-path-cutover-plan.md),
  and
  [`core-comparable-result-phase1-service-boundary-plan.md`](core-comparable-result-phase1-service-boundary-plan.md)
- Likely `Phase 2` sibling follow-ups:
  comparison-policy versioning and collection assessment lifecycle
