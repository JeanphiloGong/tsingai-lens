# Core Comparable Result Domain Model Plan

Historical note: this page is retained lineage. Use
[`../../../architecture/core-comparison/decision.md`](../../../architecture/core-comparison/decision.md)
for the current semantic authority and
[`../../../architecture/core-comparison/current-state.md`](../../../architecture/core-comparison/current-state.md)
for the implemented substrate.

## Summary

This document records the stable Core comparison-domain decision after the
`ComparisonRow`-centered model proved semantically too mixed.

This page is the decision and boundary doc for the comparison-semantic center.
It should stay stable. Delivery sequencing, phase exit criteria, artifact
cutover order, and projection-cache rollout belong in:

- [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
- [`core-comparable-result-phase1-persistence-split-plan.md`](core-comparable-result-phase1-persistence-split-plan.md)
- [`core-comparable-result-phase1-read-path-cutover-plan.md`](core-comparable-result-phase1-read-path-cutover-plan.md)
- [`core-comparable-result-phase1-service-boundary-plan.md`](core-comparable-result-phase1-service-boundary-plan.md)

The intended interpretation is:

`paper facts -> comparable results -> collection-scoped assessment -> row projection`

## Page Role

This plan owns:

- the stable semantic center of the comparison slice
- the object-boundary decision between paper facts, comparison semantics,
  collection scope, and projection
- the long-term identity boundary for comparison-semantic objects
- the ownership rules that later rollout waves must preserve

This plan does not own:

- phase-by-phase engineering rollout
- exact artifact schemas for every storage wave
- projection-cache invalidation rollout details
- public API redesign
- repository-wide storage redesign

## Why This Child Plan Exists

The current Core backbone already extracts or materializes stronger research
facts than the old comparison model admitted:

- `SampleVariant`
- `MeasurementResult`
- `TestCondition`
- `BaselineReference`
- `EvidenceAnchor`
- `CharacterizationObservation`
- `StructureFeature`

The problem was not missing semantics. The problem was semantic mixing inside a
row-shaped object:

- `ComparisonRow` carried row identity
- `ComparisonRow` carried collection scope
- `ComparisonRow` carried normalized comparison context
- `ComparisonRow` carried assessment outputs
- `ComparisonRow` was treated like the semantic center

That made one collection-facing row look like the primary research object even
though the real semantic source was still the single-document fact backbone.

## Decision

The Core comparison domain is re-centered on `ComparableResult`.

This page fixes four design judgments:

1. Paper facts remain the canonical one-document semantic foundation.
2. `ComparableResult` is the primary comparison-semantic unit.
3. `collection` is a comparison scope or working set, not the owner of
   paper-fact meaning.
4. `ComparisonRowRecord` is a projection record, not the primary domain object.

This plan explicitly rejects:

- treating `ComparisonRow` as the semantic center
- pushing `collection_id` into the base single-document semantic unit
- using random `uuid4()` values as the long-term identity strategy for
  comparison units or rows
- adding wrappers, compatibility layers, or duplicate semantic paths to
  preserve the old row-first shape

## Scope

This child plan covers:

- the stable target domain model for comparison semantics
- the ownership split between paper facts, reusable comparison semantics,
  collection-scoped assessment, and projection
- the identity rules that define semantic versus scope-level objects
- the allowed service-responsibility boundary between assembly, assessment, and
  projection

This child plan does not cover:

- a one-wave API contract break
- a repository-wide DDD rewrite
- Source runtime redesign
- moving stable research facts into Source
- the exact storage and rollout sequence for every later wave

## Stable Domain Judgments

### Paper Facts Stay The Semantic Foundation

The most important stable objects remain the facts extracted from a single
document:

- `SampleVariant`
- `MeasurementResult`
- `TestCondition`
- `BaselineReference`
- `EvidenceAnchor`
- `CharacterizationObservation`
- `StructureFeature`

These objects answer what the document reported. They are not collection-facing
display objects.

### `ComparableResult` Is The Standardized Comparison Unit

`ComparableResult` represents one document result after it has been bound to
enough context to enter comparison semantics.

That means:

- the raw `MeasurementResult` has been linked to sample, baseline, condition,
  and evidence context
- normalized comparison fields have been derived
- the result is now meaningful as a comparison-semantic unit

This object must not directly carry `collection_id`.

### `CollectionComparableResult` Owns Scope-Sensitive Judgment

Collection-specific inclusion, ordering, and assessment belong in an explicit
scope-layer object rather than being hidden inside the base semantic unit.

This layer answers:

- which comparable units are in this collection scope
- how they were judged in this scope
- what collection-specific ordering or inclusion rules apply

This is the layer where `collection_id` belongs.

### `ComparisonRowRecord` Is Projection Only

Rows exist for collection-facing outputs such as:

- `/comparisons`
- report generation
- graph projection
- export payloads

They are downstream renderings over stronger semantics. They must not carry the
burden of primary domain identity.

## Recommended Object Model

### Paper-Fact Layer

Owned by:

- [`../../../../domain/core/evidence_backbone.py`](../../../../domain/core/evidence_backbone.py)

Owned objects:

```text
SampleVariant
MeasurementResult
TestCondition
BaselineReference
EvidenceAnchor
CharacterizationObservation
StructureFeature
```

### Comparison-Semantic Layer

Owned by:

- [`../../../../domain/core/comparison.py`](../../../../domain/core/comparison.py)

Recommended shape:

```python
@dataclass(frozen=True)
class ContextBinding:
    variant_id: str | None
    baseline_id: str | None
    test_condition_id: str | None


@dataclass(frozen=True)
class NormalizedComparisonContext:
    material_system_normalized: str
    process_normalized: str | None
    baseline_normalized: str | None
    test_condition_normalized: str | None


@dataclass(frozen=True)
class ComparisonAxis:
    axis_name: str | None
    axis_value: str | float | int | None
    axis_unit: str | None


@dataclass(frozen=True)
class ResultValue:
    property_normalized: str
    result_type: str
    numeric_value: float | None
    unit: str | None
    summary: str


@dataclass(frozen=True)
class EvidenceTrace:
    direct_anchor_ids: tuple[str, ...]
    contextual_anchor_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    structure_feature_ids: tuple[str, ...]
    characterization_observation_ids: tuple[str, ...]
    traceability_status: str


@dataclass(frozen=True)
class ComparableResult:
    comparable_result_id: str
    source_result_id: str
    source_document_id: str
    binding: ContextBinding
    normalized_context: NormalizedComparisonContext
    axis: ComparisonAxis
    value: ResultValue
    evidence: EvidenceTrace
    epistemic_status: str
    normalization_version: str
```

Design rules:

- `ComparableResult` is derived from paper facts, not from a row record
- `ComparableResult` does not carry `collection_id`
- normalization metadata belongs on the semantic object
- scope-sensitive assessment does not belong on the base semantic object

### Collection-Scope Layer

Recommended shape:

```python
@dataclass(frozen=True)
class ComparisonAssessment:
    comparability_status: str
    warnings: tuple[str, ...]
    missing_context: tuple[str, ...]
    baseline_support_status: str | None
    condition_support_status: str | None
    rationale: str


@dataclass(frozen=True)
class CollectionComparableResult:
    collection_id: str
    comparable_result_id: str
    assessment: ComparisonAssessment
    epistemic_status: str
    included: bool
    sort_order: int | None = None
```

### Projection Layer

`ComparisonRowRecord` may live either in
[`../../../../domain/core/comparison.py`](../../../../domain/core/comparison.py) or
in a narrower `domain/core/projection.py` home if that file is introduced
later. This page does not force a physical file split. It only fixes the
semantic rule that row objects are projection records.

Recommended shape:

```python
@dataclass(frozen=True)
class ComparisonRowRecord:
    row_id: str
    collection_id: str
    comparable_result_id: str
    source_document_id: str
    display_payload: dict[str, Any]
    evidence_payload: dict[str, Any]
    assessment_payload: dict[str, Any]
```

## Identity Rules

### Deterministic Comparable Result Identity

`comparable_result_id` should be derived deterministically from semantic inputs
such as:

- `source_result_id`
- `variant_id`
- `baseline_id`
- `test_condition_id`
- normalized property identity
- normalization version

This identity belongs to the reusable semantic unit, not to one collection.

### Deterministic Row Identity

`row_id` should be derived deterministically from scope-level inputs such as:

- `collection_id`
- `comparable_result_id`
- `projection_version`

This identity belongs to the collection-facing projection record.

## Service Responsibility Boundary

The comparison flow should expose three ownership responsibilities:

- comparable-result assembly
- comparability evaluation
- projection

These are responsibility boundaries, not a requirement to introduce a generic
new service layer.

Allowed implementation shapes:

- one owning `ComparisonService` that keeps those responsibilities explicit
- narrow Core-owned helper modules if needed for testability

Disallowed implementation shapes:

- a generic `services/` junk drawer
- wrappers or compatibility layers that preserve row-first semantics
- per-view shadow semantic assemblers for graph, report, and export

## Migration Boundary

This decision plan is satisfied when:

- `ComparisonRowRecord` is treated as projection rather than semantic center
- `ComparableResult` exists as the base comparison-semantic unit
- collection-scoped assessment is explicit
- deterministic identity is used for comparable results and rows

This decision plan intentionally defers:

- standalone persistence for `ComparableResult`
- standalone persistence for `CollectionComparableResult`
- projection-cache invalidation rollout
- policy versioning rollout
- detailed read-path and repository cutover

Those belong to the roadmap and child implementation plans.

## Acceptance Criteria

- paper facts remain the canonical one-document semantic foundation
- `ComparableResult` is the primary comparison-semantic unit
- `collection_id` is removed from the base semantic comparable-result object
- collection-scoped assessment is modeled explicitly
- `ComparisonRowRecord` is documented and implemented as projection
- comparable-result identity and row identity are deterministic
- comparison logic is easier to test independently from DataFrame-heavy row
  assembly

## Risks And Guardrails

Risks:

- if this page is widened into an implementation backlog, the stable semantic
  decision will get buried in rollout details
- if `collection` semantics stay ambiguous, the codebase will keep mixing
  document facts, comparison scope, and UI projection
- if deterministic ids are skipped, rebuilds will keep destabilizing downstream
  references

Guardrails:

- no compatibility wrappers
- no dual semantic paths
- no Source-owned stable comparison semantics
- no random long-term identity for semantic units or rows
- no generic new service layer justified only by naming

## Parent, Child, And Companion Relationships

### Parent Doc

- [`../../core/minimal-core-domain-backfill-plan.md`](../../core/minimal-core-domain-backfill-plan.md)
  remains the parent plan for the broader Core-domain backfill.

### Roadmap Doc

- [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
  owns the delivery phases, rollout boundaries, artifact sequencing, read-path
  cutover order, and child-plan orchestration after this semantic decision.

### Phase 1 Child Plans

- [`core-comparable-result-phase1-persistence-split-plan.md`](core-comparable-result-phase1-persistence-split-plan.md)
  breaks out the first storage/artifact wave.
- [`core-comparable-result-phase1-read-path-cutover-plan.md`](core-comparable-result-phase1-read-path-cutover-plan.md)
  breaks out the collection-first read-path and row-cache cutover.
- [`core-comparable-result-phase1-service-boundary-plan.md`](core-comparable-result-phase1-service-boundary-plan.md)
  breaks out the physical responsibility split for Phase 1 without adding a
  generic service layer.

### Companion Docs

- [`../../core/core-llm-structured-extraction-hard-cutover-plan.md`](../../core/core-llm-structured-extraction-hard-cutover-plan.md)
  remains the extraction-contract and semantic-build companion plan.
- [`../../core/core-llm-structured-extraction-id-boundary-plan.md`](../../core/core-llm-structured-extraction-id-boundary-plan.md)
  remains the boundary-cleanup companion plan that keeps backend ids out of the
  LLM contract.

## Related Docs

- [`../../core/minimal-core-domain-backfill-plan.md`](../../core/minimal-core-domain-backfill-plan.md)
- [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
- [`core-comparable-result-phase1-persistence-split-plan.md`](core-comparable-result-phase1-persistence-split-plan.md)
- [`core-comparable-result-phase1-read-path-cutover-plan.md`](core-comparable-result-phase1-read-path-cutover-plan.md)
- [`core-comparable-result-phase1-service-boundary-plan.md`](core-comparable-result-phase1-service-boundary-plan.md)
- [`../../core/core-llm-structured-extraction-hard-cutover-plan.md`](../../core/core-llm-structured-extraction-hard-cutover-plan.md)
- [`../../core/core-llm-structured-extraction-id-boundary-plan.md`](../../core/core-llm-structured-extraction-id-boundary-plan.md)
- [`../../../architecture/domain-architecture.md`](../../../architecture/domain-architecture.md)
- [`../../../architecture/goal-core-source-layering.md`](../../../architecture/goal-core-source-layering.md)
