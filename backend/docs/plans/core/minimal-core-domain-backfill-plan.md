# Minimal Core Domain Backfill Plan

## Summary

This document records the next backend-local cleanup wave for making the
`domain/` package carry real Core research semantics instead of remaining a
thin `ports + protocol` shell.

The recommended scope is intentionally narrow:

- backfill stable Core domain objects and value semantics
- move stable judgment rules out of `application/core/*` services
- keep Source engine runtime, parser workflow, and parquet execution details
  outside `domain/`

This is a domain-model backfill plan, not a parser-replacement plan and not a
full repository-layer redesign.

Read this plan with:

- [`../architecture/domain-architecture.md`](../../architecture/domain-architecture.md)
- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
- [`../architecture/core-comparison/README.md`](../../architecture/core-comparison/README.md)
- [`goal-source-core-business-layer-alignment-plan.md`](../backend-wide/goal-source-core-layering/proposal.md)
- [`materials-comparison-v2-plan.md`](../backend-wide/materials-comparison-v2/implementation-plan.md)
- [`../historical/comparable-result/core-comparable-result-domain-model-plan.md`](../historical/comparable-result/core-comparable-result-domain-model-plan.md)
- [`../historical/comparable-result/core-comparable-result-evolution-roadmap-plan.md`](../historical/comparable-result/core-comparable-result-evolution-roadmap-plan.md)

## Context

The backend has already made major progress on package and runtime boundaries:

- `goal / source / core / derived` is now explicit in `application/`,
  `controllers/`, and `infra/`
- active Source runtime now lives under `infra/source/*`
- Core-first graph and report cutover has already happened

But one important gap remains:

the backend's most important research semantics still mostly live inside
application services and parquet-oriented row builders rather than in explicit
domain models.

Today the `domain/` package is very small:

- [`../../domain/ports.py`](../../../domain/ports.py)
  owns collection, task, and artifact repository protocols
- [`../../domain/protocol.py`](../../../domain/protocol.py)
  owns protocol-oriented dataclasses

Meanwhile, stable Core semantics currently live elsewhere:

- document-profile classification and suitability heuristics live in
  [`../../application/core/semantic_build/document_profile_service.py`](../../../application/core/semantic_build/document_profile_service.py)
- sample/result/test-condition/baseline semantics live in
  [`../../application/core/semantic_build/paper_facts_service.py`](../../../application/core/semantic_build/paper_facts_service.py)
- comparison-row semantics and comparability judgments live in
  [`../../application/core/comparison_service.py`](../../../application/core/comparison_service.py)
- collection and handoff state normalization lives in
  [`../../application/source/collection_service.py`](../../../application/source/collection_service.py)

That makes the current codebase workable, but it leaves two architectural
problems:

- `domain/` does not yet represent the stable research objects the system now
  depends on
- `application/` mixes orchestration with object semantics and judgment rules

## Scope

This plan covers:

- introducing minimal, stable Core domain objects under `backend/domain/`
- moving stable value semantics and judgment rules out of
  `application/core/*`
- keeping application services as orchestrators, loaders, and persistence
  boundaries
- adding targeted unit coverage for domain objects and rules

This plan does not cover:

- parser-engine replacement work
- Source runtime or workflow redesign
- pandas/parquet retirement
- public API contract changes
- Graph or protocol feature expansion
- a full DDD rewrite of every backend package

## Design Rules

- only move stable research semantics into `domain/`
- do not mirror every parquet table one-to-one as a domain model
- do not move pipeline runtime, parser config, or storage adapters into
  `domain/`
- keep `application/*` responsible for orchestration and IO boundaries
- keep `infra/*` responsible for execution details and persistence mechanisms
- do not add compatibility layers or duplicate object paths
- rewrite callers directly when a domain object becomes the new real shape
- prefer dataclasses and small value objects over heavyweight abstraction

## Why This Plan Exists

The backend now has a stronger Core backbone than its `domain/` package shows.

The main stable research objects are no longer hypothetical:

- `document_profiles`
- `evidence_cards`
- `characterization_observations`
- `structure_features`
- `test_conditions`
- `baseline_references`
- `sample_variants`
- `measurement_results`
- `comparison_rows`

Those artifacts are already part of the runtime contract and downstream
behavior.
What is missing is the code-level semantic center that should define:

- what these objects mean
- which fields are stable semantics versus storage-only fields
- which statuses and classifications are valid
- where comparability and epistemic judgments belong

Without this backfill, the codebase will continue to accumulate:

- large service-local constant blocks
- service-local status literals
- duplicated normalization rules
- comparability and review logic that is harder to test independently from
  pandas and parquet

## Proposed Change

The backend should treat `domain/` as the home of stable research objects and
judgment semantics, not merely as a repository-port container.

The minimal target is:

```text
backend/domain/
  __init__.py
  ports.py
  protocol.py
  shared/
    enums.py
    values.py
  core/
    document_profile.py
    paper_facts.py
    comparison.py
    projection.py
  source/
    collection.py
    artifact_status.py
```

The first implementation waves should focus on Core, not on Source.

That means:

- introduce shared enums and value objects first
- introduce Core research objects second
- move comparison and suitability rules third
- delay Source-record domainization until the Source contract is calmer

## Domain Ownership Rules

### What Should Move Into `domain/`

Stable research semantics:

- `DocumentProfile`
- `MethodFact`
- `EvidenceAnchor`
- `CharacterizationObservation`
- `StructureFeature`
- `TestCondition`
- `BaselineReference`
- `SampleVariant`
- `MeasurementResult`
- `EvidenceCardView`
- `ComparableResult`
- `CollectionComparableResult`
- `ComparisonAssessment`
- `ComparisonRowRecord` only when it is kept explicitly as a projection record
  rather than as the semantic center

Stable value and judgment semantics:

- `EpistemicStatus`
- `ComparabilityStatus`
- `TraceabilityStatus`
- document type and protocol suitability classifications
- expert-review and missing-context judgment rules

### What Should Not Move Into `domain/`

Execution details and engine internals:

- Source pipeline workflow definitions
- parser or OCR runtime configuration
- pandas/parquet serialization details
- filesystem layout and artifact path helpers
- cache, storage, and callback plumbing
- third-party engine wrappers

## Initial Target Mapping

### Shared Values

Move stable literals and small value semantics out of service-local constant
blocks into:

- `domain/shared/enums.py`
- `domain/shared/values.py`

Candidates include:

- epistemic statuses now defined inside
  [`../../application/core/semantic_build/paper_facts_service.py`](../../../application/core/semantic_build/paper_facts_service.py)
- comparability and review status literals now defined inside
  [`../../application/core/comparison_service.py`](../../../application/core/comparison_service.py)
- document-kind and suitability classifications now inferred inside
  [`../../application/core/semantic_build/document_profile_service.py`](../../../application/core/semantic_build/document_profile_service.py)

### Core Domain Objects

Move stable Core object definitions into:

- `domain/core/document_profile.py`
- `domain/core/paper_facts.py`
- `domain/core/comparison.py`

The application layer should continue to:

- load artifacts
- convert rows and payloads into domain objects
- call domain rules
- write normalized artifact outputs

The application layer should stop owning:

- the canonical field semantics of those objects
- stable status enumerations
- comparability and suitability decision rules

### Source Domain Objects

Source-record domainization should be delayed and narrowed.

Only after the current Source handoff is judged stable should the backend add:

- `CollectionRecord`
- `GoalBriefHandoff`
- `ArtifactStatus`

Even then, the domain boundary should remain narrow:

- business record semantics may move in
- Source pipeline runtime and ingestion mechanics must stay out

## Wave Plan

### Wave A: Shared Domain Values

Objective:

extract stable enum-like and value-like semantics from Core services.

Actions:

- add `domain/shared/enums.py`
- add `domain/shared/values.py`
- move stable status literals and tiny normalization helpers there
- rewrite Core services to consume those shared domain values directly

Acceptance:

- Core services no longer define large repeated status-literal blocks
- shared statuses can be unit tested without pandas or parquet

### Wave B: Document Profile Domainization

Objective:

move document-profile semantics and suitability rules into `domain/core`.

Actions:

- add `domain/core/document_profile.py`
- define a `DocumentProfile` object and supporting classifications
- move review/protocol-suitability rules out of
  `application/core/semantic_build/document_profile_service.py`
- keep the service responsible for artifact IO and collection-scoped assembly

Acceptance:

- document-profile decision rules are testable independently of artifact IO
- application service becomes primarily orchestration and serialization logic

### Wave C: Paper-Facts Domainization

Objective:

introduce explicit Core objects for the stable sample/result backbone.

Actions:

- add `domain/core/paper_facts.py`
- define stable dataclasses for:
  - `EvidenceAnchor`
  - `MethodFact`
  - `CharacterizationObservation`
  - `StructureFeature`
  - `TestCondition`
  - `BaselineReference`
  - `SampleVariant`
  - `MeasurementResult`
- move canonical field semantics and small object-local invariants there

Acceptance:

- `application/core/semantic_build/paper_facts_service.py` no longer acts as the only
  canonical home of these object definitions
- artifact writers build domain objects before storage normalization

### Wave D: Comparison Judgment Domainization

Objective:

move comparison semantics and scope-sensitive review semantics into
`domain/core/comparison.py`, while keeping row projection downstream from the
semantic center.

Actions:

- follow the narrowed comparison child plan recorded in
  [`../../architecture/core-comparison/decision.md`](../../architecture/core-comparison/decision.md)
- define `ComparableResult`
- define `CollectionComparableResult`
- define `ComparisonAssessment`
- if a row record remains in domain ownership, keep it explicitly
  projection-only in `domain/core/projection.py` or another equally narrow
  projection home
- define comparison judgment inputs and outputs
- move:
  - comparability status rules
  - missing critical context rules
  - expert review gating
  - assessment epistemic status rules
  out of `application/core/comparison_service.py`

Acceptance:

- comparison semantic logic is centered on comparable results rather than on
  comparison rows
- comparison judgment logic is testable without DataFrame-heavy setup
- comparison service focuses on loading inputs, invoking rules, and writing
  outputs

### Wave E: Narrow Source Record Backfill

Objective:

backfill only the stable Source business records after Core is done.

Actions:

- add `domain/source/collection.py`
- add `domain/source/artifact_status.py`
- move collection-record normalization and artifact-status semantics out of
  `application/source/collection_service.py` where appropriate

Acceptance:

- collection and artifact-status semantics stop being raw `dict` contracts only
- Source pipeline runtime remains outside `domain/`

## File Change Plan

The expected implementation slices are:

1. Add new domain files:
   - `backend/domain/shared/enums.py`
   - `backend/domain/shared/values.py`
   - `backend/domain/core/document_profile.py`
   - `backend/domain/core/paper_facts.py`
   - `backend/domain/core/comparison.py`
   - `backend/domain/core/projection.py`
   - later, if justified:
     - `backend/domain/source/collection.py`
     - `backend/domain/source/artifact_status.py`

2. Rewrite application callers:
   - `backend/application/core/semantic_build/document_profile_service.py`
   - `backend/application/core/semantic_build/paper_facts_service.py`
   - `backend/application/core/comparison_service.py`
   - later:
     - `backend/application/source/collection_service.py`

3. Add targeted tests:
   - new unit tests for domain objects and rule functions
   - keep existing service tests, but reduce rule duplication in them

4. Update backend docs only where needed:
   - this plan page
   - backend docs index if discovery changes
   - only update architecture pages if the architectural statement itself
     changes

## Verification

Structural checks after the first useful wave:

- `backend/domain/` contains real Core-domain files, not only `ports.py`
  and `protocol.py`
- stable statuses no longer live only in application-service constant blocks
- Core application services import domain objects and values directly

Behavioral checks:

- unit tests for domain objects and comparison/profile rules
- existing service tests for:
  - document profiles
  - evidence backbone generation
  - comparisons
  - workspace readiness
- targeted regression checks that artifact outputs remain contract-compatible

## Risks

- If this plan is done too aggressively, `domain/` can become a storage-schema
  mirror rather than a semantic layer.
- If Source records are domainized too early, the backend will freeze unstable
  ingestion-era contracts in the wrong place.
- If application services keep both old literals and new domain semantics for
  too long, the codebase will temporarily get more confusing instead of less.

The main guardrail is to move only stable semantics and to rewrite callers
directly in each wave.

## Non-Goals And Guardrails

- do not turn this into a repository-wide DDD rewrite
- do not model every parquet table as a first-class domain object
- do not move pipeline runtime or parser-engine details into `domain/`
- do not add adapters, wrappers, or compatibility models solely to bridge old
  and new shapes
- do not change frontend-facing API contracts as part of the domain backfill

## Relationship To Existing Plans

This plan follows, but does not replace:

- [`goal-source-core-business-layer-alignment-plan.md`](../backend-wide/goal-source-core-layering/proposal.md)
  which made the business-layer split visible in package layout
- [`materials-comparison-v2-plan.md`](../backend-wide/materials-comparison-v2/implementation-plan.md)
  which established the stronger sample/result Core backbone
- [`../../architecture/core-comparison/decision.md`](../../architecture/core-comparison/decision.md)
  which is the current authority for `ComparableResult` as the semantic center
  and `ComparisonRowRecord` as projection
- [`../historical/comparable-result/core-comparable-result-evolution-roadmap-plan.md`](../historical/comparable-result/core-comparable-result-evolution-roadmap-plan.md)
  which retains the original persistence, identity, policy, read-path, and
  projection-cache rollout lineage

Those plans made the runtime backbone clearer.
This plan makes the code-level semantic center match that backbone.
