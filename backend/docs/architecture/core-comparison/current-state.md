# Retired Core Comparison Current State

## Summary

Comparable-result and comparison-row records remain only for offline evaluation
and extraction-trace export. They are not maintained browser resources.

The product chain is:

`Source -> Objective -> published analysis -> Finding -> ObjectiveEvidence`

## Retained Offline Artifact Chain

### Semantic Truth

- `comparable_results`
  reusable `ComparableResult` records for one collection build output

### Scope Truth

- `collection_comparable_results`
  current collection-scoped overlays with assessment and policy metadata

### Deterministic Projection

- `comparison_rows`
  offline projection regenerated from semantic and scope artifacts; it is not
  persisted

## Product Read Path

The frontend comparison overview reads Objectives and their published Findings.
Finding review reads versioned ObjectiveEvidence, whose stable Source locator
opens the document reader. No comparison-row, comparable-result,
comparison-semantics, or graph endpoint is registered.

## Current Ownership In Code

- [`../../../domain/core/comparison.py`](../../../domain/core/comparison.py)
  accepted dataclasses, ids, assessments, and reassessment logic
- [`../../../domain/core/comparison_assembly.py`](../../../domain/core/comparison_assembly.py)
  materialization of comparable-result and scope artifacts
- [`../../../domain/core/comparison_projection.py`](../../../domain/core/comparison_projection.py)
  row projection from semantic artifacts
- [`../../../infra/persistence/postgres/comparison_repository.py`](../../../infra/persistence/postgres/comparison_repository.py)
  retained storage adapter used by offline evaluation and export tooling
- [`../../../application/derived/core_fact_projection.py`](../../../application/derived/core_fact_projection.py)
  retained legacy projection used by extraction-trace export tooling

## Current Contract Notes

- public API authority is [`../../specs/api.md`](../../specs/api.md)
- workspace readiness is based on Source documents, DocumentProfiles, and
  Objective candidates
- comparison records are not task artifacts or browser readiness signals

## Remaining Guardrails

- do not reintroduce retired product routes or browser clients
- do not rebuild Findings from comparison records
- keep offline evaluation ownership isolated from the product read path

## Related Docs

- [`decision.md`](decision.md)
- [`../../specs/api.md`](../../specs/api.md)
- [`../overview.md`](../overview.md)
