# Core Comparable Result Domain Model Plan

## Summary

This document records a focused Core child plan for realigning the comparison
domain around `ComparableResult` rather than around `ComparisonRow`.

The target is not to add a new backend layer, redesign the public API in one
wave, or replace the existing Core backbone. The target is narrower:

- keep paper facts as the semantic ground truth for one document's research
  facts
- treat `ComparableResult` as the primary Core comparison-semantic unit
- treat `collection` as a comparison scope or working-set boundary rather than
  as the owner of paper-fact meaning
- demote `ComparisonRow` to a projection record used by collection-facing
  views

The intended interpretation becomes:

`paper facts -> comparable results -> collection-scoped assessment -> row projection`

Read this plan with:

- [`minimal-core-domain-backfill-plan.md`](minimal-core-domain-backfill-plan.md)
- [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
- [`core-llm-structured-extraction-hard-cutover-plan.md`](core-llm-structured-extraction-hard-cutover-plan.md)
- [`core-llm-structured-extraction-id-boundary-plan.md`](core-llm-structured-extraction-id-boundary-plan.md)
- [`../../architecture/domain-architecture.md`](../../architecture/domain-architecture.md)
- [`../../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)

## Why This Child Plan Exists

The current Core backbone already has stronger semantics than the current
comparison-domain model shows.

Today the system already extracts or materializes:

- `SampleVariant`
- `MeasurementResult`
- `TestCondition`
- `BaselineReference`
- `EvidenceAnchor`
- `CharacterizationObservation`
- `StructureFeature`

Those are the facts that answer the document-level questions that matter most:

- what sample or variant was studied
- under what conditions
- against what baseline
- what result was reported
- and where the evidence came from

The current comparison modeling problem is not missing data.

The current problem is semantic mixing inside one object:

- `ComparisonRow` currently carries a row resource id
- it also carries collection scope
- it also carries normalized comparison context
- it also carries comparability judgment outputs
- and it is treated as if it were the domain-semantic center

That shape makes one table row look like the primary research object even
though the row is only one collection-facing rendering of a stronger semantic
unit.

It also makes `collection` look like the owner of the semantics when the real
semantic source is still the single-document fact backbone.

## Decision

The Core comparison model should be re-centered on one explicit semantic unit:
`ComparableResult`.

This plan makes four design decisions explicit:

1. Single-document paper facts remain the semantic foundation.
2. `ComparableResult` becomes the comparison-semantic core object.
3. `collection` is treated as a comparison scope or working set, not as the
   owner of document fact meaning.
4. `ComparisonRowRecord` is a projection record, not the primary domain
   object.

This plan explicitly rejects:

- treating `ComparisonRow` as the semantic center of the comparison domain
- pushing `collection_id` down into the primary single-document comparison
  unit
- using random `uuid4()` values as the long-term identity strategy for row
  resources
- adding wrappers, compatibility layers, or duplicate object paths just to
  preserve the current shape

## Scope

This child plan covers:

- the target domain model for comparison semantics
- the ownership split between paper facts, comparison semantics, collection
  scope, and projections
- the intended Core service responsibilities for assembly, assessment, and
  projection
- storage and identity rules for comparable results and collection-scoped
  rows
- a migration path from the current `ComparisonRow`-centered flow

This child plan does not cover:

- a one-wave API contract break
- a repository-wide DDD rewrite
- Source runtime redesign
- moving stable research facts into Source
- changing the current Lens v1 evidence-first product boundary

## Core Design Judgments

### The Semantic Foundation Is Still Paper Facts

The most important stable objects are still the research facts extracted from a
single document:

- `SampleVariant`
- `MeasurementResult`
- `TestCondition`
- `BaselineReference`
- `EvidenceAnchor`
- `CharacterizationObservation`
- `StructureFeature`

These belong to the one-document semantic layer.

They answer what the document says. They should not be recast as collection
display objects.

### `ComparableResult` Is The Standardized Comparison Unit

`ComparableResult` represents one document result after it has been bound to
enough context to enter comparison semantics.

That means:

- the raw `MeasurementResult` has been linked to its sample, baseline,
  condition, and evidence context
- normalized comparison fields have been derived
- the unit is now meaningful as a candidate for collection-level comparison

This object should not directly carry `collection_id`.

Its job is to represent what comparable unit exists in the paper facts, not
how one particular collection currently uses or displays it.

### `collection` Is A Working-Scope Boundary

For comparison semantics, `collection` should be interpreted as:

- a comparison scope
- a working set
- a saved review context

It may determine:

- which documents or results are included
- what comparison policy or filtering rules apply
- how assessment is computed in the current review context

It should not be treated as:

- the permanent owner of paper-fact meaning
- the only identity boundary for comparable units
- the semantic layer where one-document facts are first defined

### `ComparisonRowRecord` Is Only A Projection

Rows exist for:

- `/comparisons`
- report generation
- graph projection
- exports

They are collection-facing views over stronger semantics.

They should not keep carrying the full burden of domain identity.

## Recommended Domain Model

### Paper Facts Layer

The paper-fact layer remains in:

- [`../../../domain/core/evidence_backbone.py`](../../../domain/core/evidence_backbone.py)

The owned objects remain:

```text
SampleVariant
MeasurementResult
TestCondition
BaselineReference
EvidenceAnchor
CharacterizationObservation
StructureFeature
```

These objects remain single-document semantics and should stay separate from
collection projection concerns.

### Comparison Semantic Layer

The comparison-semantic layer should live in:

- [`../../../domain/core/comparison.py`](../../../domain/core/comparison.py)

The recommended shape is:

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
    statistic_type: str | None = None
    uncertainty: str | None = None


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

- `ComparableResult` is derived from paper facts, not from a collection row
- `ComparableResult` does not carry `collection_id`
- normalization metadata belongs here because it defines the semantic unit
- comparability judgment does not belong inside the object itself because it is
  scope-sensitive

### Collection-Scope Relationship Layer

Collection-scoped use and judgment should be represented explicitly rather
than hidden inside the base semantic object.

The recommended shape is:

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

This layer answers:

- which comparable units are in this collection scope
- how those units were judged in that scope
- whether the unit is included, filtered, or ordered for that scope

This is the layer where `collection_id` belongs.

### Projection Layer

Projection records should be moved out of the semantic center.

The recommended shape is:

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

One acceptable target module shape is:

```text
backend/domain/core/
  document_profile.py
  evidence_backbone.py
  comparison.py
  projection.py
```

`projection.py` is not a new architecture layer. It is only a narrower home
for collection-facing projection records that should not be confused with the
comparison-semantic core.

## Target Service Responsibilities

The comparison flow should be split conceptually into three responsibilities.

### Comparable Result Assembly

`ComparableResultAssembler` should:

- read paper facts
- bind `MeasurementResult` to variant, baseline, condition, and evidence
- derive normalized comparison context
- materialize `ComparableResult`

Input:

- paper facts

Output:

- `ComparableResult`

### Comparability Evaluation

`ComparabilityEvaluator` should:

- receive `ComparableResult`
- receive collection scope or comparison policy
- compute `ComparisonAssessment`

Input:

- `ComparableResult`
- collection scope or policy

Output:

- `ComparisonAssessment`

### Row Projection

`ComparisonRowProjector` should:

- receive `ComparableResult`
- receive `CollectionComparableResult`
- produce row, report, or graph-facing projection records

Input:

- `ComparableResult`
- `CollectionComparableResult`

Output:

- `ComparisonRowRecord`

These are ownership responsibilities, not a requirement to add a new generic
service layer. The implementation may begin as direct Core-owned modules or as
a narrowing of the current comparison service, but the responsibilities should
remain explicit.

## Collection Semantics

The recommended semantic definition is:

`collection = one comparison task's working-set boundary`

It may come from:

- a user-curated paper set
- one search result set
- one saved research workspace
- one project-specific review set

It should not imply:

- permanent ownership of the underlying paper facts
- one and only one home for a comparable unit
- the first semantic layer where results become meaningful

In team language, it is safer to describe `collection` as:

- `comparison scope`
- `working set`

That interpretation matches how the system already behaves better than the
stronger "data ownership container" interpretation.

## Storage And Identity Rules

### Storage Layers

The intended storage split is:

1. fact layer
   - `MeasurementResult`
   - `SampleVariant`
   - `TestCondition`
   - `BaselineReference`
   - `EvidenceAnchor`
   - related fact artifacts
2. comparable-result layer
   - `ComparableResult`
3. collection relationship layer
   - `CollectionComparableResult`
4. projection layer
   - `ComparisonRowRecord`

`ComparisonRowRecord` may be persisted as a cache or projected on demand.

### Deterministic Comparable Result Identity

`comparable_result_id` should not be random.

It should be derived deterministically from fields such as:

- `source_result_id`
- `variant_id`
- `baseline_id`
- `test_condition_id`
- `property_normalized`
- `normalization_version`

That gives the system rebuild-stable identity for the semantic comparison
unit.

### Deterministic Row Identity

`row_id` should also stop using random `uuid4()` values.

It should be derived deterministically from fields such as:

- `collection_id`
- `comparable_result_id`
- `projection_version`

That gives stable drill-down, report references, graph references, and cache
keys across rebuilds.

## Migration Path

### Step 1: Demote `ComparisonRow`

Immediately clarify in code and docs that:

- `ComparisonRow` or `ComparisonRowRecord` is a projection
- it is not the primary comparison-semantic object

Acceptance:

- docs and type names no longer imply that the row is the semantic center
- comparison assembly logic is described as result-driven rather than row-first

### Step 2: Introduce `ComparableResult`

Add the comparison-semantic core object and its assembly path.

Acceptance:

- comparison semantics are materialized from paper facts into
  `ComparableResult`
- comparability logic consumes `ComparableResult` rather than a row record

### Step 3: Introduce Explicit Collection Relationship Modeling

Add `CollectionComparableResult` so collection-scoped judgment becomes
explicit.

Acceptance:

- collection-sensitive judgment is no longer hidden inside the base semantic
  object
- the system can distinguish reusable semantic units from one-scope
  assessment decisions

### Step 4: Keep Projection As Projection

Move row generation behind the semantic and scope layers.

Acceptance:

- `ComparisonRowRecord` is generated from semantic units plus scope-level
  assessment
- row identity is deterministic
- row projection stays downstream from the semantic center

## File Scope

Expected primary file ownership:

- `backend/domain/core/evidence_backbone.py`
- `backend/domain/core/comparison.py`
- `backend/domain/core/projection.py`
- `backend/application/core/comparison_service.py`

Likely direct implementation follow-up paths:

- `backend/tests/unit/domains/test_comparison_domain.py`
- `backend/tests/unit/services/test_paper_facts_services.py`
- `backend/tests/unit/services/test_core_report_service.py`
- `backend/tests/unit/services/test_graph_core_projection.py`

## Acceptance Criteria

- paper facts remain the canonical one-document semantic foundation
- `ComparableResult` becomes the primary comparison-semantic unit
- `collection_id` is removed from the base comparable-result object
- collection-scoped assessment is modeled explicitly rather than hidden inside
  the base object
- `ComparisonRowRecord` is documented and implemented as a projection
- row ids and comparable-result ids are derived deterministically
- comparison logic is easier to test independently from DataFrame-heavy row
  assembly

## Risks And Guardrails

Risks:

- if this plan is over-expanded, it can turn into a repository-wide domain
  rewrite instead of a narrow comparison-domain correction
- if `collection` semantics stay ambiguous, the codebase will keep mixing
  document facts, comparison scope, and UI projections
- if deterministic ids are skipped, rebuilds will continue to destabilize row
  identity and downstream references
- if the row remains the semantic center, the backend will keep hiding domain
  ambiguity inside projection records

Guardrails:

- no compatibility wrappers
- no dual semantic paths
- no Source-owned stable comparison semantics
- no random long-term row identity
- no new generic `services/` junk drawer

## Parent, Child, And Companion Relationships

### Parent Doc

- [`minimal-core-domain-backfill-plan.md`](minimal-core-domain-backfill-plan.md)
  remains the parent plan for the broader Core-domain backfill.

### Companion Docs

- [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
  records the next engineering roadmap for persistence, identity, policy, read
  paths, and projection-cache evolution after the semantic-center correction.
- [`core-llm-structured-extraction-hard-cutover-plan.md`](core-llm-structured-extraction-hard-cutover-plan.md)
  remains the extraction-contract and semantic-build companion plan.
- [`core-llm-structured-extraction-id-boundary-plan.md`](core-llm-structured-extraction-id-boundary-plan.md)
  remains the boundary-cleanup companion plan that keeps backend ids out of the
  LLM contract.

### Follow-Up Scope

If later work introduces database-backed comparable-result storage, explicit
projection versioning, or multi-scope comparison policies, record those as
later child plans rather than widening this page into an open-ended comparison
program.

## Related Docs

- [`minimal-core-domain-backfill-plan.md`](minimal-core-domain-backfill-plan.md)
- [`core-llm-structured-extraction-hard-cutover-plan.md`](core-llm-structured-extraction-hard-cutover-plan.md)
- [`core-llm-structured-extraction-id-boundary-plan.md`](core-llm-structured-extraction-id-boundary-plan.md)
- [`../../architecture/domain-architecture.md`](../../architecture/domain-architecture.md)
- [`../../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
