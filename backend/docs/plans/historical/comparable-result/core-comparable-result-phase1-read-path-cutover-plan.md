# Core Comparable Result Phase 1 Read-Path Cutover Plan

Historical note: this page is retained lineage. Use
[`../../../architecture/core-comparison/decision.md`](../../../architecture/core-comparison/decision.md)
for the current semantic authority and
[`../../../architecture/core-comparison/current-state.md`](../../../architecture/core-comparison/current-state.md)
for the implemented substrate.

## Summary

This child plan defines how `Phase 1` cuts the collection-first comparison read
path over to the new semantic and scope artifacts while preserving the current
collection-facing API surface.

The key rule is that the read path becomes explicit even if some downstream
views still temporarily consume row cache.

## Goal

Make the primary Lens v1 comparison path read as:

`collection -> collection_comparable_results -> comparable_results -> row projection/cache`

## Non-Goals

- public API redesign
- corpus-first query
- immediate graph/report substrate unification
- removing row cache entirely

## Phase 1 Read-Path Rules

### Required Primary Path

The collection comparison table must be explainable through:

- collection-scoped membership and assessment
- reusable comparable-result semantics
- downstream row projection/cache

### Allowed Temporary Path

Graph and report may continue reading `comparison_rows.parquet` during
`Phase 1`, but that dependency must be explicit and temporary.

### Deferred Path

Document-first semantic inspection may begin as an internal or debug read path,
but full productized document-first drill-down can wait for `Phase 2`.

## Migration Order

1. land the persistence split
2. teach the comparison read path to load scope and semantic artifacts first
3. keep row projection as the collection-facing cache/output
4. document temporary downstream consumers that still read row cache directly
5. avoid adding new view-specific semantic assemblers

## Stability Rule

This cutover should preserve:

- `/comparisons` response shape
- collection route structure
- existing collection-facing row semantics, except where deterministic identity
  or semantic-boundary cleanup requires correction

## File Scope

Expected primary file ownership:

- `backend/application/core/comparison_service.py`
- `backend/application/core/workspace_overview_service.py`
- `backend/application/derived/graph_projection_service.py`
- `backend/application/derived/report_service.py`

Likely verification paths:

- `backend/tests/unit/services/test_core_report_service.py`
- `backend/tests/unit/services/test_graph_core_projection.py`
- comparison-service or controller tests that cover `/comparisons`

## Acceptance Criteria

- collection-first comparison reads are explicitly backed by semantic and scope
  artifacts
- `/comparisons` stays stable as a collection-facing projection surface
- graph/report row-cache dependency is documented rather than implicit
- no new hidden semantic path is introduced just for one downstream view

## Verification

- targeted `/comparisons` API or service-shape regression coverage
- graph/report tests proving temporary row-cache dependency still works
- tests that fail if semantic and scope artifacts are missing but row cache is
  treated as semantic source of truth

## Relationships

- Parent roadmap:
  [`core-comparable-result-evolution-roadmap-plan.md`](core-comparable-result-evolution-roadmap-plan.md)
- Sibling child plans:
  [`core-comparable-result-phase1-persistence-split-plan.md`](core-comparable-result-phase1-persistence-split-plan.md)
  and
  [`core-comparable-result-phase1-service-boundary-plan.md`](core-comparable-result-phase1-service-boundary-plan.md)
