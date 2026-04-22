# Core Comparable Result Phase 2 Policy Lifecycle Plan

## Summary

This child plan defines the next executable `Phase 2` wave after
document-first semantic inspection.

Its job is to make collection-scoped assessment policy lineage explicit and to
turn reassessment rules into owned artifact semantics instead of leaving them
implicit in build code.

This plan is intentionally narrower than a full policy-family platform. It
does not introduce a general policy registry, reassessment history storage, or
another service layer.

## Goal

Attach explicit policy metadata to `CollectionComparableResult` and make
reassessment triggers testable through the current comparable-result
substrate.

The intended lifecycle for this wave is:

`ComparableResult + active policy -> CollectionComparableResult assessment metadata -> explicit reassessment decision`

## Non-Goals

This child plan does not require:

- a database cutover
- reassessment history tables
- a task-level policy configuration UI
- a new generic comparison-policy service layer
- a redesign of `/comparisons`
- projection-substrate unification for graph, report, or export

## Why This Child Plan Exists

`Phase 1` established the semantic and scope artifacts.

The first `Phase 2` wave then made document-first semantic inspection
explicit.

What is still missing is policy ownership at the scope layer. Right now the
backend can say that one `CollectionComparableResult` is `comparable` or
`limited`, but it cannot state:

- which policy family and version produced that judgment
- which semantic inputs that judgment depended on
- which changes should force the judgment to be recomputed

Without this wave, collection-scoped assessment remains correct only by
convention. That makes later reuse, rebuild rules, and lifecycle debugging too
opaque.

## Current Baseline

The current baseline after the document-first inspection wave is:

- `comparable_results.parquet` is the semantic source of truth
- `collection_comparable_results.parquet` persists collection-scoped
  assessment records
- `comparison_rows.parquet` remains downstream projection/cache
- document drilldown can already read:
  `document -> comparable_results -> collection_comparable_results -> optional row projection`

But the stored collection-scoped record still only carries:

- `collection_id`
- `comparable_result_id`
- `assessment`
- `epistemic_status`
- `included`
- `sort_order`

That means policy lineage and reassessment rules are still implicit.

## Phase 2 Decision For This Wave

### Policy Metadata Belongs On The Scope Artifact

`CollectionComparableResult` remains the owning artifact for
collection-scoped judgment.

This is where policy metadata should live because:

- `ComparableResult` is reusable semantics, not scope-specific judgment
- row artifacts are projections and must not become the policy source of truth
- collection-scoped assessment is where policy is actually applied

Minimum metadata for this wave:

- `policy_family`
- `policy_version`
- `comparable_result_normalization_version`
- `assessment_input_fingerprint`
- `reassessment_triggers`

### Reassessment Must Be Triggered By Explicit Inputs

This wave should not treat reassessment as a vague rebuild side effect.

Instead, the backend should explicitly record which inputs matter for the
stored judgment and expose deterministic reasons that require recomputation.

Minimum reassessment trigger families for this wave:

- policy family changed
- policy version changed
- comparable-result normalization version changed
- assessment input fingerprint changed

The first three are lifecycle boundaries.
The fingerprint is the concrete input-set boundary for the current judgment.

### The Policy Wave Must Stay Inside Existing Ownership

`ComparisonService` remains the owning Core entrypoint.

This wave may add domain helpers and Core-owned assembly logic, but it must
not add:

- a generic policy registry abstraction
- a wrapper or compatibility facade
- a second document-specific or collection-specific service tree

## Target Artifact Semantics

### CollectionComparableResult

Each stored collection-scoped record should be able to answer:

- which active policy produced this assessment
- which comparable-result normalization version it depends on
- which fingerprint represents the effective assessment input set
- which trigger categories require reassessment

### Reassessment Decision

This wave should add an explicit domain-level comparison between:

- a stored `CollectionComparableResult`
- the current `ComparableResult`
- the current active policy identity

The output should be a deterministic set of reassessment reasons.

An empty reason set means the current scoped assessment is still valid for the
current policy and semantic input set.

## Storage And Artifact Rule

This wave should reuse the existing `Phase 1` artifacts.

No new primary artifact is required.

The intended storage rule is:

- `ComparableResult` remains the semantic truth
- `CollectionComparableResult` gains policy and lifecycle metadata
- `ComparisonRowRecord` may mirror policy metadata only if a projection needs
  it, but must not become the owner

## Execution Waves

### Wave 1: Domain Metadata And Reassessment Contract

Required work:

1. extend `CollectionComparableResult` with policy and lifecycle metadata
2. add deterministic helpers for assessment input fingerprinting
3. add deterministic reassessment-reason evaluation
4. prove round-trip behavior through domain tests

Expected outcome:

- the scope artifact can express its policy lineage and recomputation contract

### Wave 2: Assembly And Persistence Integration

Required work:

1. make comparison assembly write the new metadata
2. normalize old/missing records safely at read time
3. prove persisted scope artifacts carry the new metadata

Expected outcome:

- policy lineage is written as part of normal comparison build output

### Wave 3: Inspection Surface Exposure

Required work:

1. expose policy and lifecycle metadata through the existing document-first
   semantic inspection surface
2. keep `/comparisons` behavior stable unless an additive field is justified
3. update the owned API spec only for surfaces that actually change

Expected outcome:

- operators can inspect not only the judgment but also why and when it must be
  recomputed

## Proposed File Scope

Expected primary file ownership:

- `backend/domain/core/comparison.py`
- `backend/application/core/comparison_assembly.py`
- `backend/application/core/comparison_service.py`

Potential contract updates only if the read surface changes:

- `backend/controllers/schemas/core/documents.py`
- `backend/docs/specs/api.md`

Likely verification paths:

- `backend/tests/unit/domains/test_comparison_domain.py`
- `backend/tests/unit/services/test_paper_facts_services.py`
- document drilldown route tests only if the response schema changes

## Acceptance Criteria

- every persisted `CollectionComparableResult` carries explicit policy family
  and policy version metadata
- every persisted `CollectionComparableResult` carries a deterministic
  assessment input fingerprint
- reassessment reasons are derived explicitly, not inferred from comments
- document-first inspection can expose the new metadata without needing row
  cache
- `ComparisonService` remains the owning Core entrypoint
- no wrapper, compatibility layer, or generic policy service is introduced

## Verification

- domain tests for scope-artifact round-trip with policy metadata
- domain tests for reassessment-reason evaluation
- service tests proving collection-scoped artifacts persist the new metadata
- service or route tests proving document-first inspection can surface the new
  fields if the read contract is extended

## Relationships

- Parent roadmap:
  [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
- Parent semantic decision:
  [`core-comparable-result-domain-model-plan.md`](core-comparable-result-domain-model-plan.md)
- Phase 2 predecessor:
  [`core-comparable-result-phase2-document-first-semantic-inspection-plan.md`](core-comparable-result-phase2-document-first-semantic-inspection-plan.md)
- Likely later sibling follow-up:
  projection-substrate cutover
