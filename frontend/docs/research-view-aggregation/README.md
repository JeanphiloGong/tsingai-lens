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
  - `Materials`
  - `Papers`
  - `Graph`
  - `More`
- render collection overview from `CollectionAggregation`
- render material summaries and material profile entry points
- render paper coverage from `PaperCoverageRow`
- render comparison inside material profile from `ComparableGroup` and
  `CrossPaperMatrix`
- render paper-scoped material summaries and "Material In This Paper" drilldown
  when paper detail needs a local material view
- render paper detail from `PaperAggregation`, `SampleMatrix`, and
  `ConditionSeries`
- move raw extraction-card browsing into evidence/debug surfaces
- keep global all-comparison browsing under `More`
- preserve loading, empty, partial, ready, and failed states

Excluded:

- backend grouping and deduplication logic
- graph projection and layout algorithm changes
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

- collection tabs are `Overview / Materials / Papers / Graph / More`
- `Materials` shows canonical materials and links to material profiles
- material profiles show papers, sample matrix, process ranges, property
  summaries, comparisons, condition series, and evidence
- `Papers` shows paper coverage and links to paper detail
- paper detail can show materials inside one paper without becoming a
  collection material profile
- `More / All Comparisons` shows grouped comparison objects and matrices when
  users need a global comparison browser
- raw extracted records are no longer the main collection result list
- paper detail shows sample matrix and condition series when available
- every value can open evidence detail or show a missing-evidence warning
