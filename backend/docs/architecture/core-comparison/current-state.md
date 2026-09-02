# Retired Core Comparison Current State

## Summary

The retired material-first comparison substrate has been removed. Comparable
results, collection overlays, row projections, and their assembly and
assessment helpers are not maintained runtime, evaluation, or browser
resources.

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

Objective analysis owns comparison directly through its Evidence and Finding
modules. `ObjectiveEvidenceComparison` records the conditions of one grounded
within-paper comparison; `Finding` synthesizes agreement, conflict, and limits
across those versioned Evidence records. There is no comparison repository,
comparison domain module, Core-fact projection service, or fallback substrate.

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
