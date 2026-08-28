# Retired Core Comparison Current State

## Summary

Comparable-result and comparison-row persistence and projection code have been
removed. They are not maintained runtime, evaluation, or browser resources.

The product chain is:

`Source -> Objective -> published analysis -> Finding -> ObjectiveEvidence`

## Retired Artifact Chain

### Semantic Truth

- `comparable_results`
  Former reusable normalized comparison records.

### Scope Truth

- `collection_comparable_results`
  Former Collection overlays over comparable results.

### Deterministic Projection

- `comparison_rows`
  Former deterministic row projection.

## Product Read Path

The frontend comparison overview reads Objectives and their published Findings.
Finding review reads versioned ObjectiveEvidence, whose stable Source locator
opens the document reader. No comparison-row, comparable-result,
comparison-semantics, or graph endpoint is registered.

## Current Ownership In Code

Objective analysis now owns comparison directly through its Evidence and
Finding modules. The retired comparison domain helpers may remain as private
scientific utilities only where directly imported by Objective analysis; there
is no comparison repository or Core-fact projection service.

## Current Contract Notes

- public API authority is [`../../specs/api.md`](../../specs/api.md)
- readiness is per Document; selected ready Documents feed Objective discovery
  and analysis
- comparison records are not task artifacts or browser readiness signals

## Remaining Guardrails

- do not reintroduce retired product routes or browser clients
- do not rebuild Findings from comparison records
- keep evaluation snapshots tied to published Objective Findings and Evidence

## Related Docs

- [`decision.md`](decision.md)
- [`../../specs/api.md`](../../specs/api.md)
- [`../overview.md`](../overview.md)
