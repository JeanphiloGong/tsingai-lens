# Research View Aggregation Backend Plan

## Purpose

This topic owns the backend implementation plan for the research-view
aggregation contract.

The shared product direction lives in
[`../../../../../docs/decisions/rfc-research-view-aggregation-layer.md`](../../../../../docs/decisions/rfc-research-view-aggregation-layer.md).
The shared frontend/backend contract lives in
[`../../../../../docs/contracts/research-view-aggregation-contract.md`](../../../../../docs/contracts/research-view-aggregation-contract.md).

This backend topic only owns backend implementation work: aggregation services,
schemas, API endpoints, evidence binding, tests, and evaluation checks.

## Scope

Included:

- derive paper-level sample matrices from paper facts
- derive paper-scoped material summaries and optional document material
  profiles from paper facts
- derive paper-level condition series from paper facts
- derive collection-level material summaries and material profiles from paper
  facts and comparison rows
- derive collection-level paper coverage from document profiles and fact
  availability
- derive comparable groups and cross-paper matrices from comparison inputs and
  attach them to material context
- preserve evidence references and warnings in every aggregate value
- expose same-origin `/api/v1/*` read endpoints for the frontend
- verify the first PBF-metal slice against expert gold data

Excluded:

- frontend route layout and component implementation
- final database persistence changes unless the first service response proves
  that persistence is needed
- protocol generation and SOP surfaces
- graph layout changes

## Reading Path

1. Read the shared RFC:
   [`rfc-research-view-aggregation-layer.md`](../../../../../docs/decisions/rfc-research-view-aggregation-layer.md)
2. Read the shared contract:
   [`research-view-aggregation-contract.md`](../../../../../docs/contracts/research-view-aggregation-contract.md)
3. Use the backend implementation plan:
   [`implementation-plan.md`](implementation-plan.md)
4. For the current six-paper 316L repair wave, use
   [`material-profile-aggregation-repair-plan.md`](material-profile-aggregation-repair-plan.md)
5. For the current material page synthesis direction, use the ResearchUnderstanding
   contract in [`../../../specs/api.md`](../../../specs/api.md) and the
   collection-build pipeline implementation.

## Ownership

Backend implementation should stay under the existing Core application and
controller seams:

- `backend/application/core/`
- `backend/application/core/semantic_build/`
- `backend/controllers/core/`
- `backend/controllers/schemas/core/`
- `backend/tests/unit/services/`
- `backend/tests/unit/routers/`
- `backend/tests/integration/`

The implementation should not put frontend-specific grouping rules into route
components or browser helpers.

## Verification Entry

The first backend delivery is acceptable when it can build:

- a paper detail sample matrix for the P001-style 316L paper without duplicate
  visible rows
- paper-scoped material summaries, and when needed a document material profile
  that stays inside one source document
- one material summary per canonical material, with aliases merged rather than
  split into duplicate material cards
- one material profile that contains papers, sample matrix, process ranges,
  property summaries, comparison groups, condition series, evidence, and
  warnings for that material
- the current six-paper 316L validation collection keeps all six papers under
  `mat-316l-stainless-steel` and does not expose process media such as argon
  as material profiles
- paper coverage rows for a collection
- at least one material-scoped comparable group or a clear partial-state warning
- evidence references for observed matrix values
- explicit warnings for unresolved sample, process, condition, and evidence
  binding
