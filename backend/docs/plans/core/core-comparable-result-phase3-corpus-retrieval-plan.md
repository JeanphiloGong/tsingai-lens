# Core Comparable Result Phase 3 Corpus Retrieval Plan

## Summary

This child plan defines the first executable `Phase 3` wave after the
comparable-result substrate is already persisted, policy-aware, and no longer
hidden behind row-cache-only read paths.

Its job is to expose `ComparableResult` as a corpus-level retrieval unit
across collections while keeping `CollectionComparableResult` as an optional,
current-only scope overlay rather than collapsing the retrieval model back
into collection-local rows.

This plan is intentionally narrower than a full retrieval platform. It does
not introduce a database cutover, vector search, ranking system, or a new
generic retrieval layer.

## Goal

Make corpus-level structured retrieval possible over reusable
`ComparableResult` records and attach current `CollectionComparableResult`
overlays only when scope-sensitive judgment is actually needed.

The intended read shape for this wave is:

`collection outputs -> comparable_results scan -> deduplicated comparable results -> optional current collection overlays`

## Non-Goals

This child plan does not require:

- a database or repository-abstraction cutover
- a new `corpus_comparable_results` primary artifact
- vector search, embedding retrieval, or full-text relevance ranking
- a redesign of `/comparisons`, document drilldown, graph, or report routes
- benchmark or export projection families
- task-specific policy-family configuration
- a generic corpus retrieval service layer

## Why This Child Plan Exists

`Phase 1` established the semantic and scope artifacts.

`Phase 2` then made document-first inspection explicit and attached policy and
reassessment semantics to `CollectionComparableResult`.

The projection-substrate cutover removed the last hidden dependency on row
cache for graph and report reads.

What is still missing is a true corpus-level read surface over reusable
`ComparableResult` records.

Today the backend can answer:

- which comparison rows exist in one collection
- which comparable results came from one document
- which collection-scoped overlay currently judges one result

But it still cannot directly answer, at the corpus level:

- which comparable results exist for one normalized material or property
- where the same comparable result is reused across collections
- which current collection overlays are attached to that result

Without this wave, `ComparableResult` remains reusable in storage but not yet
reusable as a real backend read model.

## Current Baseline

The current baseline before this wave is:

- `comparable_results.parquet` is the semantic source of truth inside each
  collection output
- `collection_comparable_results.parquet` is the current collection-scope
  judgment artifact
- `comparison_rows.parquet` is only projection/cache
- document-first semantic inspection can read
  `document -> comparable_results -> collection_comparable_results`
- graph and report now project from semantic artifacts through a shared
  in-memory projection substrate rather than requiring row cache to exist
- stale `CollectionComparableResult` records are explicit and no longer count
  as current readiness

What does not yet exist is:

- a corpus-level route over `ComparableResult`
- a service-level contract for cross-collection retrieval and deduplication
- explicit rules for joining current collection overlays onto a corpus result

## Phase 3 Decision For This Wave

### ComparableResult Remains The Corpus Retrieval Unit

The corpus retrieval surface should return `ComparableResult` as the primary
item.

It must not promote:

- `ComparisonRowRecord` back into the retrieval unit
- `CollectionComparableResult` into the reusable base object

This preserves the already accepted semantic center:

- `ComparableResult` is reusable semantics
- `CollectionComparableResult` is scope-sensitive judgment
- row records are downstream projection only

### Collection Remains A Working-Set Overlay

Collection is still the working boundary for current judgment, not the owner
of the base semantic object.

That means corpus retrieval should:

- return one base item per `comparable_result_id`
- attach collection overlays only through `comparable_result_id`
- keep collection overlays optional rather than redefining base identity

### The First Wave Should Scan Existing Collection Outputs

This wave should reuse the current file-backed collection registry and output
directories.

The recommended first implementation is:

- enumerate collections through `CollectionService`
- read each collection's `comparable_results.parquet`
- read each collection's `collection_comparable_results.parquet` only when
  current overlay attachment is needed
- deduplicate base results by `comparable_result_id`

This avoids introducing a second storage split before the retrieval rules are
proven.

### The First Wave Should Stay Structured

The first public retrieval surface should stay in the structured comparison
domain.

Recommended initial filters:

- `material_system_normalized`
- `property_normalized`
- `baseline_normalized`
- `test_condition_normalized`
- `source_document_id`
- `collection_id`
- `limit`
- `offset`

This wave should not attempt:

- semantic keyword search
- fuzzy relevance ranking
- ontology expansion
- embedding retrieval

### Shared Projection Must Stay Downstream

Corpus retrieval should not consume `comparison_rows.parquet`.

If a caller later wants row-like or graph-like projections, those should stay
downstream from corpus retrieval rather than becoming the retrieval substrate
itself.

### ComparisonService Must Stay The Owning Entry Point

`ComparisonService` remains the Core-owned entry point for comparison-semantic
reads.

This wave may add small Core-owned helpers or local value objects, but it must
not add:

- a generic search-platform abstraction
- a compatibility facade
- a second parallel service tree just for corpus retrieval

## Target Read Model

### Additive Route Surface

If a public route is introduced in this wave, the recommended additive shape
is:

- `GET /api/v1/comparable-results`
- `GET /api/v1/comparable-results/{comparable_result_id}`

This keeps the new retrieval surface clearly separate from collection-scoped
`/comparisons`.

### Item Shape

Each corpus retrieval item should expose the base comparable-result payload
plus corpus and scope context.

Minimum payload shape:

- `comparable_result_id`
- `source_result_id`
- `source_document_id`
- `binding`
- `normalized_context`
- `axis`
- `value`
- `evidence`
- `variant_label`
- `baseline_reference`
- `result_source_type`
- `epistemic_status`
- `normalization_version`
- `observed_collection_ids`
- `collection_overlays`

### Deduplication Rule

Base results should deduplicate by deterministic `comparable_result_id`.

One `comparable_result_id` should produce one corpus item even when multiple
collections contain the same semantic record.

`observed_collection_ids` should express where that base result was observed.

### Overlay Rule

`collection_overlays` should only contain current
`CollectionComparableResult` records.

That means:

- stale overlays do not count as current overlays
- stale overlays do not satisfy a `collection_id` filter
- missing scope artifacts do not erase the base `ComparableResult`

This keeps base semantic retrieval independent from scope readiness while
preserving current scope truth when a collection-sensitive filter is used.

### Collection Filter Rule

If `collection_id` is supplied:

- the result set should narrow to base comparable results currently observed
  in that collection
- returned overlays should be limited to that collection's current overlay

If `collection_id` is absent:

- the base result set stays corpus-wide
- current overlays from all matching collections may be attached

## Storage And Execution Rule

This wave should not add a new primary artifact.

The intended storage rule is:

- `ComparableResult` remains the only reusable base semantic truth
- `CollectionComparableResult` remains the only current scope judgment truth
- corpus retrieval is assembled from those existing artifacts at read time

This also means the first wave should not require:

- `comparison_rows.parquet`
- a prebuilt corpus manifest
- a separate retrieval cache artifact

## Execution Waves

### Wave 1: Core Corpus Retrieval Contract

Required work:

1. add a corpus-level retrieval method to `ComparisonService`
2. enumerate collection outputs through the existing collection registry
3. load and deduplicate base `ComparableResult` records by
   `comparable_result_id`
4. attach only current `CollectionComparableResult` overlays
5. prove row cache is not required

Expected outcome:

- the backend can answer corpus-level comparable-result queries directly from
  semantic and scope artifacts

### Wave 2: Additive Route And Schema Surface

Required work:

1. add an additive Core route for corpus comparable-result retrieval
2. add explicit schemas for corpus list and detail payloads
3. keep `/comparisons` and document-first inspection behavior stable
4. update the owned API spec for the new surface only

Expected outcome:

- frontend or operator tooling can consume corpus retrieval without rewriting
  collection-first comparison surfaces

### Wave 3: Leave Clean Hooks For Later Expansion

This child plan should leave clean hooks for later `Phase 3` work such as:

- corpus manifest or index acceleration
- benchmark and export projection families
- broader materials-fact retrieval over normalized evidence
- Goal-facing or query-facing reuse of comparable-result retrieval

But those remain separate follow-up work.

## Proposed File Scope

Expected primary file ownership:

- `backend/application/core/comparison_service.py`
- `backend/controllers/core/*`
- `backend/controllers/schemas/core/*`

Potential supporting seams only if needed:

- `backend/application/source/collection_service.py`
- `backend/docs/specs/api.md`

Likely verification paths:

- `backend/tests/unit/services/test_paper_facts_services.py`
- `backend/tests/unit/routers/*`
- `backend/tests/integration/test_app_layer_api.py`

## Acceptance Criteria

- corpus retrieval returns one base item per deterministic
  `comparable_result_id`
- current collection overlays attach through `CollectionComparableResult`
  rather than through row projection
- stale overlays are excluded from current overlay attachment
- `comparison_rows.parquet` is not required for corpus retrieval
- `ComparisonService` remains the owning Core entrypoint
- no wrapper, compatibility layer, generic search platform, or new primary
  retrieval artifact is introduced

## Verification

- service tests proving two collections with the same
  `comparable_result_id` produce one base corpus item
- service tests proving current overlays attach and stale overlays are
  excluded
- service or route tests proving corpus retrieval works when
  `comparison_rows.parquet` is absent
- route tests proving the additive surface does not regress existing
  collection-first `/comparisons` behavior

## Relationships

- Parent roadmap:
  [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
- Parent semantic decision:
  [`core-comparable-result-domain-model-plan.md`](core-comparable-result-domain-model-plan.md)
- Phase 2 predecessors:
  [`core-comparable-result-phase2-document-first-semantic-inspection-plan.md`](core-comparable-result-phase2-document-first-semantic-inspection-plan.md)
  and
  [`core-comparable-result-phase2-policy-lifecycle-plan.md`](core-comparable-result-phase2-policy-lifecycle-plan.md)
- Likely later sibling follow-up:
  broader materials-fact retrieval or corpus-manifest acceleration once the
  first corpus read contract is stable
