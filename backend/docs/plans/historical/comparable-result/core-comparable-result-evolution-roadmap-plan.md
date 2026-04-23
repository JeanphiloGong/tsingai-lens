# Core Comparable Result Evolution Roadmap Plan

Historical note: this page is retained lineage. Use
[`../../../architecture/core-comparison/decision.md`](../../../architecture/core-comparison/decision.md)
for the current semantic authority and
[`../../../architecture/core-comparison/current-state.md`](../../../architecture/core-comparison/current-state.md)
for the implemented substrate.

## Summary

This document records the delivery roadmap after the comparable-result
domain-model decision has already been made.

This page owns:

- phase and wave boundaries
- required outcomes per phase
- artifact, service, read-path, and verification matrices
- child-plan breakdown for executable implementation waves

This page does not reopen the semantic-center decision. That remains owned by:

- [`core-comparable-result-domain-model-plan.md`](core-comparable-result-domain-model-plan.md)

Read this plan with:

- [`core-comparable-result-domain-model-plan.md`](core-comparable-result-domain-model-plan.md)
- [`core-comparable-result-phase1-persistence-split-plan.md`](core-comparable-result-phase1-persistence-split-plan.md)
- [`core-comparable-result-phase1-read-path-cutover-plan.md`](core-comparable-result-phase1-read-path-cutover-plan.md)
- [`core-comparable-result-phase1-service-boundary-plan.md`](core-comparable-result-phase1-service-boundary-plan.md)
- [`core-comparable-result-phase2-document-first-semantic-inspection-plan.md`](core-comparable-result-phase2-document-first-semantic-inspection-plan.md)
- [`core-comparable-result-phase2-policy-lifecycle-plan.md`](core-comparable-result-phase2-policy-lifecycle-plan.md)
- [`core-comparable-result-phase3-corpus-retrieval-plan.md`](core-comparable-result-phase3-corpus-retrieval-plan.md)
- [`../../core/minimal-core-domain-backfill-plan.md`](../../core/minimal-core-domain-backfill-plan.md)
- [`../../core/core-llm-structured-extraction-hard-cutover-plan.md`](../../core/core-llm-structured-extraction-hard-cutover-plan.md)
- [`../../core/core-llm-structured-extraction-id-boundary-plan.md`](../../core/core-llm-structured-extraction-id-boundary-plan.md)

## Purpose

The purpose of this child plan is to turn the corrected comparison model into
an executable rollout for a reusable Core comparison substrate.

Without an explicit rollout structure, the backend will keep drifting back
toward a collection-local row builder even when the object model is
conceptually correct.

## Delivery Baseline

This roadmap starts after the semantic-center correction accepted by the parent
domain-model plan.

Baseline assumptions inherited from that decision:

- paper facts remain the semantic foundation
- `ComparableResult` is the primary comparison-semantic unit
- `CollectionComparableResult` carries collection-scoped judgment and usage
- `ComparisonRowRecord` is a projection or cache record

## Non-Goals

This roadmap does not attempt to complete the following in one wave:

- a full productized corpus-wide materials database
- a full ontology or taxonomy platform
- a repository-wide storage rewrite
- an immediate public API redesign
- automatic expert-grade reasoning over all structure-feature semantics

## Phase Map

| Phase | Goal | Must Ship | Explicitly Not Required |
| --- | --- | --- | --- |
| `Phase 0` | Semantic-center correction | `ComparableResult` decision, explicit scope layer, deterministic identity boundary, row demotion to projection | standalone persistence split |
| `Phase 1` | Persistence split and collection-first substrate | `ComparableResult` and `CollectionComparableResult` artifacts, collection-first read path, row cache as explicit projection, clear responsibility boundary | corpus-wide search, database cutover, policy-family system |
| `Phase 2` | Reuse and policy stabilization | document-first read path, policy versioning, reassessment rules, explicit reuse and dedup behavior | corpus-level retrieval productization |
| `Phase 3` | Projection substrate and broader retrieval expansion | shared projection substrate, cross-scope reuse surfaces, broader retrieval over comparable results | repository-wide platform rewrite |

Current recommended engineering focus after the parent cutover is `Phase 1`.

After `Phase 1` substrate closure, the first recommended `Phase 2` child wave
is document-first semantic inspection.

## Layered Interpretation

The intended layering remains:

`paper facts -> comparable results -> collection-scoped assessment -> projection/cache`

### Layer 1: Paper Facts

Owned objects:

- `SampleVariant`
- `MeasurementResult`
- `TestCondition`
- `BaselineReference`
- `EvidenceAnchor`
- `CharacterizationObservation`
- `StructureFeature`

### Layer 2: Comparable Results

Owned object:

- `ComparableResult`

This is the first reusable comparison-semantic layer.

### Layer 3: Collection-Scoped Assessment And Membership

Owned object:

- `CollectionComparableResult`

This layer owns collection-specific inclusion and judgment.

### Layer 4: Projection And Cache

Owned object:

- `ComparisonRowRecord`

This layer owns collection-facing row, graph, report, and export projection
artifacts.

## Phase 1 Execution Envelope

### Goal

Move the current comparison flow from row-centered assembly to a persisted
semantic substrate without requiring a database cutover.

### Entry Criteria

- the domain-model decision is accepted
- deterministic `comparable_result_id` exists
- deterministic `row_id` exists
- collection-facing API shape does not need to change in this wave

### Required Outcomes

- persist or materialize `ComparableResult`
- persist `CollectionComparableResult`
- keep `ComparisonRowRecord` explicitly downstream from semantic artifacts
- keep collection-scoped assessment separate from the base semantic object
- make the collection-first read path explicit
- make Phase 1 service ownership explicit without adding a generic new service
  layer

### Deferred From Phase 1

- corpus-wide search
- advanced ontology work
- broad cross-collection merge heuristics
- a new public API surface
- projection-substrate unification across every downstream view
- fully generalized comparison-policy families

### Exit Criteria

`Phase 1` is complete only when:

- `comparable_results.parquet` exists as a Core-owned semantic artifact
- `collection_comparable_results.parquet` exists as a Core-owned scope artifact
- `comparison_rows.parquet` is produced as an explicit projection/cache artifact
- the collection comparison read path can be described as
  `collection -> collection_comparable_results -> comparable_results -> row projection`
- graph and report remain on a documented temporary substrate rather than on an
  implicit hidden one

## Artifact Matrix

### Phase 1 Artifact Ownership

| Artifact | Layer | Writer | Primary Readers | Source Of Truth Role | Notes |
| --- | --- | --- | --- | --- | --- |
| `sample_variants.parquet` | paper facts | paper-facts build | comparison build, evidence read paths | semantic fact artifact | pre-existing |
| `measurement_results.parquet` | paper facts | paper-facts build | comparison build | semantic fact artifact | pre-existing |
| `test_conditions.parquet` | paper facts | paper-facts build | comparison build | semantic fact artifact | pre-existing |
| `baseline_references.parquet` | paper facts | paper-facts build | comparison build | semantic fact artifact | pre-existing |
| `comparable_results.parquet` | comparable-result layer | comparison build | collection-first reads, document-first semantic inspection, row projection | semantic source of truth | new in `Phase 1` |
| `collection_comparable_results.parquet` | collection-scope layer | comparison build | collection-first reads, row projection | scope source of truth | new in `Phase 1` |
| `comparison_rows.parquet` | projection/cache layer | row projection step | `/comparisons`, graph/report if still on row cache | cache only | must not become semantic source of truth |

### Artifact Cutover Rule

`Phase 1` succeeds only if the semantic source of truth moves upward while row
artifacts remain downstream caches.

## Service Ownership Matrix

| Responsibility | Owner In Phase 1 | Must Own | Must Not Own |
| --- | --- | --- | --- |
| comparable-result assembly | Core comparison build path | bind paper facts and materialize `ComparableResult` | artifact policy history, public route semantics |
| comparability evaluation | domain/core comparison logic | compute `ComparisonAssessment` from semantic input and active scope rule set | row rendering details |
| row projection | Core projection step | map semantic plus scope objects into `ComparisonRowRecord` | semantic identity decisions |
| orchestration and IO | `ComparisonService` | build order, artifact read/write, rebuild coordination | hidden semantic logic that bypasses the owned helpers |

Phase 1 does not require introducing three standalone public service classes.
It does require that these responsibilities are explicit and testable.

## Read-Path Matrix

| Read Path | Status In Phase 1 | Backing Flow | Notes |
| --- | --- | --- | --- |
| collection-first comparison table | required | `collection -> collection_comparable_results -> comparable_results -> row projection/cache` | primary Lens v1 path |
| graph and report | allowed temporary path | row cache in `Phase 1`, shared substrate later | must be documented, not implicit |
| document-first semantic inspection | partial or internal | `document/result -> comparable_results -> related scope records` | may begin as debug or internal read path |
| corpus-first retrieval | deferred | future | not part of `Phase 1` |

## Migration Order

The intended `Phase 1` order is:

1. write `comparable_results` and `collection_comparable_results` artifacts
2. make row generation consume those artifacts or their in-memory equivalents
3. keep `comparison_rows` as projection/cache output
4. cut the collection-first read path so it is explicitly backed by semantic
   plus scope artifacts
5. document temporary downstream consumers that still read row cache directly

This order prevents row cache from remaining the accidental source of truth.

## Verification Matrix

| Verification Slice | What It Proves | Minimum Expected Coverage |
| --- | --- | --- |
| domain identity tests | deterministic comparable-result and row identity | stable ids across rebuild inputs |
| artifact round-trip tests | semantic and scope artifacts can be written and read without loss of boundary | new parquet round-trip tests |
| comparison service build tests | build order writes semantic, scope, and projection artifacts in the right sequence | collection build happy path |
| API shape tests | collection-facing `/comparisons` responses remain stable | no public contract regression |
| projection dependency tests | graph/report temporary row-cache dependency is explicit and versioned | no hidden semantic bypass |

## Child Plan Breakdown

### Phase 1 Child Plans

- [`core-comparable-result-phase1-persistence-split-plan.md`](core-comparable-result-phase1-persistence-split-plan.md)
  owns artifact introduction, storage contract, writer/reader boundaries, and
  build order.
- [`core-comparable-result-phase1-read-path-cutover-plan.md`](core-comparable-result-phase1-read-path-cutover-plan.md)
  owns collection-first read-path cutover, row-cache usage rules, and
  collection-facing API stability.
- [`core-comparable-result-phase1-service-boundary-plan.md`](core-comparable-result-phase1-service-boundary-plan.md)
  owns the physical responsibility split for `Phase 1` while preserving the
  no-generic-service-layer guardrail.

### Later Child Plans

Later child docs should narrow this roadmap further instead of widening this
page into an open-ended program log. The next likely candidates are:

- [`core-comparable-result-phase2-document-first-semantic-inspection-plan.md`](core-comparable-result-phase2-document-first-semantic-inspection-plan.md)
- [`core-comparable-result-phase2-policy-lifecycle-plan.md`](core-comparable-result-phase2-policy-lifecycle-plan.md)
- projection-substrate cutover
- [`core-comparable-result-phase3-corpus-retrieval-plan.md`](core-comparable-result-phase3-corpus-retrieval-plan.md)

## Phase 2 Summary

### Goal

Make reusable comparable results work cleanly across multiple collection
scopes.

### Required Outcomes

- document-first read path is explicit
- reuse and deduplication rules are explicit
- policy versioning is attached to assessment outputs
- reassessment triggers are explicit

## Phase 3 Summary

### Goal

Let collection degrade into a working view while the backend grows a reusable
comparison substrate above document facts.

### Possible Outcomes

- corpus-level query over comparable results
- task-specific comparison policy families
- reusable projection families for table, graph, benchmark, report, and export
- broader materials-fact retrieval over normalized literature evidence

## Acceptance Criteria

- phase boundaries are explicit enough that one implementation wave can be
  scoped without reopening semantic decisions
- the persistence split between paper facts, comparable results, collection
  scope, and projection is explicit
- the collection-first read path is explicit
- row cache is documented as cache rather than semantic source of truth
- the service ownership split is explicit without requiring a generic wrapper
  layer
- later phase work is discoverable through child-plan links rather than hidden
  inside one broad roadmap page

## Risks And Guardrails

Risks:

- if `ComparableResult` is not stored separately, the system will drift back to
  collection-local row generation
- if the collection-first read path remains implicit, downstream views will
  keep coupling to row cache
- if rollout waves remain vague, follow-up work will reopen already-settled
  semantic questions

Guardrails:

- no compatibility wrappers
- no row cache promoted to semantic source of truth
- no collection-local duplicate semantic path unless explicitly justified
- no random long-term identity for comparable results or rows
- no per-view shadow semantic assemblers for graph, report, and export

## Open Questions

The following questions may remain open after this roadmap is refined, but they
should stay narrow:

- whether initial `ComparableResult` persistence remains parquet-backed or
  moves behind a repository abstraction immediately
- whether assessment history is versioned in `Phase 1` or deferred to `Phase 2`
- whether graph and report should continue reading row cache through all of
  `Phase 1` or cut over earlier once the shared substrate is stable

## Parent, Child, And Companion Relationships

### Parent Doc

- [`core-comparable-result-domain-model-plan.md`](core-comparable-result-domain-model-plan.md)
  remains the parent semantic decision doc.

### Phase 1 Child Docs

- [`core-comparable-result-phase1-persistence-split-plan.md`](core-comparable-result-phase1-persistence-split-plan.md)
- [`core-comparable-result-phase1-read-path-cutover-plan.md`](core-comparable-result-phase1-read-path-cutover-plan.md)
- [`core-comparable-result-phase1-service-boundary-plan.md`](core-comparable-result-phase1-service-boundary-plan.md)

### Phase 2 Child Docs

- [`core-comparable-result-phase2-document-first-semantic-inspection-plan.md`](core-comparable-result-phase2-document-first-semantic-inspection-plan.md)
- [`core-comparable-result-phase2-policy-lifecycle-plan.md`](core-comparable-result-phase2-policy-lifecycle-plan.md)

### Phase 3 Child Docs

- [`core-comparable-result-phase3-corpus-retrieval-plan.md`](core-comparable-result-phase3-corpus-retrieval-plan.md)

### Companion Docs

- [`../../core/core-llm-structured-extraction-hard-cutover-plan.md`](../../core/core-llm-structured-extraction-hard-cutover-plan.md)
- [`../../core/core-llm-structured-extraction-id-boundary-plan.md`](../../core/core-llm-structured-extraction-id-boundary-plan.md)
- [`../../core/minimal-core-domain-backfill-plan.md`](../../core/minimal-core-domain-backfill-plan.md)
