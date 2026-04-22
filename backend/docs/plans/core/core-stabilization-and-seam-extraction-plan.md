# Backend Core Stabilization And Seam Extraction Plan

## Summary

This document records the next child execution plan under the broader
five-layer backend direction.

Its job is narrower:

stabilize the current Research Intelligence Core slice and extract the shared
parsing seam that still sits under the protocol branch.

This plan intentionally remains a single backend-wide child plan under
`docs/plans/`. It does not justify a deeper documentation subtree yet.

This plan remains an earlier Core child plan focused on stabilization and seam
extraction. The current near-term Core quality priority is now recorded in
[`core-parsing-quality-hardening-plan.md`](core-parsing-quality-hardening-plan.md).

For the current HTTP and route migration state, read
[`current-api-surface-migration-checklist.md`](../backend-wide/current-api-surface-migration-checklist.md).
For the broader future-wave roadmap, read
[`goal-core-source-implementation-plan.md`](../backend-wide/goal-core-source-implementation-plan.md).

## Context

The current backend shape has already moved beyond a protocol-first pipeline.

Current facts:

- `document_profiles` is a real backend artifact
- `application/evidence/` and `application/comparisons/` now exist as real
  application nodes
- indexing already runs
  a Core-first route family that should now be interpreted as
  `document_profiles -> paper facts family -> evidence_cards plus
  comparable-result substrate -> row projection -> protocol`
- workspace and artifact registry already expose Core-oriented readiness fields

The remaining near-term architecture problem is not the absence of layers. The
problem is that the current Core slice is still partially coupled to protocol-
owned parsing helpers.

Today:

- `application/documents/service.py` imports
  `application.protocol.section_service`
- `application/documents/service.py` imports
  `application.protocol.source_service`
- `application/evidence/service.py` imports the same protocol-owned helpers
- protocol is therefore still the owner of corpus parsing primitives that
  should belong to the Core path

This child plan exists to finish the current Core slice before broader Goal or
Source work proceeds.

## Scope

This plan covers:

- Core artifact stabilization for real collections
- readiness and route semantics alignment for the Core slice
- extraction of a Core-owned shared parsing seam
- protocol boundary repair after seam extraction

This plan does not cover:

- Goal Brief / Intake or Goal Consumer contracts
- external search, crawler, or connector implementation
- major package-tree reshuffles outside the affected seam
- broader protocol sophistication beyond the required branch boundary repair

## Proposed Change

### Execution Goal

Make the current collection-backed Core slice stable enough that:

- real collections can reliably expose the public document-profile, evidence,
  and comparison route family over a stable paper-facts layer
- workspace, task, and artifact readiness all describe the same state
- protocol remains downstream of the Core
- shared parsing helpers no longer live under protocol-owned modules

### Phase 1: Stabilize Core Artifacts

Goal:

- make `document_profiles`, the underlying paper-facts layer, and the derived
  evidence/comparison views reliable real outputs for non-mock collections

Primary changes:

- align artifact persistence behavior for empty versus non-empty Core outputs
- stabilize real collection reads for:
  - `/documents/profiles`
  - `/evidence/cards`
  - `/comparisons`
- tighten comparison-row inclusion rules so the comparison surface remains
  collection-facing rather than becoming a dump of low-value context rows
- keep `document_profiles` as the first gating artifact for the protocol branch

Expected result:

- the backend has one stable Core slice before broader Goal Brief or Goal
  Consumer work starts

### Phase 2: Align Readiness And Route Semantics

Goal:

- make task, artifact, workspace, and route semantics tell the same story

Primary changes:

- align artifact-registry readiness with actual Core artifact presence and
  usability
- align workspace summary states with Core-first workflow meaning
- distinguish:
  - collection missing
  - stage not ready
  - stage completed with empty results
- keep protocol-limited collections readable as successful Core outputs instead
  of failed collections

Expected result:

- frontend and operators can infer collection state without guessing from
  mismatched booleans or route errors

### Phase 3: Extract A Core-Owned Parsing Seam

Goal:

- move shared parsing helpers out of protocol-owned modules

Primary seam candidates:

- document-record assembly
- collection output loading for shared corpus inputs
- section derivation used by documents and evidence

Preferred placement:

- keep the seam close to the Core path
- prefer a narrow location under `application/documents/` or a nearby Core-
  owned package
- avoid broad catch-all nodes such as `application/core/`,
  `application/common/`, or `application/utils/`

Boundary target:

- `documents`, `evidence`, `comparisons`, and `protocol` should all depend on
  the same upstream Core parsing seam
- protocol should consume that seam, not own it

Expected result:

- the Core path can evolve independently from protocol branch details

### Phase 4: Reconfirm Protocol As A Downstream Branch

Goal:

- repair the branch boundary after seam extraction

Primary changes:

- keep protocol execution behind Core-owned suitability and readiness
- prevent protocol artifact absence from redefining Core success
- prepare for later `protocol_candidates` versus `protocol_steps` separation if
  filtering needs to become explicit

Expected result:

- protocol remains supported without reclaiming ownership of the main parsing
  backbone

## File Change Plan

### Core Stabilization

- `application/documents/service.py`
- `application/evidence/service.py`
- `application/comparisons/service.py`
- `application/workspace/service.py`
- `application/workspace/artifact_registry_service.py`
- `application/indexing/index_task_runner.py`
- `controllers/documents.py`
- `controllers/evidence.py`
- `controllers/comparisons.py`
- `controllers/schemas/workspace.py`
- `controllers/schemas/task.py`

### Seam Extraction

- `application/protocol/source_service.py`
- `application/protocol/section_service.py`
- new Core-owned parsing location under `application/documents/` or equivalent
- import sites in:
  - `application/documents/service.py`
  - `application/evidence/service.py`
  - `application/protocol/pipeline_service.py`

### Protocol Boundary Repair

- `application/protocol/pipeline_service.py`
- `application/protocol/extract_service.py`
- `application/protocol/search_service.py`
- `application/protocol/sop_service.py`

## Verification

### Regression Verification

- current collection upload, indexing, workspace, graph, report, and query
  flows remain intact
- protocol-capable collections still produce usable protocol outputs after seam
  extraction
- route paths and top-level collection workflow remain unchanged

### New Behavior Verification

- real collections can read `document_profiles`, `evidence_cards`, and
  `comparison_rows`
- workspace and task payloads express Core-first readiness consistently
- protocol-limited collections can still complete indexing successfully
- `documents` and `evidence` no longer import shared parsing helpers from
  protocol-owned modules
- protocol continues to work as a downstream branch over the extracted seam

### Suggested Test Slices

- unit tests for Core artifact generation and normalization
- unit tests for workspace readiness semantics
- unit tests for route-level 404 versus 409 versus empty-result behavior
- integration tests for Core-first task-stage progression
- regression tests for protocol outputs after seam extraction

## Risks

- current Core rollout work is still moving, so seam extraction must not fight
  active implementation changes
- empty-result semantics can drift across task, workspace, and route layers if
  they are updated independently
- moving section or source helpers too broadly will create a new junk-drawer
  abstraction
- protocol regressions are likely if seam extraction happens without targeted
  regression tests

## Related Docs

- [`current-api-surface-migration-checklist.md`](../backend-wide/current-api-surface-migration-checklist.md)
- [`goal-core-source-implementation-plan.md`](../backend-wide/goal-core-source-implementation-plan.md)
- [`evidence-first-parsing-plan.md`](../historical/evidence-first-parsing-plan.md)
- [`../architecture/goal-core-source-layering.md`](../../architecture/goal-core-source-layering.md)
- [`../architecture/domain-architecture.md`](../../architecture/domain-architecture.md)
- [`../../../application/core/README.md`](../../../application/core/README.md)
- [`../../../application/derived/protocol/README.md`](../../../application/derived/protocol/README.md)
- [`../../../application/source/README.md`](../../../application/source/README.md)
