# Core Comparable Result Evolution Roadmap Plan

## Summary

This document records the next Core child plan after the comparable-result
domain-model decision.

Its job is not to reopen the semantic-center decision. That decision is
already made:

- paper facts remain the semantic foundation
- `ComparableResult` is the primary comparison-semantic unit
- `CollectionComparableResult` carries collection-scoped judgment and usage
- `ComparisonRowRecord` is a projection or cache record

This child plan answers the next engineering question:

how the Core comparison substrate should evolve from the corrected object model
into a reusable, persistable, collection-aware comparison backbone.

Read this plan with:

- [`core-comparable-result-domain-model-plan.md`](core-comparable-result-domain-model-plan.md)
- [`minimal-core-domain-backfill-plan.md`](minimal-core-domain-backfill-plan.md)
- [`core-llm-structured-extraction-hard-cutover-plan.md`](core-llm-structured-extraction-hard-cutover-plan.md)
- [`core-llm-structured-extraction-id-boundary-plan.md`](core-llm-structured-extraction-id-boundary-plan.md)

## Purpose

The purpose of this child plan is to turn the corrected comparison model into
an implementation roadmap for a reusable Core comparison substrate.

This means making five ownership-heavy areas explicit:

- persistence model and repository boundaries
- comparable-result identity and deduplication
- cross-collection reuse and read paths
- comparison-policy configuration and versioning
- projection-cache generation and invalidation

Without those decisions, the backend will keep drifting back toward a
collection-local row builder even if the object model is conceptually correct.

## Non-Goals

This child plan does not attempt to complete the following in one wave:

- a full productized corpus-wide materials database
- a full ontology or taxonomy platform
- a repository-wide storage rewrite
- an immediate public API redesign
- automatic expert-grade reasoning over all structure-feature semantics

This plan defines the backbone that later work can build on. It does not
require finishing the long-term database product in this wave.

## Why This Child Plan Exists

The comparable-result domain-model plan corrected the semantic center of the
comparison slice, but it intentionally stopped short of specifying the full
engineering substrate.

That leaves five implementation questions as the next critical backbone work:

1. which objects must be persisted versus projected
2. how `ComparableResult` identity is defined and deduplicated
3. how one collection scope references reusable comparable results
4. how comparison policy is configured and versioned
5. when comparison projections are precomputed versus generated on demand

Those are not optional follow-up details.
They are the minimum engineering decisions required to keep the comparison
slice stable as it grows.

## Target Layered Model

The intended layered interpretation remains:

`paper facts -> comparable results -> collection-scoped assessment -> projection/cache`

The target layers are:

### 1. Paper Facts Layer

This layer remains the canonical one-document semantic foundation.

Owned objects include:

- `SampleVariant`
- `MeasurementResult`
- `TestCondition`
- `BaselineReference`
- `EvidenceAnchor`
- `CharacterizationObservation`
- `StructureFeature`

This layer answers what the source document reported.
It should not absorb collection-specific assessment or UI projection concerns.

### 2. Comparable Result Layer

This layer owns reusable comparison-semantic units.

The primary object is:

- `ComparableResult`

This layer answers:

- what measurement-level semantic unit can participate in comparison
- what bound context defines that unit
- what stable normalized fields identify that unit

This is the first layer that should be reusable across collection scopes.

### 3. Collection-Scoped Assessment And Membership Layer

This layer owns collection-specific inclusion and judgment.

The primary object is:

- `CollectionComparableResult`

This layer answers:

- which comparable units are present in a given collection scope
- how those units were assessed under the active comparison policy
- what collection-specific metadata, inclusion flags, or ordering rules apply

### 4. Projection And Cache Layer

This layer owns collection-facing projection records.

The primary object is:

- `ComparisonRowRecord`

This layer answers:

- what one collection-facing comparison row looks like
- what report or graph payload can be derived from the semantic substrate
- what cache artifacts may be materialized for fast reads

This layer is downstream from the semantic center and should remain
replaceable.

## Persistence Model

### Persistence Boundary

The intended persistence split is:

1. paper-fact artifacts
2. comparable-result artifacts
3. collection membership and assessment artifacts
4. projection or cache artifacts

This gives the system one reusable semantic layer and one collection-scoped
relationship layer instead of collapsing everything into row-shaped storage.

### Persisted Objects

The following objects should be treated as persisted or persistable Core
artifacts:

- paper-fact artifacts derived from semantic build
- `ComparableResult`
- `CollectionComparableResult`

The following object may be persisted, but only as a downstream cache:

- `ComparisonRowRecord`

### Repository And Ownership Boundaries

The ownership boundary should be explicit:

- paper-fact repositories own single-document extracted facts
- comparable-result repositories own reusable semantic comparison units
- collection-comparable-result repositories own collection-scoped membership
  and assessment state
- projection repositories, if used, own cache artifacts only

The row cache must not become the hidden source of truth for comparison
semantics.

### Initial Storage Shape

The initial engineering target does not require a full database cutover.

A valid short-term storage split is:

- `sample_variants.parquet`
- `measurement_results.parquet`
- `test_conditions.parquet`
- `baseline_references.parquet`
- `comparable_results.parquet`
- `collection_comparable_results.parquet`
- `comparison_rows.parquet`

The critical rule is semantic separation, not a specific storage technology.

## Identity And Deduplication

### Comparable Result Identity

`comparable_result_id` should be deterministic.

The default identity input should include:

- `source_result_id`
- bound `variant_id`
- bound `baseline_id`
- bound `test_condition_id`
- normalized property identity
- normalization version

This should produce rebuild-stable identity for the same semantic comparison
unit.

### Identity Rules

The identity contract should follow these rules:

- if the semantic source result and bound context are the same under the same
  normalization version, reuse the same `comparable_result_id`
- if the normalization version changes and the semantic interpretation changes,
  issue a new `comparable_result_id`
- if two units are similar but not fully identical in bound context, do not
  collapse them into one identity

### Deduplication Categories

Deduplication should explicitly distinguish three cases:

1. strictly identical comparable units
2. semantically related but context-distinct comparable units
3. same source result under a different normalization version

Only case 1 should deduplicate to the same comparable-result identity.

### Rebuild And Reuse Rules

The system should define the following behavior:

- rebuild a comparable result when its bound inputs or normalization version
  change
- reuse a comparable result when the deterministic identity input is unchanged
- preserve old identities when historical comparison outputs must remain
  traceable to an older normalization version

## Query And Read Paths

The comparison substrate should support two first-class read paths and one
future path.

### Collection-First Read Path

Primary flow:

`collection -> collection_comparable_results -> comparable_results -> projections`

This path serves:

- collection comparison table
- graph views
- report and export views

This should remain the default Lens v1 interactive path.

### Document-First Read Path

Primary flow:

`document/result -> comparable_results -> related collections`

This path serves:

- single-paper semantic inspection
- trace-from-result drill-down
- debugging and semantic QA

This path is required if comparable results are meant to be reusable rather
than hidden behind one collection's row cache.

### Future Corpus-First Read Path

Future flow:

`corpus query -> comparable_results -> collections / evidence / projections`

This path is out of current implementation scope, but the repository boundary
should not block it.

This future path enables:

- corpus-wide result search
- literature-backed materials-fact retrieval
- cross-collection reuse and aggregation

## Comparison Policy Model

### Policy Object

Comparison policy should become an explicit object, even if it begins as a
Core-owned code configuration rather than a database table.

The policy object should define:

- comparability rules
- missing-context thresholds
- baseline and condition sufficiency rules
- expert-review triggers
- projection-affecting display rules only when those rules are truly semantic

### Policy Placement

Short term, the policy may live as a Core-owned code object or file-backed
configuration.

Mid term, it should be represented explicitly enough that different comparison
tasks can bind to different policy identities.

The critical requirement is versionability, not immediate database storage.

### Policy Versioning

Assessment outputs should be traceable to:

- `policy_id`
- `policy_version`
- assessment generation timestamp
- assessment input signature

Without that linkage, assessment outputs will become ambiguous whenever the
policy changes.

### Assessment Lifecycle Rules

The collection-scoped assessment layer should define when reassessment is
required.

At minimum, reassessment should happen when:

- a comparable result changes
- a policy version changes
- collection membership changes in a way that affects inclusion or ordering

The system should also decide whether historical assessments are replaced or
retained as versioned records.

## Projection And Cache Strategy

### Projection Rule

Projection is downstream from semantic storage and assessment storage.

That means:

- `ComparisonRowRecord` is generated from `ComparableResult` plus
  `CollectionComparableResult`
- graph and report projections should derive from the same semantic substrate
- no downstream view should own hidden comparison semantics that bypass the
  semantic core

### Precompute Versus On-Demand

The intended short-term strategy is:

- precompute collection comparison rows during build or rebuild
- allow graph, report, and export payloads to derive from the same stored row
  cache or directly from the semantic substrate when needed
- keep the option open to move some projections to on-demand generation later

The intended mid-term strategy is:

- keep a shared projection substrate
- avoid separate per-view semantic assemblers
- precompute only where it materially improves latency or operational
  simplicity

### Cache Invalidation Rules

Projection cache invalidation should be explicit.

At minimum, invalidate projection caches when:

- comparable-result content changes
- collection membership or inclusion changes
- collection-scoped assessment changes
- policy version changes
- projection schema or projection version changes

If these invalidation rules remain implicit, graph, report, and comparison
views will drift apart.

## Phased Rollout

### Phase 1: Short-Term Backbone Engineering

Goal:

move the current comparison flow from row-centered assembly to
`ComparableResult`-centered assembly without requiring a full database
cutover.

Required outcomes:

- persist or materialize `ComparableResult`
- persist `CollectionComparableResult`
- generate deterministic `comparable_result_id`
- generate deterministic `row_id`
- make `ComparisonRowRecord` an explicit projection output
- keep assessment collection-scoped

This phase should not block on:

- corpus-wide search
- advanced ontology work
- broad cross-collection merge heuristics

### Phase 2: Mid-Term Reuse And Policy Stabilization

Goal:

make one comparable result reusable across multiple collection scopes.

Required outcomes:

- deduplication and reuse rules become explicit
- collection-first and document-first read paths both work cleanly
- policy versioning is attached to assessment outputs
- projection cache becomes a shared substrate rather than a page-local helper

### Phase 3: Long-Term Comparison Substrate Expansion

Goal:

let collection degrade into a working view while the backend grows a reusable
literature-backed comparison substrate.

Possible outcomes:

- corpus-level query over comparable results
- task-specific comparison policy families
- reusable projection families for table, graph, benchmark, report, and export
- materials-facts retrieval over normalized literature evidence

This phase should be tracked by later child plans rather than hidden inside
incremental service drift.

## Acceptance Criteria

- the persistence split between paper facts, comparable results, collection
  assessment, and projection is explicit
- `ComparableResult` identity is deterministic and version-aware
- deduplication rules distinguish identical versus merely similar comparison
  units
- collection scopes reference reusable comparable-result identities rather than
  only collection-local row records
- comparison policy is explicitly versionable
- projection generation and invalidation rules are explicit
- the planned read paths support future cross-collection reuse instead of
  blocking it

## Risks And Guardrails

Risks:

- if `ComparableResult` is not stored separately, the system will drift back to
  collection-local row generation
- if identity and deduplication are underspecified, rebuilds will either
  explode duplicates or incorrectly merge distinct units
- if policy versioning is omitted, assessment outputs will become historically
  ambiguous
- if projection invalidation rules remain implicit, different collection views
  will diverge

Guardrails:

- no compatibility wrappers
- no row cache promoted to semantic source of truth
- no collection-local duplicate semantic path unless explicitly justified
- no random long-term identity for comparable results or rows
- no per-view shadow assemblers for graph, report, and export

## Open Questions

The following questions may remain open after this child plan is recorded, but
they should stay narrow:

- whether initial comparable-result persistence remains parquet-backed or moves
  to a repository abstraction immediately
- whether assessment history is fully versioned in the first implementation
  wave or only from the second wave onward
- whether graph and report should continue reading from row cache during the
  first rollout wave or move directly onto a shared projection substrate later

## Parent, Child, And Companion Relationships

### Parent Docs

- [`core-comparable-result-domain-model-plan.md`](core-comparable-result-domain-model-plan.md)
  remains the immediate parent plan for the semantic-center correction.
- [`minimal-core-domain-backfill-plan.md`](minimal-core-domain-backfill-plan.md)
  remains the broader Core-domain parent plan.

### Companion Docs

- [`core-llm-structured-extraction-hard-cutover-plan.md`](core-llm-structured-extraction-hard-cutover-plan.md)
  remains the extraction-contract companion plan.
- [`core-llm-structured-extraction-id-boundary-plan.md`](core-llm-structured-extraction-id-boundary-plan.md)
  remains the identifier-boundary companion plan.

### Follow-Up Scope

Later child plans may narrow this roadmap into:

- comparable-result repository implementation
- collection assessment lifecycle implementation
- projection-substrate cutover
- corpus-level comparable-result retrieval

Those should be tracked as later child docs instead of widening this page into
an open-ended program log.
