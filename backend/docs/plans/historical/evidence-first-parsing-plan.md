# Backend Evidence-First Parsing Refactor Plan

## Summary

This document records the originating backend-local implementation plan for
shifting literature parsing away from a protocol-first pipeline and toward an
evidence-first pipeline with conditional protocol generation.

Parts of that transition have since landed in the backend codebase. This
document now remains as historical origin context for the shift rather than the
current execution entry point.

The shared direction is defined by the following shared docs:

- [`../../../docs/overview/lens-mission-positioning.md`](../../../../docs/overview/lens-mission-positioning.md)
- [`../../../docs/contracts/lens-v1-definition.md`](../../../../docs/contracts/lens-v1-definition.md)
- [`../../../docs/architecture/lens-v1-architecture-boundary.md`](../../../../docs/architecture/lens-v1-architecture-boundary.md)
- [`../../../docs/decisions/rfc-evidence-first-literature-parsing.md`](../../../../docs/decisions/rfc-evidence-first-literature-parsing.md)

This backend plan narrows that shared direction into module-owned execution
slices, artifact changes, API adjustments, and verification targets.

Its first delivery goal is narrow:

prove the collection comparison workspace with evidence traceback as the
primary Lens v1 workflow.

This is a target implementation plan, not a description of already-implemented
backend current-state behavior.

For the current backend migration state, read
[`current-api-surface-migration-checklist.md`](../backend-wide/api-surface-migration/current-state.md).
For the active near-term execution plan, read
[`core-stabilization-and-seam-extraction-plan.md`](../core/core-stabilization-and-seam-extraction-plan.md).
For the broader parent roadmap, read
[`goal-core-source-implementation-plan.md`](../backend-wide/goal-source-core-layering/implementation-plan.md).

## Scope

This plan covers backend-owned work only:

- the first collection comparison workflow needed by Lens v1
- parsing artifact shape
- application and service responsibilities
- backend service responsibilities
- collection workspace semantics
- backend API additions and adjustments
- verification slices for backend behavior

This plan does not cover:

- frontend redesign beyond API consumption implications
- OCR or scanned PDF support
- model provider selection
- graph as a primary acceptance surface
- long-term product positioning or the v1 product boundary itself

This plan should not try to prove every surface at once.

After the first evidence-backbone implementation wave lands, the preferred next
step is to split narrower backend current-state docs such as artifact flow,
workspace semantics, and API additions rather than continuing to grow this plan
as the only backend parsing document. That split has now started.

## Proposed Change

### Primary execution focus

The first backend execution target is the collection comparison workspace.

That means the backend should prioritize:

- document profiling
- evidence cards
- comparison rows
- traceback-capable evidence access
- workspace readiness and warning states for the comparison workflow

Chat, graph, SOP, and protocol browsing may continue to exist, but they are not
the primary acceptance center for this implementation wave.

### Phase 0: Repair current protocol payload fidelity

Before changing parsing direction, make the current backend responses faithful
to stored artifacts.

Goals:

- decode structured `*_json` fields when listing protocol steps
- expose source-bearing fields such as raw evidence spans where available
- ensure current protocol APIs are not hiding structured data already present in
  artifact storage
- preserve collection-level context so the frontend can judge whether a step is
  usable

This keeps the existing system observable while larger parsing changes land.

This phase directly addresses the current tracked defect around misleading
protocol step outputs and missing structured response fields.

### Phase 1: Add document profiling as a backend artifact

Introduce a document profiling stage that classifies each paper and determines
whether protocol extraction should run.

Proposed artifact:

- `document_profiles.parquet`

Suggested fields:

- `document_id`
- `collection_id`
- `doc_type`
- `protocol_extractable`
- `protocol_extractability_signals`
- `parsing_warnings`
- `confidence`

Expected effect:

- review-heavy collections stop defaulting into final protocol step generation
- workspace can surface parsing suitability instead of only artifact existence
- downstream protocol extraction becomes explicitly gated rather than assumed

### Phase 2: Add evidence-first extraction outputs

Introduce backend services that extract evidence-oriented units before
protocol-specific units.

Primary artifact targets:

- `evidence_cards.parquet`
- `comparison_rows.parquet`

Evidence-oriented units should cover:

- claim-bearing text
- material system or composition
- process or treatment conditions
- microstructure observations
- measurement methods
- property values and units
- baseline or control references
- evidence spans and confidence

Expected effect:

- structured retrieval becomes more useful for research analysis
- the backend exposes outputs closer to the actual materials-research workflow
- the system gains first-class outputs even when protocol extraction is skipped

### Phase 3: Reposition protocol extraction behind candidate filtering

Convert protocol extraction into a conditional branch rather than the default
main parsing output.

Proposed artifact split:

- `protocol_candidates.parquet`
- `protocol_steps.parquet`

Rules:

- only protocol-suitable documents enter the branch
- low-signal or weakly supported candidate steps remain candidates or are
  dropped
- final `protocol_steps` should represent filtered, defensible steps rather than
  every keyword hit

Expected effect:

- returning zero final steps becomes acceptable for unsuitable collections
- SOP draft generation depends on stronger protocol inputs
- protocol browsing becomes a supported branch rather than the implied center of
  the backend

### Phase 4: Expand workspace and API semantics

Update workspace and collection APIs to reflect evidence-first parsing.

Suggested backend additions:

- document profile readiness
- evidence readiness
- comparison readiness
- document type distribution
- warnings for review-heavy or protocol-limited collections

Suggested API additions:

- `GET /api/v1/collections/{collection_id}/documents/profile`
- `GET /api/v1/collections/{collection_id}/evidence/cards`
- `GET /api/v1/collections/{collection_id}/comparisons`

The current protocol APIs remain, but should no longer imply that every indexed
collection is expected to produce final protocol steps.

## Artifact Model

The backend should converge toward the following artifact shape:

- `documents_raw.parquet`
- `document_profiles.parquet`
- `evidence_cards.parquet`
- `comparison_rows.parquet`
- `protocol_candidates.parquet`
- `protocol_steps.parquet`

Not every phase must land at once, but implementation should move in this
direction rather than continue deepening the old steps-first backbone.

The shared minimum field contract for these artifacts is defined in
[`../../../docs/contracts/lens-core-artifact-contracts.md`](../../../../docs/contracts/lens-core-artifact-contracts.md).

## File Change Plan

### Keep

- `backend/services/collection_service.py`
- `backend/services/task_service.py`
- `backend/services/index_task_runner.py`
- `backend/services/artifact_registry_service.py`
- graph, query, and report flows outside the protocol branch

### Add

- `backend/application/document_profile_service.py`
- `backend/application/evidence_extract_service.py`
- `backend/application/comparison_service.py`
- `backend/application/protocol_candidate_service.py`

Potential helper additions if layout-aware parsing becomes explicit:

- `backend/application/layout_block_service.py`
- `backend/application/evidence_schema_service.py`

### Reposition or replace

The following current protocol services should no longer be the sole backbone of
literature parsing:

- `backend/application/protocol_section_service.py`
- `backend/application/protocol_block_service.py`
- `backend/application/protocol_extract_service.py`
- `backend/application/protocol_pipeline_service.py`

Their future role should be one of:

- protocol-branch helper logic
- compatibility layer during migration
- fallback parser for methods-heavy documents

### API and schema touchpoints

- `backend/controllers/collections.py`
- `backend/controllers/schemas/retrieval.py`
- `backend/controllers/schemas/workspace.py`
- `backend/services/workspace_service.py`
- protocol response serializers that currently flatten or omit structured fields

## Execution Order

1. repair current protocol response decoding and evidence field exposure
2. add document profiling artifact generation
3. surface profile readiness and warnings in workspace responses
4. introduce evidence extraction artifacts
5. introduce comparison normalization artifacts
6. add collection-level APIs for profiles, evidence, and comparisons
7. only after the evidence backbone is stable, split protocol extraction into
   candidates versus final steps
8. update SOP generation to depend on filtered final protocol steps

This order is meant to preserve a usable backend while the parsing model
changes underneath it.

## Acceptance Focus

This backend plan is successful when:

- current protocol responses stop hiding structured data that already exists in
  storage
- backend readiness and workspace responses can distinguish evidence-ready
  collections from protocol-ready collections
- review-heavy corpora can complete indexing without producing misleading final
  protocol steps
- evidence and comparison artifacts become usable first-class backend outputs
- protocol remains supported for methods-heavy documents without dictating the
  entire parsing backbone
- graph remains a derived or secondary surface rather than a competing
  extraction backbone

## Verification

### Regression verification

- current experimental sample fixtures still produce usable protocol results
- existing graph and report flows remain available
- protocol APIs continue to return valid payloads after decoding changes

### New behavior verification

- review-heavy fixtures produce zero or near-zero final protocol steps
- document profiles classify fixtures into reasonable types
- evidence artifacts include conditions, measurement methods, and evidence spans
- comparison artifacts expose normalized cross-paper rows
- workspace clearly signals when a collection is protocol-limited

### Test slices

- unit tests for document profiling decisions
- unit tests for evidence extraction normalization
- unit tests for comparison-row generation
- protocol branch tests for candidate filtering and abstain behavior
- app-layer tests for new workspace and collection APIs

## Risks

- Current service relocation from `services/` to `application/` is already in
  flight, so parsing refactor work must avoid fighting the ongoing package move
- Artifact count and storage complexity will increase
- Document typing heuristics may be noisy before corpus tuning
- Mixed papers may require warnings rather than clean binary classification
- API surface growth can confuse consumers unless workspace messaging stays
  clear

## Related Docs

- [`current-api-surface-migration-checklist.md`](../backend-wide/api-surface-migration/current-state.md)
  Current backend migration state and reading order
- [`core-stabilization-and-seam-extraction-plan.md`](../core/core-stabilization-and-seam-extraction-plan.md)
  Active near-term child execution plan for the Core slice
- [`goal-core-source-implementation-plan.md`](../backend-wide/goal-source-core-layering/implementation-plan.md)
  Broader parent roadmap for later Core, Goal, and Source waves
- [`../../../docs/overview/lens-mission-positioning.md`](../../../../docs/overview/lens-mission-positioning.md)
  Shared long-lived Lens mission and positioning
- [`../../../docs/contracts/lens-v1-definition.md`](../../../../docs/contracts/lens-v1-definition.md)
  Shared Lens v1 boundary
- [`../../../docs/contracts/lens-core-artifact-contracts.md`](../../../../docs/contracts/lens-core-artifact-contracts.md)
  Shared minimum artifact contracts for the evidence backbone
- [`../../../docs/architecture/lens-v1-architecture-boundary.md`](../../../../docs/architecture/lens-v1-architecture-boundary.md)
  Shared Lens v1 architecture boundary
- [`../../../docs/decisions/rfc-evidence-first-literature-parsing.md`](../../../../docs/decisions/rfc-evidence-first-literature-parsing.md)
  Shared parsing direction RFC
- [`../architecture/overview.md`](../../architecture/overview.md)
  Current backend architecture overview
- [`../specs/api.md`](../../specs/api.md)
  Current public backend API contract
- [`../../../docs/research/materials-optimize.md`](../../../../docs/research/materials-optimize.md)
  Research-facing requirements that motivate the refactor
