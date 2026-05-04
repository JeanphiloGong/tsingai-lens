# Research View Aggregation Frontend Plan

## Purpose

This topic owns the frontend implementation plan for rendering research-view
aggregation in the collection workspace.

The shared product direction lives in
[`../../../docs/decisions/rfc-research-view-aggregation-layer.md`](../../../docs/decisions/rfc-research-view-aggregation-layer.md).
The shared frontend/backend contract lives in
[`../../../docs/contracts/research-view-aggregation-contract.md`](../../../docs/contracts/research-view-aggregation-contract.md).

This frontend topic owns browser behavior, route information architecture,
state rendering, matrix interactions, evidence drawers, and tests. Backend
aggregation semantics belong to the backend plan.

## Scope

Included:

- collapse collection primary navigation to:
  - `Overview`
  - `Documents`
  - `Comparison`
  - `Graph`
  - `More`
- render collection overview from `CollectionAggregation`
- render document coverage from `PaperCoverageRow`
- render comparison from `ComparableGroup` and `CrossPaperMatrix`
- render paper detail from `PaperAggregation`, `SampleMatrix`, and
  `ConditionSeries`
- move raw extraction-card browsing into evidence/debug surfaces
- preserve loading, empty, partial, ready, and failed states

Excluded:

- backend grouping and deduplication logic
- graph projection and layout algorithm changes
- protocol and SOP behavior changes
- wholesale visual redesign of the SvelteKit application

## Reading Path

1. Read the shared RFC:
   [`rfc-research-view-aggregation-layer.md`](../../../docs/decisions/rfc-research-view-aggregation-layer.md)
2. Read the shared contract:
   [`research-view-aggregation-contract.md`](../../../docs/contracts/research-view-aggregation-contract.md)
3. Use the frontend implementation plan:
   [`implementation-plan.md`](implementation-plan.md)

## Owning Frontend Seams

Implementation should stay in the existing frontend seams:

- `frontend/src/routes/collections/`
- `frontend/src/routes/collections/[id]/+layout.svelte`
- `frontend/src/routes/collections/[id]/+page.svelte`
- paper detail routes under `frontend/src/routes/collections/[id]/documents/`
- shared API and state helpers under `frontend/src/routes/_shared/`
- route-local tests under `frontend/src/routes/collections/`

Use the same-origin helper path. Do not introduce a second browser API
contract.

## Verification Entry

The first frontend delivery is acceptable when:

- collection tabs are `Overview / Documents / Comparison / Graph / More`
- `Documents` shows paper coverage and links to paper detail
- `Comparison` shows grouped comparison objects and matrices
- raw extracted records are no longer the main collection result list
- paper detail shows sample matrix and condition series when available
- every value can open evidence detail or show a missing-evidence warning
